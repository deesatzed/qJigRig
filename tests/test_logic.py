import pytest

from qjig.contracts import ContractError
from qjig.logic import Outcome, Support, combine_support


@pytest.mark.parametrize(
    "pos,neg,expected",
    [
        (Support.SUPPORTED, Support.UNKNOWN, Outcome.TRUE),
        (Support.UNKNOWN, Support.SUPPORTED, Outcome.FALSE),
        (Support.UNKNOWN, Support.UNKNOWN, Outcome.UNKNOWN),
        (Support.SUPPORTED, Support.SUPPORTED, Outcome.CONFLICT),
    ],
)
def test_support_state_table(pos, neg, expected):
    assert combine_support(pos, neg) is expected


def test_four_combinations_give_four_distinct_outcomes():
    results = {combine_support(p, n) for p in Support for n in Support}
    assert results == {Outcome.TRUE, Outcome.FALSE, Outcome.UNKNOWN, Outcome.CONFLICT}


@pytest.mark.parametrize("pos,neg", [(True, False), (False, False), ("supported", Support.UNKNOWN), (None, Support.UNKNOWN), (Support.UNKNOWN, 0)])
def test_only_explicit_support_states_are_accepted(pos, neg):
    # a bare boolean/score cannot stand in for support on the negative side
    with pytest.raises(ContractError):
        combine_support(pos, neg)


from qjig.logic import Observation, evaluate

T, F, U, C = Outcome.TRUE, Outcome.FALSE, Outcome.UNKNOWN, Outcome.CONFLICT

AND_TABLE = {
    (T, T): T, (T, F): F, (T, U): U, (T, C): C,
    (F, T): F, (F, F): F, (F, U): F, (F, C): F,
    (U, T): U, (U, F): F, (U, U): U, (U, C): C,
    (C, T): C, (C, F): F, (C, U): C, (C, C): C,
}
OR_TABLE = {
    (T, T): T, (T, F): T, (T, U): T, (T, C): T,
    (F, T): T, (F, F): F, (F, U): U, (F, C): C,
    (U, T): T, (U, F): U, (U, U): U, (U, C): C,
    (C, T): T, (C, F): C, (C, U): C, (C, C): C,
}
NOT_TABLE = {T: F, F: T, U: U, C: C}


def obs(**kw):
    return {k: Observation(v, f"why_{k}") for k, v in kw.items()}


@pytest.mark.parametrize("pair", sorted(AND_TABLE, key=str))
def test_compose_truth_table(pair):
    a, b = pair
    o = obs(a=a, b=b)
    both = lambda op: {"op": op, "args": [{"ref": "a"}, {"ref": "b"}]}
    assert evaluate(both("and"), o).outcome is AND_TABLE[pair]
    assert evaluate(both("or"), o).outcome is OR_TABLE[pair]


@pytest.mark.parametrize("value", list(Outcome))
def test_not_table(value):
    assert evaluate({"op": "not", "args": [{"ref": "a"}]}, obs(a=value)).outcome is NOT_TABLE[value]


def test_unknown_and_conflict_reasons_are_preserved():
    expr = {"op": "or", "args": [{"ref": "ordinary"}, {"op": "and", "args": [{"ref": "exception"}, {"ref": "extra"}]}]}
    o = {
        "ordinary": Observation(F, "outside_30_days"),
        "exception": Observation(U, "no_retrieval_hit"),
        "extra": Observation(C, "two_applicable_sources_disagree"),
    }
    r = evaluate(expr, o)
    assert r.outcome is C
    assert {(u.predicate_id, u.outcome, u.reason) for u in r.unresolved} == {
        ("exception", U, "no_retrieval_hit"),
        ("extra", C, "two_applicable_sources_disagree"),
    }
    # a conclusive operand makes the unresolved ones irrelevant to the result
    r2 = evaluate(expr, {**o, "ordinary": Observation(T, "within_30_days")})
    assert r2.outcome is T and r2.unresolved == () and r2.witnesses == ("ordinary",)
    # a missing observation is an explicit unknown with its own reason
    r3 = evaluate({"ref": "ghost"}, {})
    assert r3.outcome is U and r3.unresolved[0].reason == "no_observation"
