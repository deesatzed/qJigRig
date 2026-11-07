"""One bounded acquisition round: schedule a need, retrieve, verify, evaluate, record a trace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .applicability import Applicability
from .indexing import IndexEntry
from .contracts import ContractError
from .logic import Observation, Outcome, evaluate, expression_ids, is_material
from .obligations import ObligationLedger
from .packets import EvidencePacket
from .plans import Plan
from .contracts import Request
from .recovery import Exclusion, RecoveryResult, recover_packet
from .retrieval import Candidate, bm25_candidates
from .scheduler import next_need
from .stopping import StopDecision, check_stop
from .budgets import BudgetExceeded, BudgetLedger
from .judge import JudgeResult, QuoteRef, judge_predicate
from .obligations import Obligation
from .planner import PlanBinding, request_fresh_plan
from .providers import ProviderUnavailable, ReservationFactory, Transport
from .journal import ReconciliationRequired, UncertainOutcome
from .plans import Plan as _Plan  # noqa: F401
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


@dataclass(frozen=True)
class Skip:
    """A predicate that was deliberately not worked on, and why."""

    predicate_id: str
    kind: str  # witnessed | unwitnessed | unreferenced
    witnesses: tuple[str, ...]  # predicate ids whose known values fixed the outcome
    reason: str


@dataclass(frozen=True)
class RunSummary:
    stop: StopDecision
    skipped: tuple[Skip, ...]
    conflicts: tuple[str, ...] = ()  # material predicates whose applicable evidence disagrees


@dataclass
class RunState:
    request: Request
    plan: Plan
    ledger: ObligationLedger
    observations: dict[str, Observation] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    trace: list["TraceRecord"] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)


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


def run_until_done(state: RunState, ctx: Context) -> RunSummary:
    """Run rounds until no material need remains, then record stop status and every skip."""
    guard = len(state.plan.predicates) * ctx.max_rounds + 1
    for _ in range(guard):
        if run_round(state, ctx) is None:
            break
    referenced = expression_ids(state.plan.expression)
    result = evaluate(state.plan.expression, state.observations)
    skips: list[Skip] = []
    for p in state.plan.predicates:
        if state.attempts.get(p.id, 0) or p.id in state.observations:
            continue
        if p.id not in referenced:
            skips.append(Skip(p.id, "unreferenced", (), "not_in_expression"))
        elif result.outcome in (Outcome.TRUE, Outcome.FALSE) and result.witnesses:
            why = "; ".join(
                f"{w}={state.observations[w].outcome.value} ({state.observations[w].reason})" for w in result.witnesses
            )
            skips.append(Skip(p.id, "witnessed", result.witnesses, why))
        else:
            skips.append(Skip(p.id, "unwitnessed", (), "immaterial_without_conclusive_witness"))
    for sk in skips:
        if sk.kind == "unwitnessed":
            continue  # nothing conclusive justifies dropping its obligations
        for ob in state.ledger.for_predicate(sk.predicate_id):
            if ob.kind not in ("entity", "applicability"):
                state.ledger.skip(ob.obligation_id, reason=f"skipped: {sk.reason}")
    state.skipped = skips
    stop = check_stop(state.plan.expression, state.observations, state.ledger)
    conflicts = tuple(
        p.id
        for p in state.plan.predicates
        if p.id in state.observations
        and state.observations[p.id].outcome is Outcome.CONFLICT
        and is_material(p.id, state.plan.expression, state.observations)
    )
    return RunSummary(stop, tuple(skips), conflicts)


COVERAGE_ID = "ob-plan-coverage"
EXCEPTION_QUERY = "exception exceptions waiver unless except special case"


@dataclass(frozen=True)
class FreshRun:
    """Result of the model-planned path. It is never `decided`: a generated plan is not known complete."""

    status: str  # always "deferred" until a reviewer closes the plan-coverage gap
    reasons: tuple[str, ...]
    plan_failure: str | None
    binding: PlanBinding | None
    state: RunState | None
    summary: RunSummary | None
    judgments: dict[str, JudgeResult]
    quote_refs: dict[str, tuple[QuoteRef, ...]]  # predicate id -> verified quote bindings that carried a decision
    coverage_candidates: tuple[str, ...]  # entry ids of exception-channel passages found, offered for review


def run_fresh(
    *,
    request: Request,
    catalog: Catalog,
    entries: list[IndexEntry],
    ledger: BudgetLedger,
    transport: Transport,
    planner: tuple[str, str],
    judge: tuple[str, str],
    revision_applicability: Callable[[str], Applicability],
    planner_max_tokens: int | None = None,
    judge_max_tokens: int | None = None,
    reservation_factory: ReservationFactory | None = None, archive=None,
    want: int = 3,
    max_bytes: int = 3000,
) -> FreshRun:
    """Plan with a model, then answer each predicate through the canonical retrieval, recovery and judge path.

    Every decisive quote keeps its binding. An unresolved predicate stays unresolved. Because the plan is
    model-written, a material plan-coverage obligation is always opened; retrieval can offer exception
    passages for review but can never close it, so the result is a deferral that names the gap.
    """
    kw = {} if planner_max_tokens is None else {"max_tokens": planner_max_tokens}
    try:
        outcome = request_fresh_plan(
            ledger, transport, request, corpus_revision_ids=sorted({e.span.revision_id for e in entries}),
            provider=planner[0], model=planner[1], reservation_factory=reservation_factory, archive=archive, **kw,
        )
    except (BudgetExceeded, ProviderUnavailable, UncertainOutcome, ReconciliationRequired) as exc:
        failure = {BudgetExceeded: "budget_exceeded", ProviderUnavailable: "provider_unavailable",
                   UncertainOutcome: "uncertain_outcome", ReconciliationRequired: "reconciliation_required"}[type(exc)]
        return FreshRun("deferred", (f"plan_unavailable:{failure}",), failure, None, None, None, {}, {}, ())
    if not outcome.ok:
        return FreshRun("deferred", (f"plan_unavailable:{outcome.failure}",), outcome.failure, None, None, None, {}, {}, ())

    plan = outcome.plan
    judgments: dict[str, JudgeResult] = {}
    refs: dict[str, tuple[QuoteRef, ...]] = {}
    jkw = {} if judge_max_tokens is None else {"max_tokens": judge_max_tokens}

    halted = False

    def make_evaluator(question: str, pid: str):
        def evaluate(packet: EvidencePacket, recovery: RecoveryResult) -> EvalResult:
            nonlocal halted
            if halted:
                return EvalResult(Outcome.UNKNOWN, "reconciliation_required")
            result = judge_predicate(
                ledger, transport, question, packet, provider=judge[0], model=judge[1],
                applicability=revision_applicability, reservation_factory=reservation_factory, archive=archive, **jkw,
            )
            halted = any(side.failure in ("uncertain_outcome", "reconciliation_required")
                         for side in (result.positive, result.negative))
            judgments[pid] = result
            used = tuple(r for r in (result.positive.quote_ref, result.negative.quote_ref) if r is not None)
            refs[pid] = used
            return EvalResult(result.outcome, result.observation.reason, tuple(dict.fromkeys(r.entry_id for r in used)))

        return evaluate

    check = lambda c: revision_applicability(c.revision_id)  # noqa: E731
    specs = {p.id: NeedSpec(p.question, want, max_bytes, make_evaluator(p.question, p.id)) for p in plan.predicates}
    obligations = ObligationLedger()
    for p in plan.predicates:
        obligations.open(Obligation(f"ob-{p.id}", "predicate_evidence", p.id, p.question, material=True))
    obligations.open(Obligation(COVERAGE_ID, "exception", "__plan__", "model-written plan completeness is not established", material=True))
    exc = recover_packet(catalog, bm25_candidates(entries, EXCEPTION_QUERY), want=want, max_bytes=max_bytes, applicability=check)
    obligations.record_retrieval(COVERAGE_ID, hit_count=len(bm25_candidates(entries, EXCEPTION_QUERY)), result=exc)

    state = RunState(request, plan, obligations)
    ctx = Context(catalog, entries, check, specs)
    summary = run_until_done(state, ctx)
    reasons = ("plan_coverage_unestablished",) + tuple(r for r in summary.stop.reasons if r != "plan_coverage_unestablished")
    return FreshRun(
        "deferred", reasons, None, outcome.binding, state, summary, judgments, refs,
        tuple(i.entry_id for i in exc.packet.items),
    )
