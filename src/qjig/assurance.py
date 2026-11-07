"""Evaluate explicitly attributed graph counterexamples; never certify semantics."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import ContractError
from .logic import Observation, Outcome, evaluate
from .plans import Plan, parse_plan


@dataclass(frozen=True)
class Counterexample:
    case_id: str
    observations: Mapping[str, Observation]
    expected: Outcome
    attribution: str


@dataclass(frozen=True)
class CounterexampleResult:
    case_id: str
    expected: Outcome
    actual: Outcome
    classification: str
    attribution: str
    independent: bool = False


def check_counterexamples(plan: Plan, cases: Sequence[Counterexample]) -> tuple[CounterexampleResult, ...]:
    """Compare a validated graph to labeled hypothetical assignments, not source meaning."""
    if not isinstance(plan, Plan):
        raise ContractError("validated plan required")
    checked = parse_plan({"origin": plan.origin, "predicates": [
        {"id": p.id, "question": p.question, "depends_on": list(p.depends_on),
         **({"exact_operator": p.exact_operator} if p.exact_operator is not None else {})}
        for p in plan.predicates], "expression": plan.expression})
    ids = {p.id for p in checked.predicates}
    results = []
    seen = set()
    for case in cases:
        if (not isinstance(case, Counterexample) or not isinstance(case.case_id, str) or not case.case_id.strip()
                or case.case_id in seen or not isinstance(case.attribution, str) or not case.attribution.strip()
                or not isinstance(case.expected, Outcome) or not isinstance(case.observations, Mapping)
                or any(k not in ids or not isinstance(v, Observation) or not isinstance(v.outcome, Outcome)
                       for k, v in case.observations.items())):
            raise ContractError("invalid authored counterexample")
        seen.add(case.case_id)
        actual = evaluate(checked.expression, case.observations).outcome
        if actual == case.expected:
            classification = "matches_authored_expectation"
        elif actual in (Outcome.UNKNOWN, Outcome.CONFLICT) and case.expected in (Outcome.TRUE, Outcome.FALSE):
            classification = "inconclusive"
        else:
            classification = "contradicts_authored_expectation"
        results.append(CounterexampleResult(case.case_id, case.expected, actual, classification, case.attribution))
    return tuple(results)
