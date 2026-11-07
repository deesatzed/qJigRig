"""All transports here are STAND-INS with authored responses. They prove validation, journaling and
accounting mechanics only; they say nothing about any real model's behavior."""
import json

import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget
from qjig.journal import Journal, UncertainOutcome
from qjig.logic import Outcome
from qjig.providers import (
    FieldSpec, ProviderRequest, ProviderUnavailable, RawResponse, StandInTransport, call_typed, unresolved_observation,
)

SCHEMA = {"outcome": FieldSpec(str, enum=("true", "false", "unknown", "conflict")), "reason": FieldSpec(str)}
REQ = ProviderRequest(stage="judge", provider="stand-in", model="stand-in-model", prompt="Is it?", max_tokens=50)
GOOD = json.dumps({"outcome": "true", "reason": "quoted"})
USAGE = {"prompt_tokens": 5, "completion_tokens": 2, "cost_usd": None}


def setup(tmp_path, responses, calls=5):
    j = Journal.open(tmp_path / "j.sqlite")
    return j, BudgetLedger(Budget(calls, 1000, 1.0), j, "req-1"), StandInTransport(responses)


def test_malformed_is_unknown(tmp_path):
    j, ledger, t = setup(tmp_path, [RawResponse(200, "Sure! The answer is yes.", USAGE)])
    with j:
        r = call_typed(ledger, t, REQ, SCHEMA)
        # HTTP success with unusable output is a failure, never a value
        assert r.ok is False and r.value is None and r.failure == "malformed_output"
        obs = unresolved_observation(r)
        assert obs.outcome is Outcome.UNKNOWN and obs.reason == "provider_malformed_output"
        # a receipt is retained, with the raw output and its hash, and the call still counts
        (receipt,) = [e for e in j.events("req-1") if e.kind == "receipt"]
        assert receipt.payload["raw_response"] == "Sure! The answer is yes."
        assert receipt.payload["validation"] == "malformed_output" and receipt.payload["http_status"] == 200
        assert len(receipt.payload["raw_sha256"]) == 64 and receipt.payload["usage"] == USAGE
        assert ledger.used_calls() == 1 and r.call_id == receipt.call_id
        assert t.label.startswith("STAND_IN") and t.calls_made == 1


def test_other_invalid_outputs_and_the_valid_path(tmp_path):
    cases = [
        (RawResponse(200, json.dumps({"outcome": "maybe", "reason": "x"}), USAGE), "schema_violation"),
        (RawResponse(200, json.dumps({"outcome": "true"}), USAGE), "schema_violation"),  # missing field
        (RawResponse(200, json.dumps({"outcome": "true", "reason": "x", "extra": 1}), USAGE), "schema_violation"),
        (RawResponse(200, json.dumps(["not", "an", "object"]), USAGE), "schema_violation"),
        (RawResponse(500, "upstream error", None), "http_error"),
        (RawResponse(429, "", None), "http_error"),
    ]
    j, ledger, t = setup(tmp_path, [c[0] for c in cases] + [RawResponse(200, GOOD, USAGE)], calls=10)
    with j:
        for _, expected in cases:
            r = call_typed(ledger, t, REQ, SCHEMA)
            assert (r.ok, r.failure) == (False, expected)
            assert unresolved_observation(r).reason == f"provider_{expected}"
        good = call_typed(ledger, t, REQ, SCHEMA)
        assert good.ok and good.value == {"outcome": "true", "reason": "quoted"} and good.failure is None
        assert unresolved_observation(good) is None
        assert ledger.used_calls() == 7  # every attempt, failed or not


def test_timeout_is_uncertain_and_refusal_to_connect_is_a_definite_failure(tmp_path):
    j, ledger, t = setup(tmp_path, [TimeoutError("read timed out"), ProviderUnavailable("connection refused")])
    with j:
        with pytest.raises(UncertainOutcome):
            call_typed(ledger, t, REQ, SCHEMA)
        assert [e.kind for e in j.events("req-1")] == ["intent", "uncertain"]
        other = ProviderRequest("judge", "stand-in", "stand-in-model", "different prompt", 50)
        with pytest.raises(ProviderUnavailable):
            call_typed(ledger, t, other, SCHEMA)
        assert [e.kind for e in j.events("req-1")][-2:] == ["intent", "failure"]
        assert ledger.used_calls() == 2


def test_exhausted_stand_in_and_unbudgeted_calls_never_reach_the_transport(tmp_path):
    j, ledger, t = setup(tmp_path, [], calls=1)
    with j:
        with pytest.raises(AssertionError):
            call_typed(ledger, t, REQ, SCHEMA)  # stand-in has no authored response left
    j2 = Journal.open(tmp_path / "k.sqlite")
    with j2:
        from qjig.budgets import BudgetExceeded

        t2 = StandInTransport([RawResponse(200, GOOD, USAGE)])
        with pytest.raises(BudgetExceeded):
            call_typed(BudgetLedger(None, j2, "req-2"), t2, REQ, SCHEMA)
        assert t2.calls_made == 0 and j2.events("req-2") == []


# --- T046: the real adapter. The HTTP layer below is a labeled FAKE used only to test request shaping, parsing and
# labeling offline; the actual network path is exercised by scripts/smoke_t046.py, which is opt-in and live. ---
from qjig.providers import OpenRouterTransport, load_env_value  # noqa: E402

LIVE_BODY = json.dumps({
    "choices": [{"message": {"content": GOOD}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "cost": 0.0002},
})


def _env(tmp_path, text="OPENROUTER_API_KEY=sk-test-SECRET\nBASE_URL=https://example.invalid/api/v1\n"):
    p = tmp_path / ".env"
    p.write_text(text)
    return p


def test_real_adapter_smoke_contract(tmp_path):
    seen = {}

    def fake_post(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=json.loads(payload), timeout=timeout)
        return 200, LIVE_BODY

    t = OpenRouterTransport(_env(tmp_path), post=fake_post)
    # successful path: labeled live, content extracted, usage reported with its source fields
    assert t.label == "LIVE: openrouter, real model call"
    raw = t.send(ProviderRequest("judge", "openrouter", "vendor/model-x", "Is it?", 50))
    assert raw.http_status == 200 and raw.body == GOOD
    assert raw.usage == {"prompt_tokens": 11, "completion_tokens": 7, "cost_usd": 0.0002}
    assert seen["url"] == "https://example.invalid/api/v1/chat/completions"
    assert seen["payload"]["model"] == "vendor/model-x" and seen["payload"]["max_tokens"] == 50
    assert seen["payload"]["messages"] == [{"role": "user", "content": "Is it?"}]
    assert seen["headers"]["Authorization"] == "Bearer sk-test-SECRET"
    assert "SECRET" not in repr(t)

    # cost not reported -> unknown, never zero
    t2 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (200, json.dumps({"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})))
    assert t2.send(REQ).usage["cost_usd"] is None
    # non-2xx is returned as a failure response, with no usage invented
    t3 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (429, "rate limited"))
    r = t3.send(REQ)
    assert (r.http_status, r.body, r.usage) == (429, "rate limited", None)
    # a 200 whose envelope has no choices is kept as raw text so the typed layer records the failure
    # a 200 with no message content (e.g. a reasoning model that spent its whole token cap) is an empty body
    # with the observed cause recorded, so the typed layer fails it as malformed rather than mislabeling it
    empty = json.dumps({"choices": [{"finish_reason": "length", "message": {"content": None}}], "usage": {"prompt_tokens": 3, "completion_tokens": 50}})
    r4 = OpenRouterTransport(_env(tmp_path), post=lambda *a: (200, empty)).send(REQ)
    assert r4.body == "" and r4.note == "no_message_content; finish_reason=length" and r4.usage["completion_tokens"] == 50

    # unavailable path: no key means the request never leaves; the HTTP layer is not touched
    called = []
    t5 = OpenRouterTransport(_env(tmp_path, "BASE_URL=x\n"), post=lambda *a: called.append(1))
    with pytest.raises(ProviderUnavailable, match="OPENROUTER_API_KEY"):
        t5.send(REQ)
    assert called == []
    with pytest.raises(ProviderUnavailable):
        OpenRouterTransport(tmp_path / "missing.env", post=lambda *a: called.append(1)).send(REQ)
    # connection refused happens before anything is sent
    def refuse(*a):
        raise ConnectionRefusedError("no route")
    with pytest.raises(ProviderUnavailable):
        OpenRouterTransport(_env(tmp_path), post=refuse).send(REQ)
    # a timeout after sending is outcome-unknown and is left for the journal to treat as uncertain
    def slow(*a):
        raise TimeoutError("read timed out")
    with pytest.raises(TimeoutError):
        OpenRouterTransport(_env(tmp_path), post=slow).send(REQ)
    assert load_env_value(_env(tmp_path), "BASE_URL") == "https://example.invalid/api/v1"
    assert load_env_value(_env(tmp_path), "NOPE") is None
