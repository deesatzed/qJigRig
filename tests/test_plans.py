import copy

import pytest

from qjig.plans import PlanError, parse_plan

GOOD = {
    "origin": "authored",
    "predicates": [
        {"id": "ordinary", "question": "Is the purchase within 30 days?"},
        {"id": "exception", "question": "Does a waiver apply?", "depends_on": ["ordinary"]},
    ],
    "expression": {"op": "or", "args": [{"ref": "ordinary"}, {"ref": "exception"}]},
}


def mutate(fn):
    d = copy.deepcopy(GOOD)
    fn(d)
    return d


def test_validate_ast():
    plan = parse_plan(GOOD)
    assert [p.id for p in plan.predicates] == ["ordinary", "exception"] and plan.origin == "authored"
    assert parse_plan(GOOD) == plan  # deterministic


def deep(n):
    node = {"ref": "ordinary"}
    for _ in range(n):
        node = {"op": "not", "args": [node]}
    return node


CASES = {
    "dangling_ref": mutate(lambda d: d["expression"]["args"].append({"ref": "ghost"})),
    "duplicate_predicate": mutate(lambda d: d["predicates"].append({"id": "ordinary", "question": "again"})),
    "unknown_operator": mutate(lambda d: d["expression"].update(op="xor")),
    "dependency_cycle": mutate(lambda d: d["predicates"][0].update(depends_on=["exception"])),
    "self_dependency": mutate(lambda d: d["predicates"][0].update(depends_on=["ordinary"])),
    "dangling_dependency": mutate(lambda d: d["predicates"][0].update(depends_on=["ghost"])),
    "too_many_predicates": mutate(
        lambda d: d["predicates"].extend({"id": f"p{i}", "question": "q"} for i in range(5))
    ),
    "too_deep": mutate(lambda d: d.update(expression=deep(12))),  # depth 13 with the leaf
    "no_predicates": mutate(lambda d: d.update(predicates=[])),
    "not_arity": mutate(lambda d: d.update(expression={"op": "not", "args": [{"ref": "ordinary"}, {"ref": "exception"}]})),
    "and_arity": mutate(lambda d: d.update(expression={"op": "and", "args": [{"ref": "ordinary"}]})),
    "unknown_exact_operator": mutate(lambda d: d["predicates"][0].update(exact_operator="regex_match")),
    "bad_origin": mutate(lambda d: d.update(origin="telepathy")),
    "bad_id": mutate(lambda d: d["predicates"][0].update(id="Has Space")),
    "extra_node_key": mutate(lambda d: d["expression"]["args"][0].update(code="__import__('os')")),
    "executable_code_field": mutate(lambda d: d.update(code="print(1)")),
    "bad_node": mutate(lambda d: d.update(expression=True)),
}


@pytest.mark.parametrize("code", sorted(CASES))
def test_invalid_plans_fail_with_a_named_reason(code):
    with pytest.raises(PlanError) as exc:
        parse_plan(CASES[code])
    assert exc.value.code == code


def test_boundaries_that_must_still_pass():
    six = mutate(lambda d: d["predicates"].extend({"id": f"p{i}", "question": "q"} for i in range(4)))
    assert len(parse_plan(six).predicates) == 6
    assert parse_plan(mutate(lambda d: d.update(expression=deep(11)))).origin == "authored"  # depth 12 with the leaf
    ok = mutate(lambda d: d["predicates"][0].update(exact_operator="lte"))
    assert parse_plan(ok).predicates[0].exact_operator == "lte"
