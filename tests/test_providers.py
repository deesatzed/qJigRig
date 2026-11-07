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
