from qjig.logic import Observation, Outcome
from qjig.plans import parse_plan
from qjig.scheduler import next_need

T, F, U = Outcome.TRUE, Outcome.FALSE, Outcome.UNKNOWN


def plan(preds, expr):
    return parse_plan({"origin": "authored", "predicates": preds, "expression": expr})


def obs(**kw):
    return {k: Observation(v, "r") for k, v in kw.items()}


def q(pid, deps=()):
    return {"id": pid, "question": f"is {pid}?", "depends_on": list(deps)}


def either(*ids):
    return {"op": "or", "args": [{"ref": i} for i in ids]}


def test_deterministic_next_need():
    p = plan([q("exception", ["ordinary"]), q("ordinary")], either("exception", "ordinary"))
    # the planner listed the dependent first, but its prerequisite must come before it
    assert next_need(p, {}) == "ordinary"
    # once the prerequisite is resolved, the dependent is next (ordinary=false keeps it material)
    assert next_need(p, obs(ordinary=F)) == "exception"
    # same state, same answer, every time
    assert {next_need(p, {}) for _ in range(5)} == {"ordinary"}


def test_planner_order_then_id_among_independent_needs():
    p = plan([q("zeta"), q("alpha"), q("mid")], either("zeta", "alpha", "mid"))
    assert next_need(p, {}) == "zeta"  # planner order, not alphabetical
    assert next_need(p, obs(zeta=U)) == "zeta"  # still unresolved, still first
    assert next_need(p, obs(zeta=U), exhausted=frozenset({"zeta"})) == "alpha"
    assert next_need(p, obs(zeta=U), exhausted=frozenset({"zeta", "alpha", "mid"})) is None


def test_immaterial_and_resolved_predicates_are_not_scheduled():
    p = plan([q("ordinary"), q("exception")], either("ordinary", "exception"))
    assert next_need(p, obs(ordinary=T)) is None  # an OR already settled by ordinary=true
    assert next_need(p, obs(ordinary=T, exception=T)) is None
    both = plan([q("ordinary"), q("exception")], {"op": "and", "args": [{"ref": "ordinary"}, {"ref": "exception"}]})
    assert next_need(both, obs(ordinary=F)) is None  # a known blocker makes the rest irrelevant


def test_prerequisite_chain_is_never_skipped():
    p = plan([q("c", ["b"]), q("b", ["a"]), q("a")], {"ref": "c"})  # only c is in the expression
    assert next_need(p, {}) == "a"
    assert next_need(p, obs(a=T)) == "b"
    assert next_need(p, obs(a=T, b=T)) == "c"
    # a prerequisite whose attempts are used up no longer holds the dependent back
    assert next_need(p, obs(a=U), exhausted=frozenset({"a"})) == "b"
