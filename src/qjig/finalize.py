"""Final source-binding check. A decision never mixes revisions of the same source."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .acquisition import Context, RunState, RunSummary
from .contracts import ContractError

MODES = ("snapshot", "current_required")


@dataclass(frozen=True)
class OriginUpdate:
    source_id: str
    used_revision_id: str
    current_revision_id: str | None  # None: the origin could not be read


@dataclass(frozen=True)
class FinalResult:
    status: str  # decided | deferred
    outcome: bool | None
    state: RunState
    summary: RunSummary
    origin_updates: tuple[OriginUpdate, ...]
    restarts: int
    superseded_runs: int
    reasons: tuple[str, ...]


def detect_updates(ctx: Context, state: RunState, lookup: Callable[[str], str | None]) -> tuple[OriginUpdate, ...]:
    used: dict[str, set[str]] = {}
    for rec in state.trace:
        for ev in rec.evidence:
            source_id = ctx.catalog.revision_source_id(ev.revision_id)
            if source_id is not None:
                used.setdefault(source_id, set()).add(ev.revision_id)
    updates = []
    for source_id in sorted(used):
        current = lookup(source_id)
        for revision_id in sorted(used[source_id]):
            if current != revision_id:
                updates.append(OriginUpdate(source_id, revision_id, current))
    return tuple(updates)


def _result(state, summary, updates, restarts, superseded, extra=()) -> FinalResult:
    if summary.stop.stop and not extra:
        return FinalResult("decided", summary.stop.outcome, state, summary, updates, restarts, superseded, ())
    reasons = tuple(extra) + tuple(summary.stop.reasons if not summary.stop.stop else ())
    return FinalResult("deferred", None, state, summary, updates, restarts, superseded, reasons)


def finalize(
    state: RunState,
    ctx: Context,
    summary: RunSummary,
    *,
    mode: str,
    lookup: Callable[[str], str | None],
    rerun: Callable[[], tuple[RunState, Context, RunSummary]] | None = None,
) -> FinalResult:
    """Recheck source bindings, then decide or defer.

    snapshot: stay bound to the revisions used; report origin updates separately.
    current_required: an origin update invalidates the result; restart once under a new snapshot
    (`rerun`), or defer. A second change after the restart also defers.
    """
    if mode not in MODES:
        raise ContractError(f"unknown mode {mode!r}")
    updates = detect_updates(ctx, state, lookup)
    if mode == "snapshot" or not updates:
        return _result(state, summary, updates, 0, 0)
    if rerun is None:
        return _result(state, summary, updates, 0, 0, extra=("source_changed_no_restart",))
    new_state, new_ctx, new_summary = rerun()
    after = detect_updates(new_ctx, new_state, lookup)
    if after:
        return _result(new_state, new_summary, after, 1, 1, extra=("source_changed_after_restart",))
    return _result(new_state, new_summary, (), 1, 1)
