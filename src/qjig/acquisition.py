"""One bounded acquisition round: schedule a need, retrieve, verify, evaluate, record a trace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .applicability import Applicability
from .indexing import IndexEntry
from .logic import Observation, Outcome
from .obligations import ObligationLedger
from .packets import EvidencePacket
from .plans import Plan
from .contracts import Request
from .recovery import Exclusion, RecoveryResult, recover_packet
from .retrieval import Candidate, bm25_candidates
from .scheduler import next_need
from .store import Catalog


@dataclass(frozen=True)
class EvalResult:
    outcome: Outcome
    reason: str
    evidence_entry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class NeedSpec:
    """How to look for one predicate's evidence and how to evaluate what is found."""

    query: str
    want: int
    max_bytes: int
    evaluate: Callable[[EvidencePacket, RecoveryResult], EvalResult]


@dataclass(frozen=True)
class Context:
    catalog: Catalog
    entries: list[IndexEntry]  # current entries to search
    applicability: Callable[[Candidate], Applicability] | None
    specs: dict[str, NeedSpec]


@dataclass
class RunState:
    request: Request
    plan: Plan
    ledger: ObligationLedger
    observations: dict[str, Observation] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    trace: list["TraceRecord"] = field(default_factory=list)


@dataclass(frozen=True)
class TraceEvidence:
    entry_id: str
    revision_id: str
    start: int
    end: int
    text_sha256: str
    text: str
    truncated: bool


@dataclass(frozen=True)
class TraceRecord:
    sequence: int
    request_id: str
    predicate_id: str
    round_number: int  # attempt number for this predicate
    query: str
    hit_count: int
    evidence: tuple[TraceEvidence, ...]
    exclusions: tuple[Exclusion, ...]
    observation: Observation


def run_round(state: RunState, ctx: Context) -> TraceRecord | None:
    """Work on the next material need once. Returns the trace record, or None if none remains."""
    pid = next_need(state.plan, state.observations)
    if pid is None:
        return None
    spec = ctx.specs[pid]
    candidates = bm25_candidates(ctx.entries, spec.query)
    recovery = recover_packet(
        ctx.catalog, candidates, want=spec.want, max_bytes=spec.max_bytes, applicability=ctx.applicability
    )
    ob_id = f"ob-{pid}"
    state.ledger.record_retrieval(ob_id, hit_count=len(candidates), result=recovery)
    ob = state.ledger.get(ob_id)
    if ob.status == "unresolved":  # nothing usable, or truncated/omitted: do not evaluate partial evidence
        observation = Observation(Outcome.UNKNOWN, ob.reason)
    else:
        result = spec.evaluate(recovery.packet, recovery)
        observation = Observation(result.outcome, result.reason)
        if result.outcome in (Outcome.TRUE, Outcome.FALSE) and result.evidence_entry_ids:
            state.ledger.satisfy(ob_id, evidence_entry_ids=result.evidence_entry_ids)
    state.observations[pid] = observation
    state.attempts[pid] = state.attempts.get(pid, 0) + 1
    record = TraceRecord(
        sequence=len(state.trace) + 1,
        request_id=state.request.request_id,
        predicate_id=pid,
        round_number=state.attempts[pid],
        query=spec.query,
        hit_count=len(candidates),
        evidence=tuple(
            TraceEvidence(i.entry_id, i.span.revision_id, i.span.start, i.span.end, i.span.text_sha256, i.span.text, i.truncated)
            for i in recovery.packet.items
        ),
        exclusions=recovery.exclusions,
        observation=observation,
    )
    state.trace.append(record)
    return record
