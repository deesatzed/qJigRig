from decimal import Decimal

import pytest

from qjig.applicability import OPEN, Interval, MemberMetadata
from qjig.contracts import ContractError
from qjig.exact import FieldValue, NumericRule, PolicyRule, evaluate_dated_numeric
from qjig.logic import Outcome


def policy(rev, start, end, op, limit, field="refund_days", entities=("customer:42",), observed_at="2026-01-01"):
    meta = MemberMetadata(rev, "project", Interval(start, end), entity_keys=frozenset(entities), observed_at=observed_at)
    return PolicyRule(meta, NumericRule(field, op, Decimal(limit)))


OLD = policy("rev-old", "2026-01-01", "2026-10-31", "lte", "30")
NEW = policy("rev-new", "2026-11-01", OPEN, "lte", "14", observed_at="2026-10-20")
OBS = FieldValue("refund_days", 20)
ENT = frozenset({"customer:42"})


def run(policies, as_of, obs=OBS, historical=False):
    return evaluate_dated_numeric(obs, policies, as_of=as_of, request_entities=ENT, historical_as_known=historical)


def test_dated_numeric_rule():
    # the same observation (20 days) passes the old threshold and fails the new one
    before = run([OLD, NEW], "2026-10-15")
    after = run([OLD, NEW], "2026-11-15")
    assert (before.outcome, before.revision_id) == (Outcome.TRUE, "rev-old")
    assert (after.outcome, after.revision_id) == (Outcome.FALSE, "rev-new")
    # list order is irrelevant; there is no "latest file wins" input at all
    assert run([NEW, OLD], "2026-10-15") == before and run([NEW, OLD], "2026-11-15") == after
    # inclusive boundaries
    assert run([OLD, NEW], "2026-10-31").revision_id == "rev-old"
    assert run([OLD, NEW], "2026-11-01").revision_id == "rev-new"


@pytest.mark.parametrize(
    "op,limit,value,expected",
    [("eq", "5", 5, True), ("eq", "5", 6, False), ("ne", "5", 6, True), ("lt", "5", 5, False), ("lt", "5", 4, True),
     ("lte", "5", 5, True), ("gt", "5", 5, False), ("gte", "5", 5, True), ("gte", "5", 4, False),
     ("lte", "2.50", Decimal("2.5"), True)],
)
def test_operator_table(op, limit, value, expected):
    p = policy("r", "2026-01-01", OPEN, op, limit)
    r = run([p], "2026-06-01", obs=FieldValue("refund_days", value))
    assert r.outcome is (Outcome.TRUE if expected else Outcome.FALSE)


def test_unverified_or_ambiguous_inputs_stay_unknown_or_conflict():
    # field binding differs: the number is not the thing the rule is about
    assert run([OLD], "2026-06-01", obs=FieldValue("shipping_days", 20)).outcome is Outcome.UNKNOWN
    # no policy covers the date
    assert run([OLD], "2027-01-01").outcome is Outcome.UNKNOWN
    # a policy with an unknown boundary cannot be assumed to apply
    unknown_end = policy("rev-x", "2026-01-01", __import__("qjig.applicability", fromlist=["x"]).UNKNOWN_BOUND, "lte", "30")
    assert run([unknown_end], "2026-06-01").outcome is Outcome.UNKNOWN
    # two applicable policies for the same date: conflict, not a pick
    clash = policy("rev-clash", "2026-05-01", OPEN, "lte", "7")
    r = run([OLD, clash], "2026-06-01")
    assert r.outcome is Outcome.CONFLICT and r.revision_id is None
    # a policy for another customer is not used
    other = policy("rev-other", "2026-01-01", OPEN, "lte", "1", entities=("customer:7",))
    assert run([other, OLD], "2026-06-01").revision_id == "rev-old"
    # historical-as-known: a policy recorded after the request date cannot be used
    late = policy("rev-late", "2026-01-01", OPEN, "lte", "1", observed_at="2026-12-01")
    assert run([late], "2026-06-01", historical=True).outcome is Outcome.UNKNOWN
    assert run([late], "2026-06-01", historical=False).revision_id == "rev-late"


@pytest.mark.parametrize("bad", [True, 1.5, "20", None, float("nan")])
def test_observation_values_must_be_exact_numbers(bad):
    with pytest.raises(ContractError):
        FieldValue("refund_days", bad)


def test_clear_policy_plus_unknown_one_is_not_silently_resolved():
    unrecorded_subject = policy("rev-unk", "2026-05-01", OPEN, "lte", "7", entities=())  # may be newer and apply
    r = run([OLD, unrecorded_subject], "2026-06-01")
    assert r.outcome is Outcome.UNKNOWN and r.reason == "applicable_policy_ambiguous" and r.revision_id is None
