"""STAND-IN transport only (D018): authored planner responses. No real model is involved."""
import json

import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.journal import Journal
from qjig.planner import corpus_manifest_sha256, request_fresh_plan
from qjig.providers import RawResponse, StandInTransport

REQUEST = Request("req-1", "Can customer 42 get a refund after 20 days?", "reviewer", "1", "project")
PLAN_JSON = {
    "predicates": [
        {"id": "within_limit", "question": "Is the refund inside the limit?"},
        {"id": "exception", "question": "Does a waiver apply?"},
    ],
    "expression": {"op": "or", "args": [{"ref": "within_limit"}, {"ref": "exception"}]},
}
USAGE = {"prompt_tokens": 30, "completion_tokens": 40, "cost_usd": 0.0}


def setup(tmp_path, bodies, calls=5):
    j = Journal.open(tmp_path / "j.sqlite")
    return j, BudgetLedger(Budget(calls, 5000, 1.0), j, "req-1"), StandInTransport([RawResponse(200, b, USAGE) for b in bodies])


def test_fresh_plan_binding(tmp_path):
    corpus = ["rev1:aaa", "rev1:bbb"]
    j, ledger, t = setup(tmp_path, [json.dumps(PLAN_JSON)])
    with j:
        out = request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=corpus, provider="stand-in", model="stand-in-model")
        assert out.ok and out.failure is None
        # the plan's origin is the model path, never "authored", and the caveats travel with it
        assert out.plan.origin == "fresh"
        assert {"completeness_not_established", "model_generated_untrusted"} <= set(out.caveats)
        b = out.binding
        assert b.request_id == "req-1" and b.model == "stand-in-model" and b.provider == "stand-in"
        assert b.corpus_manifest_sha256 == corpus_manifest_sha256(corpus) == corpus_manifest_sha256(reversed(corpus))
        assert len(b.prompt_sha256) == 64 and b.call_id == "req-1#1" and len(b.raw_sha256) == 64
        assert [p.id for p in out.plan.predicates] == ["within_limit", "exception"]
        # the exact journal intent carries the same input identity as the binding
        assert j.events("req-1")[0].input_sha256 == b.prompt_sha256


def test_binding_changes_with_corpus_and_model(tmp_path):
    j, ledger, t = setup(tmp_path, [json.dumps(PLAN_JSON)] * 3)
    with j:
        a = request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r1"], provider="stand-in", model="m1")
        b = request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r1", "r2"], provider="stand-in", model="m1")
        c = request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r1"], provider="stand-in", model="m2")
        hashes = {x.binding.prompt_sha256 for x in (a, b, c)}
        assert len(hashes) == 3
        assert a.binding.corpus_manifest_sha256 != b.binding.corpus_manifest_sha256
        assert a.binding.corpus_manifest_sha256 == c.binding.corpus_manifest_sha256 and a.binding.model != c.binding.model


@pytest.mark.parametrize(
    "body,failure",
    [
        ("here is a plan: or(a,b)", "malformed_output"),
        (json.dumps({**PLAN_JSON, "expression": {"op": "or", "args": [{"ref": "within_limit"}, {"ref": "ghost"}]}}), "plan_invalid:dangling_ref"),
        (json.dumps({**PLAN_JSON, "origin": "authored"}), "plan_invalid:model_supplied_origin"),
        (json.dumps({**PLAN_JSON, "code": "import os"}), "plan_invalid:executable_code_field"),
        (json.dumps({"predicates": [{"id": f"p{i}", "question": "q"} for i in range(7)], "expression": {"ref": "p0"}}), "plan_invalid:too_many_predicates"),
        (json.dumps([1, 2]), "malformed_output"),
    ],
)
def test_bad_planner_output_gives_no_plan_but_keeps_the_receipt(tmp_path, body, failure):
    j, ledger, t = setup(tmp_path, [body])
    with j:
        out = request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r1"], provider="stand-in", model="stand-in-model")
        assert out.ok is False and out.plan is None and out.failure == failure
        (receipt,) = [e for e in j.events("req-1") if e.kind == "receipt"]
        assert receipt.payload["raw_response"] == body  # nothing is silently repaired or replaced
        assert ledger.used_calls() == 1


def test_max_tokens_override_reaches_the_request_and_default_is_unchanged(tmp_path):
    seen = []

    class Spy(StandInTransport):
        def send(self, request):
            seen.append(request.max_tokens)
            return super().send(request)

    j = Journal.open(tmp_path / "j.sqlite")
    ledger = BudgetLedger(Budget(5, 20000, 1.0), j, "req-1")
    t = Spy([RawResponse(200, json.dumps(PLAN_JSON), USAGE)] * 2)
    with j:
        request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r"], provider="stand-in", model="m")
        request_fresh_plan(ledger, t, REQUEST, corpus_revision_ids=["r"], provider="stand-in", model="m", max_tokens=6000)
    assert seen == [1500, 6000]


def test_prompt_asks_for_an_exception_predicate(tmp_path):
    seen = []

    class Spy(StandInTransport):
        def send(self, request):
            seen.append(request.prompt)
            return super().send(request)

    j = Journal.open(tmp_path / "j.sqlite")
    ledger = BudgetLedger(Budget(2, 20000, 1.0), j, "req-1")
    with j:
        request_fresh_plan(ledger, Spy([RawResponse(200, json.dumps(PLAN_JSON), USAGE)]), REQUEST, corpus_revision_ids=["r"], provider="s", model="m")
    # the prompt tells the model to cover exceptions, and to never rely on that for completeness
    assert "exception" in seen[0].lower() and "waiver" in seen[0].lower()
