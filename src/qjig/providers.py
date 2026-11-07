"""Provider boundary: typed validation of responses, every attempt journaled and budgeted.

HTTP success with unusable output is a failure that keeps a receipt (raw text and hash), not a value.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from .budgets import BudgetLedger
from .journal import UncertainOutcome
from .logic import Observation, Outcome


class ProviderUnavailable(Exception):
    """The request definitely never reached the provider."""


@dataclass(frozen=True)
class ProviderRequest:
    stage: str
    provider: str
    model: str
    prompt: str
    max_tokens: int

    def input_sha256(self) -> str:
        blob = json.dumps(
            {"stage": self.stage, "provider": self.provider, "model": self.model, "prompt": self.prompt, "max_tokens": self.max_tokens},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawResponse:
    http_status: int
    body: str
    usage: dict[str, Any] | None  # as reported by the provider; None = not reported


class Transport(Protocol):
    label: str

    def send(self, request: ProviderRequest) -> RawResponse: ...


class StandInTransport:
    """STAND-IN: returns authored responses in order. Not a model; proves mechanics only."""

    label = "STAND_IN: authored responses, not a model"

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.calls_made = 0

    def send(self, request: ProviderRequest) -> RawResponse:
        assert self._responses, "stand-in has no authored response left"
        self.calls_made += 1
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@dataclass(frozen=True)
class FieldSpec:
    type: type
    enum: tuple | None = None


@dataclass(frozen=True)
class TypedCall:
    ok: bool
    value: dict[str, Any] | None
    failure: str | None  # malformed_output | schema_violation | http_error
    call_id: str
    raw_sha256: str
    usage: dict[str, Any] | None


def _validate(text: str, schema: dict[str, FieldSpec]) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None, "malformed_output"
    if not isinstance(data, dict) or set(data) != set(schema):
        return None, "schema_violation"
    for name, spec in schema.items():
        v = data[name]
        if type(v) is not spec.type or (spec.enum is not None and v not in spec.enum):
            return None, "schema_violation"
    return data, None


def call_typed(ledger: BudgetLedger, transport: Transport, request: ProviderRequest, schema: dict[str, FieldSpec]) -> TypedCall:
    """One budgeted, journaled provider attempt returning a validated value or an explicit failure."""

    def attempt():
        try:
            raw = transport.send(request)
        except TimeoutError as exc:  # sent, outcome unknown
            raise UncertainOutcome(f"timeout: {exc}") from exc
        digest = hashlib.sha256(raw.body.encode("utf-8")).hexdigest()
        if not 200 <= raw.http_status < 300:
            value, failure = None, "http_error"
        else:
            value, failure = _validate(raw.body, schema)
        extra = {"http_status": raw.http_status, "raw_sha256": digest, "transport": transport.label}
        if failure:
            extra.update(validation=failure, raw_response=raw.body)
        else:
            extra.update(validation="ok")
        return (value, failure, digest, raw.usage), raw.usage or {}, extra

    value, failure, digest, usage = ledger.run(
        request.stage, attempt, provider=request.provider, model=request.model,
        input_sha256=request.input_sha256(), reserve_tokens=request.max_tokens,
    )
    call_id = ledger.last_call_id()
    return TypedCall(failure is None, value, failure, call_id, digest, usage)


def unresolved_observation(call: TypedCall) -> Observation | None:
    """A failed provider call yields UNKNOWN with the failure as its reason; a good one yields None."""
    return None if call.ok else Observation(Outcome.UNKNOWN, f"provider_{call.failure}")
