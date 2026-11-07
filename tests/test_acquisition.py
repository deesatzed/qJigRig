import re
from decimal import Decimal

import pytest

from qjig.acquisition import Context, EvalResult, NeedSpec, RunState, run_round
from qjig.applicability import OPEN, Collection, Interval, MemberMetadata
from qjig.contracts import Request
from qjig.exact import FieldValue, NumericRule, PolicyRule, evaluate_dated_numeric
from qjig.indexing import index_entries, save_entries, current_entries
from qjig.logic import Outcome
from qjig.obligations import Obligation, ObligationLedger
from qjig.plans import parse_plan
from qjig.recovery import applicability_filter
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog

AS_OF = "2026-11-15"


def rev(text, source_id):
    return SourceRevision.create(source_id, "/x", decode_source(text.encode("utf-8"), encoding="utf-8"))


OLD = rev("# Refund limit\nRefunds are accepted within 30 days of purchase.\n", "policy/old.md")
NEW = rev("# Refund limit\nRefunds are accepted within 14 days of purchase.\n", "policy/new.md")
META = {
    OLD.revision_id: MemberMetadata(OLD.revision_id, "project", Interval("2026-01-01", "2026-10-31"), entity_keys=frozenset({"customer:42"}), observed_at="2026-01-01"),
    NEW.revision_id: MemberMetadata(NEW.revision_id, "project", Interval("2026-11-01", OPEN), entity_keys=frozenset({"customer:42"}), observed_at="2026-10-20"),
}
ENTITIES = frozenset({"customer:42"})


def exact_evaluator(fact):
    """Pull the threshold out of each retrieved span and apply the policy valid on AS_OF."""

    def evaluate(packet, recovery):
        rules, ids = [], []
        for item in packet.items:
            m = re.search(r"within (\d+) days", item.span.text)
            if m:
                rules.append(PolicyRule(META[item.span.revision_id], NumericRule(fact.field, "lte", Decimal(m.group(1)))))
                ids.append(item.entry_id)
        r = evaluate_dated_numeric(fact, rules, as_of=AS_OF, request_entities=ENTITIES, historical_as_known=False)
        return EvalResult(r.outcome, r.reason, tuple(ids))

    return evaluate


def build(tmp_path, fact=FieldValue("refund_days", 20)):
    cat = Catalog.open(tmp_path / "c.sqlite")
    for r in (OLD, NEW):
        cat.add_revision(r)
        save_entries(cat, index_entries(r))
    entries = [e for r in (OLD, NEW) for e in current_entries(cat, r.source_id, r.revision_id)]
    plan = parse_plan({"origin": "authored", "predicates": [{"id": "within_limit", "question": "Is the refund inside the limit?"}], "expression": {"ref": "within_limit"}})
    request = Request("req-1", "Can customer 42 get a refund after 20 days?", "reviewer", "1", "project")
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-within_limit", "predicate_evidence", "within_limit", "limit evidence", material=True))
    check = applicability_filter(Collection(tuple(META.values())), ENTITIES, AS_OF, historical_as_known=False)
    ctx = Context(cat, entries, check, {"within_limit": NeedSpec("refund days limit", want=2, max_bytes=4000, evaluate=exact_evaluator(fact))})
    return cat, RunState(request, plan, ledger), ctx


def test_one_round_trace(tmp_path):
    cat, state, ctx = build(tmp_path)
    with cat:
        rec = run_round(state, ctx)
    # the same 20-day fact passes the old 30-day rule but fails the policy in force on AS_OF
    assert rec.predicate_id == "within_limit" and rec.observation.outcome is Outcome.FALSE
    assert rec.request_id == "req-1" and rec.round_number == 1 and rec.sequence == 1
    # the trace binds the request, predicate, the exact source span used and the observation
    assert [e.revision_id for e in rec.evidence] == [NEW.revision_id]
    (ev,) = rec.evidence
    assert NEW.decoded.text[ev.start : ev.end] == ev.text and ev.text_sha256 == NEW.decoded.text_sha256
    assert ev.text == "# Refund limit\nRefunds are accepted within 14 days of purchase."
    assert state.observations["within_limit"].outcome is Outcome.FALSE
    assert state.attempts == {"within_limit": 1} and state.trace == [rec]
    # the old policy was retrieved but excluded as inapplicable on that date, and that is recorded
    assert [(x.reason) for x in rec.exclusions] == ["inapplicable"]
    # the evidence obligation is satisfied by that observation
    assert state.ledger.get("ob-within_limit").status == "satisfied"


def test_nothing_to_do_returns_none(tmp_path):
    cat, state, ctx = build(tmp_path)
    with cat:
        assert run_round(state, ctx) is not None
        assert run_round(state, ctx) is None  # resolved: no material need remains
        assert len(state.trace) == 1


from dataclasses import replace

from qjig.acquisition import Refusal


WAIVER = rev("# Waivers\nA manager may grant a waiver of the refund limit.\n", "policy/waiver.md")


def waiver_run(tmp_path, first_query, followup_query, can_find=True):
    cat = Catalog.open(tmp_path / "w.sqlite")
    cat.add_revision(WAIVER)
    save_entries(cat, index_entries(WAIVER))
    entries = current_entries(cat, WAIVER.source_id, WAIVER.revision_id)

    def evaluate(packet, recovery):
        hit = [i.entry_id for i in packet.items if "manager" in i.span.text]
        return EvalResult(Outcome.TRUE if hit else Outcome.UNKNOWN, "waiver_found" if hit else "no_waiver_text", tuple(hit))

    follow = NeedSpec(followup_query, 1, 3000, evaluate) if followup_query else None
    spec = NeedSpec(first_query, 1, 3000, evaluate, followup=follow)
    plan = parse_plan({"origin": "authored", "predicates": [{"id": "waiver", "question": "Is a waiver available?"}], "expression": {"ref": "waiver"}})
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-waiver", "exception", "waiver", "waiver evidence", material=True))
    state = RunState(Request("req-2", "q", "reviewer", "1", "project"), plan, ledger)
    return cat, state, Context(cat, entries, None, {"waiver": spec})


def test_bounded_followup(tmp_path):
    # first query finds nothing; one targeted followup is allowed and resolves it
    cat, state, ctx = waiver_run(tmp_path, "exception", "manager waiver")
    with cat:
        r1, r2 = run_round(state, ctx), run_round(state, ctx)
        assert (r1.round_number, r1.query, r1.observation.outcome, r1.observation.reason) == (1, "exception", Outcome.UNKNOWN, "no_retrieval_hit")
        assert (r2.round_number, r2.query, r2.observation.outcome) == (2, "manager waiver", Outcome.TRUE)
        assert run_round(state, ctx) is None and state.refusals == []

    # the followup also fails: a third round is refused and the predicate stays an explicit unknown
    cat, state, ctx = waiver_run(tmp_path, "exception", "carbon")
    with cat:
        assert run_round(state, ctx).round_number == 1
        assert run_round(state, ctx).round_number == 2
        assert run_round(state, ctx) is None
        assert run_round(state, ctx) is None
        assert [r.round_number for r in state.trace] == [1, 2]  # no third physical round
        assert state.observations["waiver"].outcome is Outcome.UNKNOWN
        assert state.refusals == [Refusal("waiver", "round_limit")]  # recorded once
        assert state.ledger.get("ob-waiver").status == "unresolved"


def test_no_followup_without_a_targeted_query(tmp_path):
    cat, state, ctx = waiver_run(tmp_path, "exception", None)
    with cat:
        assert run_round(state, ctx).round_number == 1
        assert run_round(state, ctx) is None  # repeating the same query would find the same thing
        assert state.refusals == [Refusal("waiver", "no_targeted_followup")]
        assert state.observations["waiver"].outcome is Outcome.UNKNOWN


def test_max_rounds_is_configurable_but_never_above_two(tmp_path):
    import pytest as _pytest

    cat, state, ctx = waiver_run(tmp_path, "exception", "carbon")
    with cat:
        with _pytest.raises(ValueError):
            replace(ctx, max_rounds=3)
        one = replace(ctx, max_rounds=1)
        assert run_round(state, one).round_number == 1
        assert run_round(state, one) is None and state.refusals == [Refusal("waiver", "round_limit")]


from qjig.acquisition import Skip, run_until_done


BLOCK = rev("# Eligibility\nThe order is outside the refund window and ineligible.\n", "policy/elig.md")


def multi_run(tmp_path, expression, ids=("a", "b", "c"), a_outcome=Outcome.FALSE):
    cat = Catalog.open(tmp_path / "m.sqlite")
    cat.add_revision(BLOCK)
    save_entries(cat, index_entries(BLOCK))
    entries = current_entries(cat, BLOCK.source_id, BLOCK.revision_id)
    called = []

    def make(pid, outcome):
        def evaluate(packet, recovery):
            called.append(pid)
            return EvalResult(outcome, f"{pid}_reason", tuple(i.entry_id for i in packet.items))
        return evaluate

    specs = {pid: NeedSpec("refund window ineligible", 1, 3000, make(pid, a_outcome if pid == "a" else Outcome.TRUE)) for pid in ids}
    plan = parse_plan({"origin": "authored", "predicates": [{"id": i, "question": f"is {i}?"} for i in ids], "expression": expression})
    ledger = ObligationLedger()
    for i in ids:
        ledger.open(Obligation(f"ob-{i}", "predicate_evidence", i, f"{i} evidence", material=True))
    return cat, RunState(Request("req-3", "q", "reviewer", "1", "project"), plan, ledger), Context(cat, entries, None, specs), called


def test_stop_after_blocker(tmp_path):
    expr = {"op": "and", "args": [{"ref": "a"}, {"ref": "b"}, {"ref": "c"}]}
    cat, state, ctx, called = multi_run(tmp_path, expr)
    with cat:
        summary = run_until_done(state, ctx)
    assert called == ["a"]  # b and c were never worked on
    assert summary.stop.stop is True and summary.stop.outcome is False
    # the skips carry the stopping witness and the preserved reason of the blocking fact
    assert summary.skipped == (
        Skip("b", "witnessed", ("a",), "a=false (a_reason)"),
        Skip("c", "witnessed", ("a",), "a=false (a_reason)"),
    )
    assert state.skipped == list(summary.skipped)
    # skipped predicates have no observation and no attempts: they are not silently "false"
    assert "b" not in state.observations and state.attempts == {"a": 1}


def test_or_blocker_and_nothing_skipped_when_all_needed(tmp_path):
    cat, state, ctx, called = multi_run(tmp_path, {"op": "or", "args": [{"ref": "a"}, {"ref": "b"}]}, ids=("a", "b"), a_outcome=Outcome.TRUE)
    with cat:
        s = run_until_done(state, ctx)
    assert called == ["a"] and s.stop.outcome is True and [x.predicate_id for x in s.skipped] == ["b"]
    cat, state, ctx, called = multi_run(tmp_path, {"op": "and", "args": [{"ref": "a"}, {"ref": "b"}]}, ids=("a", "b"), a_outcome=Outcome.TRUE)
    with cat:
        s = run_until_done(state, ctx)
    assert called == ["a", "b"] and s.skipped == () and s.stop.outcome is True


def test_unreferenced_predicate_is_unwitnessed_not_claimed_as_skipped_by_blocker(tmp_path):
    # a predicate outside the expression is immaterial but no known value fixed the result because of it
    expr = {"ref": "a"}
    cat, state, ctx, called = multi_run(tmp_path, expr)
    with cat:
        s = run_until_done(state, ctx)
    assert called == ["a"]
    assert {x.predicate_id: x.kind for x in s.skipped} == {"b": "unreferenced", "c": "unreferenced"}


def conflict_run(tmp_path, tag, boosted):
    """Two policy sources that are both applicable on AS_OF but disagree (30 vs 14 days)."""
    a = rev("# Refund limit\nRefunds are accepted within 30 days of purchase.\n" + ("refund days limit " if boosted == "a" else ""), f"policy/{tag}-a.md")
    b = rev("# Refund limit\nRefunds are accepted within 14 days of purchase.\n" + ("refund days limit " if boosted == "b" else ""), f"policy/{tag}-b.md")
    meta = {
        a.revision_id: MemberMetadata(a.revision_id, "project", Interval("2026-01-01", OPEN), entity_keys=ENTITIES, observed_at="2026-01-01" if boosted == "b" else "2026-10-30"),
        b.revision_id: MemberMetadata(b.revision_id, "project", Interval("2026-01-01", OPEN), entity_keys=ENTITIES, observed_at="2026-10-30" if boosted == "b" else "2026-01-01"),
    }
    cat = Catalog.open(tmp_path / f"{tag}.sqlite")
    for r in (a, b):
        cat.add_revision(r)
        save_entries(cat, index_entries(r))
    entries = [e for r in (a, b) for e in current_entries(cat, r.source_id, r.revision_id)]

    def evaluate(packet, recovery):
        rules, ids = [], []
        for item in packet.items:
            m = re.search(r"within (\d+) days", item.span.text)
            rules.append(PolicyRule(meta[item.span.revision_id], NumericRule("refund_days", "lte", Decimal(m.group(1)))))
            ids.append(item.entry_id)
        r = evaluate_dated_numeric(FieldValue("refund_days", 20), rules, as_of=AS_OF, request_entities=ENTITIES, historical_as_known=False)
        return EvalResult(r.outcome, r.reason, tuple(ids))

    plan = parse_plan({"origin": "authored", "predicates": [{"id": "within_limit", "question": "inside the limit?"}], "expression": {"ref": "within_limit"}})
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-within_limit", "predicate_evidence", "within_limit", "limit evidence", material=True))
    check = applicability_filter(Collection(tuple(meta.values())), ENTITIES, AS_OF, historical_as_known=False)
    ctx = Context(cat, entries, check, {"within_limit": NeedSpec("refund days limit", 2, 4000, evaluate)})
    return cat, RunState(Request("req-4", "q", "reviewer", "1", "project"), plan, ledger), ctx, (a, b)


import pytest as _pytest


@_pytest.mark.parametrize("boosted", ["a", "b"])
def test_material_conflict_defers(tmp_path, boosted):
    cat, state, ctx, (a, b) = conflict_run(tmp_path, f"c{boosted}", boosted)
    with cat:
        summary = run_until_done(state, ctx)
    # whichever source ranks higher or was recorded later, the contradiction is kept, not resolved
    obs = state.observations["within_limit"]
    assert obs.outcome is Outcome.CONFLICT and obs.reason == "multiple_applicable_policies"
    assert summary.stop.stop is False and summary.stop.outcome is None
    assert summary.conflicts == ("within_limit",)
    # both applicable sources are retained as evidence in the trace
    assert {e.revision_id for e in state.trace[0].evidence} == {a.revision_id, b.revision_id}
    assert state.ledger.get("ob-within_limit").status != "satisfied"
    assert state.ledger.blocking() == ["ob-within_limit"]
