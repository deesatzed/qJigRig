"""Pure decision logic over explicit true/false/unknown/conflict states."""
from __future__ import annotations

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
