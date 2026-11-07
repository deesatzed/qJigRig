"""When may acquisition stop? Only if the outcome is fixed AND no material obligation is open."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .logic import Observation, reachable_outcomes
from .obligations import ObligationLedger


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    outcome: bool | None  # the single reachable value when stable, else None
    reasons: tuple[str, ...]  # why it cannot stop
    blocking_obligations: tuple[str, ...]
    caveats: tuple[str, ...]  # true even when stopping
    unresolved_ids: tuple[str, ...]


def check_stop(
    expression: Mapping[str, Any], observations: Mapping[str, Observation], ledger: ObligationLedger
) -> StopDecision:
    reach = reachable_outcomes(expression, observations)
    blocking = tuple(ledger.blocking())
    reasons: list[str] = []
    stable = len(reach.outcomes) == 1
    if not stable:
        reasons.append("outcome_not_determined")
    if blocking:
        reasons.append("material_obligation_unresolved")
    caveats = ("stable_despite_unresolved_predicates",) if stable and reach.unresolved_ids else ()
    if reasons:
        return StopDecision(False, None, tuple(reasons), blocking, caveats, reach.unresolved_ids)
    (value,) = reach.outcomes
    return StopDecision(True, value, (), (), caveats, reach.unresolved_ids)
