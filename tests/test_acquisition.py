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
