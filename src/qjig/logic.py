"""Pure decision logic over explicit true/false/unknown/conflict states."""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .contracts import ContractError


class Support(Enum):
    SUPPORTED = "supported"
    UNKNOWN = "unknown"


class Outcome(Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


def combine_support(positive: Support, negative: Support) -> Outcome:
    """Combine separate support for a proposition (positive) and for its negation (negative).

    Absence of support for a side is UNKNOWN, never evidence for the other side.
    """
    if not isinstance(positive, Support) or not isinstance(negative, Support):
        raise ContractError("support must be a Support state, not a boolean or score")
    if positive is Support.SUPPORTED and negative is Support.SUPPORTED:
        return Outcome.CONFLICT
    if positive is Support.SUPPORTED:
        return Outcome.TRUE
    if negative is Support.SUPPORTED:
        return Outcome.FALSE
    return Outcome.UNKNOWN


@dataclass(frozen=True)
class Observation:
    outcome: Outcome
    reason: str = ""


@dataclass(frozen=True)
class Unresolved:
    predicate_id: str
    outcome: Outcome  # UNKNOWN or CONFLICT
    reason: str


@dataclass(frozen=True)
class Evaluation:
    outcome: Outcome
    unresolved: tuple[Unresolved, ...]  # unknown/conflict leaves that the result still depends on
    witnesses: tuple[str, ...]  # predicate ids whose known value fixed the result


def _eval(node: Mapping[str, Any], obs: Mapping[str, Observation]) -> Evaluation:
    if "ref" in node:
        pid = node["ref"]
        o = obs.get(pid)
        if o is None:
            return Evaluation(Outcome.UNKNOWN, (Unresolved(pid, Outcome.UNKNOWN, "no_observation"),), ())
        if o.outcome in (Outcome.UNKNOWN, Outcome.CONFLICT):
            return Evaluation(o.outcome, (Unresolved(pid, o.outcome, o.reason),), ())
        return Evaluation(o.outcome, (), (pid,))
    op, kids = node["op"], [_eval(a, obs) for a in node["args"]]
    if op == "not":
        k = kids[0]
        flip = {Outcome.TRUE: Outcome.FALSE, Outcome.FALSE: Outcome.TRUE}
        return Evaluation(flip.get(k.outcome, k.outcome), k.unresolved, k.witnesses)
    decisive = Outcome.FALSE if op == "and" else Outcome.TRUE
    fixed = [k for k in kids if k.outcome is decisive]
    if fixed:  # one conclusive operand settles it; unresolved siblings do not matter
        return Evaluation(decisive, (), tuple(w for k in fixed for w in k.witnesses))
    unresolved = tuple(u for k in kids for u in k.unresolved)
    if unresolved:
        has_conflict = any(k.outcome is Outcome.CONFLICT for k in kids)
        return Evaluation(Outcome.CONFLICT if has_conflict else Outcome.UNKNOWN, unresolved, ())
    return Evaluation(kids[0].outcome, (), tuple(w for k in kids for w in k.witnesses))


def evaluate(expression: Mapping[str, Any], observations: Mapping[str, Observation]) -> Evaluation:
    """Evaluate a validated AND/OR/NOT expression. Each leaf is evaluated independently.

    Repeated references are not tied together here; use reachable outcomes (T028) for that.
    """
    return _eval(expression, observations)


MAX_UNRESOLVED = 6  # at most 2**6 = 64 completions


@dataclass(frozen=True)
class Reachable:
    outcomes: frozenset[bool]  # distinct expression values over all consistent completions
    completions: int
    unresolved_ids: tuple[str, ...]


def _refs(node: Mapping[str, Any]) -> set[str]:
    if "ref" in node:
        return {node["ref"]}
    return set().union(*(_refs(a) for a in node["args"]))


def _bool_eval(node: Mapping[str, Any], values: Mapping[str, bool]) -> bool:
    if "ref" in node:
        return values[node["ref"]]
    vals = [_bool_eval(a, values) for a in node["args"]]
    return (not vals[0]) if node["op"] == "not" else (all(vals) if node["op"] == "and" else any(vals))


def reachable_outcomes(expression: Mapping[str, Any], observations: Mapping[str, Observation]) -> Reachable:
    """Every Boolean value the expression can take, assigning each unresolved id once.

    UNKNOWN, CONFLICT and missing observations are free variables; TRUE/FALSE are fixed.
    A reference that appears several times shares one value.
    """
    ids = sorted(_refs(expression))
    fixed = {i: observations[i].outcome is Outcome.TRUE for i in ids if i in observations and observations[i].outcome in (Outcome.TRUE, Outcome.FALSE)}
    free = [i for i in ids if i not in fixed]
    if len(free) > MAX_UNRESOLVED:
        raise ContractError(f"{len(free)} unresolved predicates exceeds the cap of {MAX_UNRESOLVED}")
    results = set()
    count = 0
    for combo in itertools.product((False, True), repeat=len(free)):
        count += 1
        results.add(_bool_eval(expression, {**fixed, **dict(zip(free, combo))}))
    return Reachable(frozenset(results), count, tuple(free))


def is_material(predicate_id: str, expression: Mapping[str, Any], observations: Mapping[str, Observation]) -> bool:
    """Can this unresolved predicate change the result under some completion of the others?

    False for a predicate that is already TRUE/FALSE, or that does not occur in the expression.
    """
    ids = _refs(expression)
    if predicate_id not in ids:
        return False
    o = observations.get(predicate_id)
    if o is not None and o.outcome in (Outcome.TRUE, Outcome.FALSE):
        return False
    fixed = {i: observations[i].outcome is Outcome.TRUE for i in ids if i in observations and observations[i].outcome in (Outcome.TRUE, Outcome.FALSE)}
    others = sorted(i for i in ids if i not in fixed and i != predicate_id)
    if len(others) + 1 > MAX_UNRESOLVED:
        raise ContractError(f"more than {MAX_UNRESOLVED} unresolved predicates")
    for combo in itertools.product((False, True), repeat=len(others)):
        base = {**fixed, **dict(zip(others, combo))}
        if _bool_eval(expression, {**base, predicate_id: False}) != _bool_eval(expression, {**base, predicate_id: True}):
            return True
    return False
