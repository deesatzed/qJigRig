import re
from decimal import Decimal

import pytest

from qjig.acquisition import Context, EvalResult, NeedSpec, RunState, RunSummary, run_until_done
from qjig.applicability import OPEN, Collection, Interval, MemberMetadata
from qjig.contracts import ContractError, Request
from qjig.exact import FieldValue, NumericRule, PolicyRule, evaluate_dated_numeric
from qjig.finalize import finalize
from qjig.indexing import current_entries, index_entries, invalidate_superseded, save_entries
from qjig.logic import Outcome
from qjig.obligations import Obligation, ObligationLedger
from qjig.plans import parse_plan
from qjig.recovery import applicability_filter
from qjig.sources import SourceRevision, decode_source
from qjig.stopping import check_stop
from qjig.store import Catalog
from qjig.logic import Observation

AS_OF, ENTITIES = "2026-11-15", frozenset({"customer:42"})


def rev(days):
    text = f"# Refund limit\nRefunds are accepted within {days} days of purchase.\n"
    return SourceRevision.create("policy/current.md", "/origin/policy.md", decode_source(text.encode(), encoding="utf-8"))


def make_run(cat, revision):
    """Acquire evidence for 'refund_days = 20' against one policy revision of policy/current.md."""
    cat.add_revision(revision)
    save_entries(cat, index_entries(revision))
    invalidate_superseded(cat, revision.source_id, current_revision_id=revision.revision_id)
    meta = {revision.revision_id: MemberMetadata(revision.revision_id, "project", Interval("2026-01-01", OPEN), entity_keys=ENTITIES, observed_at="2026-01-01")}

    def evaluate(packet, recovery):
        rules = [
            PolicyRule(meta[i.span.revision_id], NumericRule("refund_days", "lte", Decimal(re.search(r"within (\d+)", i.span.text).group(1))))
            for i in packet.items
        ]
        r = evaluate_dated_numeric(FieldValue("refund_days", 20), rules, as_of=AS_OF, request_entities=ENTITIES, historical_as_known=False)
        return EvalResult(r.outcome, r.reason, tuple(i.entry_id for i in packet.items))

    plan = parse_plan({"origin": "authored", "predicates": [{"id": "ok", "question": "inside limit?"}], "expression": {"ref": "ok"}})
    ledger = ObligationLedger()
    ledger.open(Obligation("ob-ok", "predicate_evidence", "ok", "limit", material=True))
    ctx = Context(
        cat, current_entries(cat, revision.source_id, revision.revision_id),
        applicability_filter(Collection(tuple(meta.values())), ENTITIES, AS_OF, historical_as_known=False),
        {"ok": NeedSpec("refund days limit", 1, 4000, evaluate)},
    )
    state = RunState(Request("req-5", "q", "reviewer", "1", "project"), plan, ledger)
    return state, ctx, run_until_done(state, ctx)


def test_source_change_policy(tmp_path):
    v1, v2, v3 = rev(14), rev(21), rev(28)
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        state, ctx, summary = make_run(cat, v1)
        assert state.observations["ok"].outcome is Outcome.FALSE  # 20 days > 14
        cat.add_revision(v2)  # the origin is updated after retrieval

        # snapshot mode: stay bound to v1, report the update separately, never touch v2
        snap = finalize(state, ctx, summary, mode="snapshot", lookup=lambda sid: v2.revision_id)
        assert snap.status == "decided" and snap.outcome is False and snap.restarts == 0
        assert [(u.source_id, u.used_revision_id, u.current_revision_id) for u in snap.origin_updates] == [("policy/current.md", v1.revision_id, v2.revision_id)]
        assert {e.revision_id for r in snap.state.trace for e in r.evidence} == {v1.revision_id}

        # current-required: restart once under the new snapshot; the new run uses only v2
        def rerun():
            return make_run(cat, v2)

        cur = finalize(state, ctx, summary, mode="current_required", lookup=lambda sid: v2.revision_id, rerun=rerun)
        assert cur.status == "decided" and cur.outcome is True and cur.restarts == 1  # 20 <= 21
        assert {e.revision_id for r in cur.state.trace for e in r.evidence} == {v2.revision_id}  # no mixing
        assert cur.superseded_runs == 1  # the first run is retained as superseded, not erased

    # the origin changes AGAIN during the restart: defer, no outcome, one restart only
    v4 = rev(35)
    with Catalog.open(tmp_path / "d.sqlite") as cat:
        state, ctx, summary = make_run(cat, v1)
        cat.add_revision(v4)
        answers = iter([v2.revision_id, v4.revision_id, v4.revision_id])

        def lookup(sid):
            return next(answers)

        def rerun2():
            return make_run(cat, v2)

        res = finalize(state, ctx, summary, mode="current_required", lookup=lookup, rerun=rerun2)
        assert res.status == "deferred" and res.outcome is None and res.restarts == 1
        assert "source_changed_after_restart" in res.reasons


def test_no_change_and_missing_restart_and_bad_mode(tmp_path):
    v1, v2 = rev(14), rev(21)
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        state, ctx, summary = make_run(cat, v1)
        same = finalize(state, ctx, summary, mode="current_required", lookup=lambda sid: v1.revision_id)
        assert same.status == "decided" and same.restarts == 0 and same.origin_updates == ()
        cat.add_revision(v2)
        # current-required with no way to restart: defer rather than answer from the old revision
        d = finalize(state, ctx, summary, mode="current_required", lookup=lambda sid: v2.revision_id)
        assert d.status == "deferred" and d.outcome is None and "source_changed_no_restart" in d.reasons
        # an origin that cannot be read counts as a change in current-required mode
        gone = finalize(state, ctx, summary, mode="current_required", lookup=lambda sid: None)
        assert gone.status == "deferred" and gone.origin_updates[0].current_revision_id is None
        with pytest.raises(ContractError):
            finalize(state, ctx, summary, mode="latest_wins", lookup=lambda sid: v1.revision_id)


def test_undecided_runs_stay_deferred_regardless_of_mode(tmp_path):
    v1 = rev(14)
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        state, ctx, summary = make_run(cat, v1)
        state.observations["ok"] = Observation(Outcome.UNKNOWN, "forced")
        summary = RunSummary(check_stop(state.plan.expression, state.observations, state.ledger), (), ())
        r = finalize(state, ctx, summary, mode="snapshot", lookup=lambda sid: v1.revision_id)
        assert r.status == "deferred" and r.outcome is None

@pytest.mark.parametrize("origin", ["fresh", "reused"])
def test_unreviewed_origins_defer(tmp_path, origin):
    from dataclasses import replace

    v1 = rev(21)
    with Catalog.open(tmp_path / "c.sqlite") as cat:
        state, ctx, summary = make_run(cat, v1)
        state.plan = replace(state.plan, origin=origin)
        result = finalize(state, ctx, summary, mode="snapshot", lookup=lambda sid: v1.revision_id)
        assert result.status == "deferred"
        assert result.outcome is None
        assert "plan_coverage_unestablished" in result.reasons
