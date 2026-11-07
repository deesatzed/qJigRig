"""Exact numeric rules under the policy version that applies on the request date. Pure."""
from __future__ import annotations

import operator
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .applicability import Applicability, MemberMetadata, date_applicability, entity_applicability
from .contracts import ContractError
from .logic import Outcome
from .plans import EXACT_OPERATORS

_OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge}
assert set(_OPS) == set(EXACT_OPERATORS)


def _exact(value: object, name: str) -> Decimal:
    if type(value) is Decimal:
        d = value
    elif type(value) is int:
        d = Decimal(value)
    else:
        raise ContractError(f"{name} must be an int or Decimal, got {type(value).__name__}")
    if not d.is_finite():
        raise ContractError(f"{name} must be finite")
    return d


@dataclass(frozen=True)
class FieldValue:
    field: str
    value: int | Decimal

    def __post_init__(self) -> None:
        _exact(self.value, "value")


@dataclass(frozen=True)
class NumericRule:
    field: str
    operator: str
    threshold: Decimal

    def __post_init__(self) -> None:
        if self.operator not in _OPS:
            raise ContractError(f"unknown operator {self.operator!r}")
        _exact(self.threshold, "threshold")


@dataclass(frozen=True)
class PolicyRule:
    member: MemberMetadata
    rule: NumericRule


@dataclass(frozen=True)
class ExactResult:
    outcome: Outcome
    revision_id: str | None  # the policy revision applied, if exactly one applied
    reason: str


def evaluate_dated_numeric(
    observation: FieldValue,
    policies: Iterable[PolicyRule],
    *,
    as_of: str,
    request_entities: frozenset[str],
    historical_as_known: bool,
) -> ExactResult:
    """Apply the one policy that is applicable by date and subject; never choose by recency of file."""
    applicable, unknown = [], []
    for p in policies:
        if p.rule.field != observation.field:
            continue  # a rule about a different field says nothing about this number
        ent = entity_applicability(p.member, request_entities).value
        dat = date_applicability(p.member, as_of, historical_as_known=historical_as_known).overall
        if Applicability.NO_MATCH in (ent, dat):
            continue
        (unknown if Applicability.UNKNOWN in (ent, dat) else applicable).append(p)
    if len(applicable) > 1:
        return ExactResult(Outcome.CONFLICT, None, "multiple_applicable_policies")
    if applicable and unknown:  # a possibly newer or competing policy cannot be ruled out
        return ExactResult(Outcome.UNKNOWN, None, "applicable_policy_ambiguous")
    if not applicable:
        return ExactResult(Outcome.UNKNOWN, None, "applicability_unknown" if unknown else "no_applicable_policy")
    chosen = applicable[0]
    ok = _OPS[chosen.rule.operator](_exact(observation.value, "value"), chosen.rule.threshold)
    return ExactResult(Outcome.TRUE if ok else Outcome.FALSE, chosen.member.revision_id, "rule_evaluated")
