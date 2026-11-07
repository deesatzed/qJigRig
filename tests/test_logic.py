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


from qjig.logic import reachable_outcomes


def ref(n):
    return {"ref": n}


def test_reachable_outcomes():
    unknown_a = obs(a=U)
    # repeated references share one assignment: A OR NOT A is true under every completion
    taut = {"op": "or", "args": [ref("a"), {"op": "not", "args": [ref("a")]}]}
    r = reachable_outcomes(taut, unknown_a)
    assert r.outcomes == frozenset({True}) and r.completions == 2 and r.unresolved_ids == ("a",)
    assert evaluate(taut, unknown_a).outcome is U  # independent-leaf evaluation cannot see this
    contra = {"op": "and", "args": [ref("a"), {"op": "not", "args": [ref("a")]}]}
    assert reachable_outcomes(contra, unknown_a).outcomes == frozenset({False})
    # two different unresolved facts can swing the answer both ways
    free = {"op": "or", "args": [ref("a"), ref("b")]}
    r2 = reachable_outcomes(free, obs(a=U, b=C))
    assert r2.outcomes == frozenset({True, False}) and r2.completions == 4
    # known values are fixed, not enumerated; conflict and missing count as unresolved
    r3 = reachable_outcomes(free, obs(a=T, b=C))
    assert r3.outcomes == frozenset({True}) and r3.completions == 2 and r3.unresolved_ids == ("b",)
    assert reachable_outcomes(ref("ghost"), {}).unresolved_ids == ("ghost",)
    # nothing unresolved: exactly one completion
    r4 = reachable_outcomes(free, obs(a=F, b=F))
    assert r4.outcomes == frozenset({False}) and r4.completions == 1


def test_more_than_six_unresolved_ids_refused():
    names = [f"p{i}" for i in range(7)]
    expr = {"op": "or", "args": [ref(n) for n in names]}
    with pytest.raises(ContractError):
        reachable_outcomes(expr, {})
    six = {"op": "or", "args": [ref(n) for n in names[:6]]}
    assert reachable_outcomes(six, {}).completions == 64


from qjig.logic import is_material


def test_material_predicate():
    either = {"op": "or", "args": [ref("ordinary"), ref("exception")]}
    both = {"op": "and", "args": [ref("ordinary"), ref("exception")]}
    # ordinary=false with the exception unknown under OR: the exception still decides the answer
    assert is_material("exception", either, obs(ordinary=F, exception=U)) is True
    # ordinary=true under OR already settles it; the exception no longer matters
    assert is_material("exception", either, obs(ordinary=T, exception=U)) is False
    # under AND a known false blocks everything, so the unrelated unknown is immaterial
    assert is_material("exception", both, obs(ordinary=F, exception=U)) is False
    assert is_material("exception", both, obs(ordinary=T, exception=C)) is True  # conflict is unresolved too
    # a missing observation counts as unresolved
    assert is_material("exception", either, obs(ordinary=F)) is True


def test_materiality_with_several_unresolved_and_shared_refs():
    expr = {"op": "or", "args": [{"op": "and", "args": [ref("a"), ref("b")]}, ref("c")]}
    assert is_material("a", expr, obs(a=U, b=U, c=U)) is True  # b true, c false: a decides
    assert is_material("a", expr, obs(a=U, b=U, c=T)) is False  # c settles it
    assert is_material("a", expr, obs(a=U, b=F, c=U)) is False  # b false kills the AND branch
    taut = {"op": "or", "args": [ref("a"), {"op": "not", "args": [ref("a")]}]}
    assert is_material("a", taut, obs(a=U)) is False  # same value in both branches: no effect
    # a resolved or absent predicate is not an unresolved fact that could change the result
    assert is_material("ordinary", expr, obs(a=U, b=U, c=U)) is False
    assert is_material("a", expr, obs(a=T, b=U, c=U)) is False
