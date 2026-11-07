"""STAND-IN transport only (D018): authored planner and judge answers drive the pipeline mechanics.
Nothing here shows how a real model plans or judges; see reports/t046-smoke-receipts*.json for live paths."""
import json

from qjig.acquisition import run_fresh
from qjig.applicability import Applicability
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import current_entries, index_entries, save_entries
from qjig.journal import Journal
from qjig.logic import Outcome
from qjig.providers import RawResponse, StandInTransport
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog

U = {"prompt_tokens": 20, "completion_tokens": 9, "cost_usd": 0.0}
TEXT = "# Refunds\nRefunds are accepted within 14 days of purchase.\n\n# Exceptions\nDefective items may be refunded within 30 days.\n"
REV = SourceRevision.create("sample/refunds.md", "synthetic", decode_source(TEXT.encode(), encoding="utf-8"))
REQUEST = Request("req-f", "Can customer 42 get a refund 20 days after purchase?", "reviewer", "1", "project")
QUOTE = "Refunds are accepted within 14 days of purchase."
PLAN = {"predicates": [{"id": "p1", "question": "Is the purchase inside the 14 day refund window?"}], "expression": {"ref": "p1"}}


def raw(obj):
    return RawResponse(200, json.dumps(obj), U)


def side(supported, quote=""):
    return raw({"supported": supported, "quote": quote, "reason": "r"})


def build(tmp_path, responses, calls=6):
    cat = Catalog.open(tmp_path / "c.sqlite")
    cat.add_revision(REV)
    save_entries(cat, index_entries(REV))
    entries = current_entries(cat, REV.source_id, REV.revision_id)
    j = Journal.open(tmp_path / "j.sqlite")
    return cat, entries, j, BudgetLedger(Budget(calls, 50000, 1.0), j, "req-f"), StandInTransport(responses)


def go(tmp_path, responses, **kw):
    cat, entries, j, ledger, t = build(tmp_path, responses)
    with cat, j:
        run = run_fresh(
            request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=t,
            planner=("stand-in", "stand-in-planner"), judge=("stand-in", "stand-in-judge"),
            revision_applicability=lambda rid: Applicability.MATCH, **kw,
        )
        return run, ledger.used_calls(), t


def test_fresh_pipeline(tmp_path):
    run, used, t = go(tmp_path, [raw(PLAN), side(False), side(True, QUOTE)])
    assert run.plan_failure is None and run.binding.model == "stand-in-planner"
    assert run.state.observations["p1"].outcome is Outcome.FALSE
    # the decisive evidence keeps its exact binding: entry, revision and absolute offsets that re-slice to the quote
    (ref,) = run.quote_refs["p1"]
    assert REV.decoded.text[ref.start:ref.end] == QUOTE and ref.revision_id == REV.revision_id
    (rec,) = run.state.trace
    assert rec.predicate_id == "p1" and ref.entry_id in [e.entry_id for e in rec.evidence]
    assert run.state.ledger.get("ob-p1").status == "satisfied"
    # a fresh plan is never known complete: the coverage gap blocks a decision, and says what exception text exists
    assert run.status == "deferred" and "plan_coverage_unestablished" in run.reasons
    assert "ob-plan-coverage" in run.summary.stop.blocking_obligations
    assert run.coverage_candidates  # exception-channel passages offered to a reviewer, not treated as resolved
    assert run.state.ledger.absence_established("ob-plan-coverage") is False
    assert used == 3 and t.calls_made == 3  # one planner call and two judge calls


def test_planner_failure_leaves_no_plan_and_makes_no_judge_call(tmp_path):
    run, _, t = go(tmp_path, [RawResponse(200, "Sure thing!", U)])
    assert run.state is None and run.plan_failure == "malformed_output"
    assert run.status == "deferred" and run.reasons == ("plan_unavailable:malformed_output",)
    assert t.calls_made == 1


def test_unresolved_predicate_stays_a_visible_gap(tmp_path):
    run, _, _ = go(tmp_path, [raw(PLAN), side(False), side(False)])
    assert run.state.observations["p1"].outcome is Outcome.UNKNOWN
    assert run.state.ledger.get("ob-p1").status != "satisfied"
    assert "p1" in run.summary.stop.unresolved_ids and run.status == "deferred"
    assert run.quote_refs["p1"] == ()


def test_operational_failures_return_partial_deferral(tmp_path):
    from qjig.providers import ProviderUnavailable

    scenarios = [
        ("budget", [], 0, "budget_exceeded", 0, False),
        ("unavailable", [ProviderUnavailable("offline")], 6, "provider_unavailable", 1, False),
        ("timeout", [TimeoutError("timeout")], 6, "uncertain_outcome", 1, True),
        ("judge_timeout", [raw(PLAN), TimeoutError("timeout")], 6, None, 2, True),
    ]
    for name, responses, cap, failure, calls, pending in scenarios:
        directory = tmp_path / name
        directory.mkdir()
        cat, entries, journal, ledger, transport = build(directory, responses, calls=cap)
        with cat, journal:
            run = run_fresh(request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                            planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                            revision_applicability=lambda rid: Applicability.MATCH)
            assert run.status == "deferred"
            assert run.plan_failure == failure
            assert ledger.used_calls() == calls
            assert bool(journal.pending("req-f")) is pending
            if name == "judge_timeout":
                assert run.state is not None
                assert run.state.observations["p1"].outcome is Outcome.UNKNOWN
                assert run.judgments["p1"].positive.failure == "uncertain_outcome"
                assert transport.calls_made == 2


def test_judge_timeout_preserves_first_side_and_stops_later_predicates(tmp_path):
    plan = {"predicates": [{"id": "p1", "question": "Refund purchase window?"},
                           {"id": "p2", "question": "Refund purchase limit?"}],
            "expression": {"op": "and", "args": [{"ref": "p1"}, {"ref": "p2"}]}}
    cat, entries, journal, ledger, transport = build(tmp_path, [raw(plan), side(True, QUOTE), TimeoutError("uncertain")])
    with cat, journal:
        run = run_fresh(request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                        planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                        revision_applicability=lambda rid: Applicability.MATCH)
        assert run.status == "deferred"
        assert run.judgments["p1"].positive.quote_ref is not None
        assert run.judgments["p1"].negative.failure == "uncertain_outcome"
        assert run.state.observations["p2"].reason == "reconciliation_required"
        assert transport.calls_made == 3
        assert len(journal.pending("req-f")) == 1


def test_fresh_pipeline_uses_per_call_goal_reservations(tmp_path):
    """Synthetic bound and stand-in responses: accounting integration, not model quality."""
    from qjig.goal_budget import GoalBudget
    from qjig.providers import make_call_reservation

    cat, entries, journal, _, transport = build(tmp_path, [raw(PLAN), side(False), side(True, QUOTE)])
    limit = Budget(6, 50000, 1)
    seen = []
    def reserve(request):
        seen.append(request)
        model = {"id": request.model, "context_length": 10000,
                 "top_provider": {"max_completion_tokens": 6000},
                 "pricing": {"prompt": "0.0000001", "completion": "0.0000001"}}
        return make_call_reservation(request, model, input_tokens=1000, input_bound_provenance="synthetic fixture")
    with cat, journal, GoalBudget.open(tmp_path / "goal.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal:
        ledger = BudgetLedger(limit, journal, REQUEST.request_id, goal_budget=goal, partition="smoke")
        run = run_fresh(request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                        planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                        revision_applicability=lambda rid: Applicability.MATCH, reservation_factory=reserve)
        assert run.status == "deferred" and run.state.observations["p1"].outcome is Outcome.FALSE
        assert len(seen) == 3 and goal.totals().max_calls == 3 and goal.actual_usage()["unknown_calls"] == 0
        intents = [event for event in journal.events(REQUEST.request_id) if event.kind == "intent"]
        assert [event.payload["reservation_binding"]["request_sha256"] for event in intents] == [r.input_sha256() for r in seen]
        assert len({event.payload["goal_attempt_id"] for event in intents}) == 3


def test_reservation_refusal_defers_without_extra_provider_call(tmp_path):
    from qjig.budgets import BudgetExceeded
    from qjig.goal_budget import GoalBudget
    from qjig.providers import make_call_reservation

    cat, entries, journal, _, transport = build(tmp_path, [raw(PLAN)])
    limit = Budget(6, 50000, 1)
    def reserve(request):
        if request.stage != "planner":
            raise BudgetExceeded("tokens", "synthetic mandatory reserve")
        model = {"id": request.model, "context_length": 10000,
                 "top_provider": {"max_completion_tokens": 6000},
                 "pricing": {"prompt": "0.0000001", "completion": "0.0000001"}}
        return make_call_reservation(request, model, input_tokens=1000, input_bound_provenance="synthetic fixture")
    with cat, journal, GoalBudget.open(tmp_path / "goal.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal:
        ledger = BudgetLedger(limit, journal, REQUEST.request_id, goal_budget=goal, partition="smoke")
        run = run_fresh(request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                        planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                        revision_applicability=lambda rid: Applicability.MATCH, reservation_factory=reserve)
        assert run.status == "deferred" and run.state.observations["p1"].outcome is Outcome.UNKNOWN
        assert transport.calls_made == 1 and goal.totals().max_calls == 1
        assert run.judgments["p1"].positive.failure == "budget_exceeded"


def test_fresh_pipeline_archives_each_model_attempt(tmp_path):
    from qjig.run_archive import RunArchive

    cat, entries, journal, ledger, transport = build(tmp_path, [raw(PLAN), side(False), side(True, QUOTE)])
    with cat, journal, RunArchive.open(tmp_path / "archive") as archive:
        archive.add_source(REV.source_id, TEXT.encode())
        original_send = transport.send
        def inspect_before_send(request):
            assert archive.revision(REV.revision_id) == REV
            return original_send(request)
        transport.send = inspect_before_send
        result = run_fresh(request=REQUEST, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                           planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                           revision_applicability=lambda rid: Applicability.MATCH, archive=archive)
        assert result.status == "deferred"
        assert [event["kind"] for event in archive.events()] == ["request", "response", "validation"] * 3
        assert archive.source(REV.source_id) == TEXT.encode()
        assert archive.revision(REV.revision_id) == REV
