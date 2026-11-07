"""Provider boundary: typed validation of responses, every attempt journaled and budgeted.

HTTP success with unusable output is a failure that keeps a receipt (raw text and hash), not a value.
"""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_CEILING, localcontext
import socket
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Protocol

from .budgets import BudgetExceeded, BudgetLedger
from .contracts import ContractError
from .pricing import upper_cost
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
    max_price: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.max_price is not None:
            value = self.max_price
            if (not isinstance(value, dict) or set(value) != {"prompt", "completion"}
                    or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in value.values())):
                raise ContractError("invalid routing price ceiling")
            object.__setattr__(self, "max_price", MappingProxyType(dict(value)))

    def input_sha256(self) -> str:
        data = {"stage": self.stage, "provider": self.provider, "model": self.model, "prompt": self.prompt, "max_tokens": self.max_tokens}
        if self.max_price is not None:
            data["max_price"] = dict(self.max_price)
        blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CallReservation:
    """A calculated reservation bound to one request; provenance is an assertion, not verification."""
    request_sha256: str
    input_tokens: int
    cost_usd: float
    pricing_sha256: str
    input_bound_provenance: str
    hold_back_calls: int = 0
    hold_back_tokens: int = 0
    hold_back_cost_usd: float = 0
    required_id: str | None = None


def make_call_reservation(request: ProviderRequest, model: dict, *, input_tokens: int, input_bound_provenance: str,
                          hold_back_calls: int = 0, hold_back_tokens: int = 0, hold_back_cost_usd: float = 0,
                          required_id: str | None = None) -> CallReservation:
    if not isinstance(input_bound_provenance, str) or not input_bound_provenance.strip():
        raise ContractError("input bound provenance is required")
    if not isinstance(model, dict) or model.get("id") != request.model:
        raise ContractError("pricing model does not match request")
    if required_id is not None and (not isinstance(required_id, str) or not required_id.strip()):
        raise ContractError("invalid required work identity")
    cost = upper_cost(model, input_tokens=input_tokens, output_tokens=request.max_tokens)
    if request.max_price is not None:
        # Ceilings are USD per million tokens. Add the catalog calculation rather
        # than assuming its other charge categories are covered by these limits.
        # This arithmetic does not verify provider enforcement or completeness.
        with localcontext() as ctx:
            ctx.rounding = ROUND_CEILING
            capped = (Decimal(str(request.max_price["prompt"])) * input_tokens
                      + Decimal(str(request.max_price["completion"])) * request.max_tokens) / Decimal(1000000)
            cost += capped
    as_float = float(cost)
    if not math.isfinite(as_float):
        raise ContractError("price bound is not representable")
    if Decimal(str(as_float)) < cost:
        as_float = math.nextafter(as_float, math.inf)
    if not math.isfinite(as_float):
        raise ContractError("price bound is not representable")
    snapshot = json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return CallReservation(request.input_sha256(), input_tokens, as_float, hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
                           input_bound_provenance, hold_back_calls, hold_back_tokens, hold_back_cost_usd, required_id)


ReservationFactory = Callable[[ProviderRequest], CallReservation]


@dataclass(frozen=True)
class RawResponse:
    http_status: int
    body: str
    usage: dict[str, Any] | None  # as reported by the provider; None = not reported
    note: str | None = None  # transport-observed cause, e.g. finish_reason
    metadata: dict[str, str] | None = None  # sanitized, selectively extracted provider fields


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


def load_env_value(path: Path, name: str) -> str | None:
    """Read one variable from a dotenv-style file at call time. Never logs or returns other values."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip("'\"") or None
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_post(url: str, headers: dict, payload: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=payload.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            return exc.code, "redirect refused"
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.gaierror, ConnectionRefusedError)):
            raise ConnectionRefusedError(str(exc.reason)) from exc  # never reached the provider
        raise TimeoutError(str(exc.reason)) from exc  # may have been sent: outcome unknown


class OpenRouterTransport:
    """LIVE transport: a real OpenRouter chat completion. Reads the key lazily from an env file; never stores it in repr."""

    label = "LIVE: openrouter, real model call"

    def __init__(self, env_path: Path, *, post: Callable[..., tuple[int, str]] = _urllib_post, timeout: float = 120.0) -> None:
        self._env_path = Path(env_path)
        self._post = post
        self._timeout = timeout

    def __repr__(self) -> str:
        return f"OpenRouterTransport(env={self._env_path.name!r})"

    def send(self, request: ProviderRequest) -> RawResponse:
        key = load_env_value(self._env_path, "OPENROUTER_API_KEY")
        if not key:
            raise ProviderUnavailable("OPENROUTER_API_KEY not available; nothing was sent")
        base = (load_env_value(self._env_path, "BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme != "https" or parsed.netloc != "openrouter.ai"
                or parsed.path != "/api/v1" or parsed.query or parsed.fragment):
            raise ProviderUnavailable("untrusted provider endpoint; nothing was sent")
        body = {
            "model": request.model, "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.max_price is not None:
            body["provider"] = {"max_price": dict(request.max_price)}
        payload = json.dumps(body, ensure_ascii=False)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        try:
            status, body = self._post(f"{base}/chat/completions", headers, payload, self._timeout)
        except (ConnectionRefusedError, socket.gaierror):
            raise ProviderUnavailable("connection failed before send") from None
        except Exception:
            # A transport error after dispatch may have executed; do not expose its text
            # or classify it as a definite failure. Reconciliation remains mandatory.
            raise TimeoutError("provider outcome unknown") from None
        body = body.replace(key, "[REDACTED]")
        try:
            parsed_body = self._redact_json(json.loads(body), key)
            body = json.dumps(parsed_body, ensure_ascii=False)
        except (ValueError, TypeError):
            parsed_body = None
        metadata = self._response_metadata(parsed_body)
        if not 200 <= status < 300:
            return RawResponse(status, body, self._usage(body), metadata=metadata)
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            note = self._no_content_note(body)
            return RawResponse(status, "", self._usage(body), note, metadata)
        return RawResponse(status, content, self._usage(body), metadata=metadata)

    @staticmethod
    def _redact_json(value: Any, secret: str) -> Any:
        if isinstance(value, str):
            return value.replace(secret, "[REDACTED]")
        if isinstance(value, list):
            return [OpenRouterTransport._redact_json(item, secret) for item in value]
        if isinstance(value, dict):
            return {OpenRouterTransport._redact_json(key, secret): OpenRouterTransport._redact_json(item, secret)
                    for key, item in value.items()}
        return value

    @staticmethod
    def _response_metadata(data: Any) -> dict[str, str] | None:
        if not isinstance(data, dict):
            return None
        candidates = {"response_id": data.get("id"), "model": data.get("model"), "provider": data.get("provider")}
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            candidates["finish_reason"] = choices[0].get("finish_reason")
        result = {key: value for key, value in candidates.items() if isinstance(value, str) and 0 < len(value) <= 512}
        return result or None

    @staticmethod
    def _no_content_note(body: str) -> str:
        try:
            reason = json.loads(body)["choices"][0].get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            reason = None
        return f"no_message_content; finish_reason={reason}"

    @staticmethod
    def _usage(body: str) -> dict[str, Any] | None:
        try:
            u = json.loads(body).get("usage")
        except (ValueError, AttributeError):
            return None
        if not isinstance(u, dict):
            return None
        cost = u.get("cost")
        return {
            "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
            "cost_usd": cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
        }


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


Validator = Callable[[str], tuple[dict | None, str | None]]


def call_typed(ledger: BudgetLedger, transport: Transport, request: ProviderRequest, schema: "dict[str, FieldSpec] | Validator", *, reservation: CallReservation | None = None, archive=None, context_binding: dict | None = None) -> TypedCall:
    """One budgeted, journaled provider attempt returning a validated value or an explicit failure."""
    if reservation is not None and (not isinstance(reservation, CallReservation) or reservation.request_sha256 != request.input_sha256()):
        raise ContractError("reservation does not match provider request")
    if isinstance(transport, OpenRouterTransport):
        raise BudgetExceeded("preflight_unavailable", "hosted calls require complete input, cost and goal-wide reservations")

    def attempt():
        call_id = ledger.last_call_id()
        if archive is not None:
            archive.record_request(call_id, request)
        try:
            raw = transport.send(request)
        except TimeoutError as exc:  # sent, outcome unknown
            if archive is not None:
                try:
                    archive.record_failure(call_id, "uncertain_outcome")
                except Exception:
                    pass  # journal still records uncertainty; do not replace it with a definite failure
            raise UncertainOutcome(f"timeout: {exc}") from exc
        except Exception:
            if archive is not None:
                archive.record_failure(call_id, "provider_failure")
            raise
        if archive is not None:
            try:
                archive.record_response(call_id, raw)
            except Exception:
                raise UncertainOutcome("response archive failed after dispatch") from None
        digest = hashlib.sha256(raw.body.encode("utf-8")).hexdigest()
        if not 200 <= raw.http_status < 300:
            value, failure = None, "http_error"
        else:
            try:
                value, failure = schema(raw.body) if callable(schema) else _validate(raw.body, schema)
            except Exception:
                # The provider did return; retain its usage without exposing validator details.
                value, failure = None, "validator_error"
        if archive is not None:
            try:
                archive.record_validation(call_id, value, failure)
            except Exception:
                raise UncertainOutcome("validation archive failed after dispatch") from None
        extra = {"http_status": raw.http_status, "raw_sha256": digest, "transport": transport.label, "metadata": raw.metadata}
        if raw.note:
            extra["note"] = raw.note
        if failure:
            extra.update(validation=failure, raw_response=raw.body)
        else:
            extra.update(validation="ok")
            if request.stage in ("judge_positive", "judge_negative", "escalation_positive", "escalation_negative"):
                extra["validated_value"] = value
                extra["raw_response"] = raw.body
        return (value, failure, digest, raw.usage), raw.usage or {}, extra

    kwargs = {} if reservation is None else {
        "reserve_input_tokens": reservation.input_tokens, "reserve_cost_usd": reservation.cost_usd,
        "hold_back_calls": reservation.hold_back_calls, "hold_back_tokens": reservation.hold_back_tokens,
        "hold_back_cost_usd": reservation.hold_back_cost_usd,
        "required_id": reservation.required_id,
        "reservation_binding": {"request_sha256": reservation.request_sha256, "pricing_sha256": reservation.pricing_sha256,
                                "input_bound_provenance": reservation.input_bound_provenance},
    }
    value, failure, digest, usage = ledger.run(
        request.stage, attempt, provider=request.provider, model=request.model,
        input_sha256=request.input_sha256(), reserve_tokens=request.max_tokens, context_binding=context_binding,
        request_max_price=dict(request.max_price) if request.max_price is not None else None, **kwargs,
    )
    call_id = ledger.last_call_id()
    return TypedCall(failure is None, value, failure, call_id, digest, usage)


def unresolved_observation(call: TypedCall) -> Observation | None:
    """A failed provider call yields UNKNOWN with the failure as its reason; a good one yields None."""
    return None if call.ok else Observation(Outcome.UNKNOWN, f"provider_{call.failure}")
