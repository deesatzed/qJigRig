"""Pick the next evidence need: prerequisites first, then planner order, then predicate id. Pure."""
from __future__ import annotations

from typing import Mapping

from .logic import Observation, Outcome, is_material
from .plans import Plan

_KNOWN = (Outcome.TRUE, Outcome.FALSE)


def next_need(
    plan: Plan, observations: Mapping[str, Observation], *, exhausted: frozenset[str] = frozenset()
) -> str | None:
    """The predicate id to work on next, or None when no material unresolved need remains.

    `exhausted` ids have used their attempts: they are never scheduled again and no longer hold
    back their dependents.
    """
    order = {p.id: i for i, p in enumerate(plan.predicates)}
    by_id = {p.id: p for p in plan.predicates}

    def resolved(pid: str) -> bool:
        o = observations.get(pid)
        return o is not None and o.outcome in _KNOWN

    def blocked_by(pid: str) -> list[str]:
        return [d for d in by_id[pid].depends_on if not resolved(d) and d not in exhausted]

    def ready_target(pid: str) -> str:
        """Follow unresolved prerequisites down to the first predicate that can run now."""
        while True:
            pending = blocked_by(pid)
            if not pending:
                return pid
            pid = sorted(pending, key=lambda d: (order[d], d))[0]

    wanted = {
        ready_target(p.id)
        for p in plan.predicates
        if not resolved(p.id) and p.id not in exhausted and is_material(p.id, plan.expression, observations)
    }
    wanted -= exhausted
    if not wanted:
        return None
    return sorted(wanted, key=lambda i: (order[i], i))[0]
