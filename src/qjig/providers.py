"""Provider boundary: typed validation of responses, every attempt journaled and budgeted.

HTTP success with unusable output is a failure that keeps a receipt (raw text and hash), not a value.
"""
from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .budgets import BudgetExceeded, BudgetLedger
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
    note: str | None = None  # transport-observed cause, e.g. finish_reason


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
        payload = json.dumps({
            "model": request.model, "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }, ensure_ascii=False)
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
        if not 200 <= status < 300:
            return RawResponse(status, body, None)
        try:
            data = json.loads(body)
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError
        except (ValueError, KeyError, IndexError, TypeError):
            note = self._no_content_note(body)
            return RawResponse(status, "", self._usage(body), note)
        return RawResponse(status, content, self._usage(body))

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


def call_typed(ledger: BudgetLedger, transport: Transport, request: ProviderRequest, schema: "dict[str, FieldSpec] | Validator") -> TypedCall:
    """One budgeted, journaled provider attempt returning a validated value or an explicit failure."""
    if isinstance(transport, OpenRouterTransport):
        raise BudgetExceeded("preflight_unavailable", "hosted calls require complete input, cost and goal-wide reservations")

    def attempt():
        try:
            raw = transport.send(request)
        except TimeoutError as exc:  # sent, outcome unknown
            raise UncertainOutcome(f"timeout: {exc}") from exc
        digest = hashlib.sha256(raw.body.encode("utf-8")).hexdigest()
        if not 200 <= raw.http_status < 300:
            value, failure = None, "http_error"
        else:
            value, failure = schema(raw.body) if callable(schema) else _validate(raw.body, schema)
        extra = {"http_status": raw.http_status, "raw_sha256": digest, "transport": transport.label}
        if raw.note:
            extra["note"] = raw.note
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
