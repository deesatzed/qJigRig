"""One bounded acquisition round: schedule a need, retrieve, verify, evaluate, record a trace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .applicability import Applicability
from .indexing import IndexEntry
from .contracts import ContractError
from .logic import Observation, Outcome, is_material
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
    followup: "NeedSpec | None" = None  # the single targeted second attempt, if any

MAX_ROUNDS = 2  # baseline cap per predicate: the first attempt plus one targeted followup


@dataclass(frozen=True)
class Context:
    catalog: Catalog
    entries: list[IndexEntry]  # current entries to search
    applicability: Callable[[Candidate], Applicability] | None
    specs: dict[str, NeedSpec]
    max_rounds: int = MAX_ROUNDS

    def __post_init__(self) -> None:
        if type(self.max_rounds) is not int or not 1 <= self.max_rounds <= MAX_ROUNDS:
            raise ContractError(f"max_rounds must be an integer from 1 to {MAX_ROUNDS}")


@dataclass(frozen=True)
class Refusal:
    predicate_id: str
    reason: str  # round_limit | no_targeted_followup


@dataclass
class RunState:
    request: Request
    plan: Plan
    ledger: ObligationLedger
    observations: dict[str, Observation] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    trace: list["TraceRecord"] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)


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
    exhausted: dict[str, str] = {}
    for p in state.plan.predicates:
        done = state.attempts.get(p.id, 0)
        base = ctx.specs[p.id]
        available = min(ctx.max_rounds, 1 + (1 if base.followup else 0))
        if done >= available:
            exhausted[p.id] = "round_limit" if done >= ctx.max_rounds else "no_targeted_followup"
    pid = next_need(state.plan, state.observations, exhausted=frozenset(exhausted))
    if pid is None:
        for p_id, reason in exhausted.items():  # material needs left unresolved: say so, once
            o = state.observations.get(p_id)
            unresolved = o is None or o.outcome not in (Outcome.TRUE, Outcome.FALSE)
            if unresolved and is_material(p_id, state.plan.expression, state.observations):
                refusal = Refusal(p_id, reason)
                if refusal not in state.refusals:
                    state.refusals.append(refusal)
        return None
    base = ctx.specs[pid]
    spec = base if state.attempts.get(pid, 0) == 0 else base.followup
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
