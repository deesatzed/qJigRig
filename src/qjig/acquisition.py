"""One bounded acquisition round: schedule a need, retrieve, verify, evaluate, record a trace."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import json
from typing import Callable

from .applicability import Applicability, ApplicabilityInputs, combine_applicability, scope_applicability
from .indexing import IndexEntry
from .contracts import ContractError
from .logic import Observation, Outcome, evaluate, expression_ids, is_material
from .obligations import ObligationLedger
from .packets import EvidencePacket, serialize_packet
from .plans import Plan
from .contracts import Request
from .recovery import Exclusion, RecoveryResult, check_candidate, recover_packet
from .retrieval import BM25_METHOD, EXPANDED_BM25_METHOD, NEUTRAL_PRIOR, Candidate, bm25_candidates, bm25_expanded_candidates, select_unique_with_mandatory
from .scheduler import next_need
from .stopping import StopDecision, check_stop
from .budgets import BudgetExceeded, BudgetLedger
from .judge import JUDGE_MAX_TOKENS, JudgeResult, QuoteRef, judge_predicate
from .obligations import Obligation
from .planner import PLANNER_MAX_TOKENS, PLANNER_PROMPT_VERSIONS, PlanBinding, request_fresh_plan
from .providers import ProviderRequest, ProviderUnavailable, ReservationFactory, Transport
from .journal import ReconciliationRequired, UncertainOutcome
from .plans import Plan as _Plan  # noqa: F401
from .store import Catalog


@dataclass(frozen=True)
class EvalResult:
    outcome: Outcome
    reason: str
    evidence_entry_ids: tuple[str, ...] = ()


def _check_role_priors(priors: dict[str, float]) -> None:
    if not isinstance(priors, dict) or any(not isinstance(k, str) or type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for k, v in priors.items()):
        raise ContractError("role priors must be finite scores from zero to one")


@dataclass(frozen=True)
class NeedSpec:
    """How to look for one predicate's evidence and how to evaluate what is found."""

    query: str
    want: int
    max_bytes: int
    evaluate: Callable[[EvidencePacket, RecoveryResult], EvalResult]
    followup: "NeedSpec | None" = None  # the single targeted second attempt, if any
    retrieval_method: str = BM25_METHOD
    channel_queries: tuple[tuple[str, str], ...] = ()
    role_priors: dict[str, float] = field(default_factory=dict)
    followup_reasons: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.retrieval_method not in (BM25_METHOD, EXPANDED_BM25_METHOD, 'full_source_v1'):
            raise ContractError("unknown retrieval method")
        _check_role_priors(self.role_priors)

MAX_ROUNDS = 2  # baseline cap per predicate: the first attempt plus one targeted followup


@dataclass(frozen=True)
class Context:
    catalog: Catalog
    entries: list[IndexEntry]  # current entries to search
    applicability: Callable[[Candidate], Applicability] | None
    specs: dict[str, NeedSpec]
    max_rounds: int = MAX_ROUNDS
    archive: object | None = None

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
class ChannelReport:
    hits: dict[str, int]
    selected: tuple[str, ...]
    missing: tuple[str, ...]
    excluded: tuple[str, ...]
    omitted: tuple[str, ...]
    delivered: tuple[str, ...]
    packet_omissions: tuple[str, ...]
    packet_truncations: tuple[str, ...]


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
    retrieval_method: str = BM25_METHOD
    channels: ChannelReport | None = None


def run_round(state: RunState, ctx: Context) -> TraceRecord | None:
    """Work on the next material need once. Returns the trace record, or None if none remains."""
    exhausted: dict[str, str] = {}
    for p in state.plan.predicates:
        done = state.attempts.get(p.id, 0)
        base = ctx.specs[p.id]
        available = min(ctx.max_rounds, 1 + (1 if base.followup else 0))
        if done >= available:
            exhausted[p.id] = "round_limit" if done >= ctx.max_rounds else "no_targeted_followup"
        elif done and base.followup_reasons is not None and state.observations[p.id].reason not in base.followup_reasons:
            exhausted[p.id] = "followup_not_applicable"
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
    search = bm25_expanded_candidates if spec.retrieval_method == EXPANDED_BM25_METHOD else bm25_candidates
    if spec.retrieval_method == 'full_source_v1':
        from .retrieval import ScoreProvenance
        provenance = ScoreProvenance('full_source_v1',0,0,len(ctx.entries),0,())
        candidates = [Candidate(e.entry_id,e.revision_id,e.span,0,provenance) for e in ctx.entries]
    else:
        candidates = search(ctx.entries, spec.query)
    channel_report = None
    if spec.channel_queries:
        raw_channels = {"primary": candidates, **{name: search(ctx.entries, query) for name, query in spec.channel_queries}}
        verified, channel_exclusions = {}, []
        for name, items in raw_channels.items():
            verified[name] = []
            for candidate in items:
                problem = check_candidate(ctx.catalog, candidate)
                if problem is None and ctx.applicability is not None:
                    applicability = ctx.applicability(candidate)
                    if applicability is Applicability.NO_MATCH:
                        problem = Exclusion(candidate.entry_id, "inapplicable")
                    elif applicability is Applicability.UNKNOWN:
                        problem = Exclusion(candidate.entry_id, "applicability_unknown")
                if problem is None:
                    verified[name].append(candidate)
                elif problem not in channel_exclusions:
                    channel_exclusions.append(problem)
        selection = select_unique_with_mandatory(verified, set(raw_channels), spec.want, spec.role_priors)
        unique = list(selection.candidates)
        recovery = recover_packet(ctx.catalog, unique, want=spec.want, max_bytes=spec.max_bytes, applicability=ctx.applicability)
        recovery = RecoveryResult(recovery.packet, tuple(channel_exclusions) + recovery.exclusions,
                                  recovery.alternatives, recovery.unfilled)
        channel_report = ChannelReport(
            hits={name: len(items) for name, items in raw_channels.items()},
            selected=selection.covered,
            missing=tuple(sorted(name for name, items in raw_channels.items() if not items)),
            excluded=tuple(sorted(name for name, items in raw_channels.items() if items and not verified[name])),
            omitted=selection.omitted,
            delivered=tuple(sorted(name for name, items in verified.items() if any(
                item.entry_id == candidate.entry_id and not item.truncated
                for item in recovery.packet.items for candidate in items))),
            packet_omissions=tuple(item.entry_id for item in recovery.packet.omitted),
            packet_truncations=recovery.packet.truncated_entry_ids,
        )
    else:
        candidates.sort(key=lambda c: (-c.score, -spec.role_priors.get(c.entry_id, NEUTRAL_PRIOR), c.entry_id))
        recovery = recover_packet(
            ctx.catalog, candidates, want=spec.want, max_bytes=spec.max_bytes, applicability=ctx.applicability
        )
    ob_id = f"ob-{pid}"
    hit_count = len(candidates)
    has_no_hit_followup = (state.attempts.get(pid, 0) == 0 and base.followup is not None and ctx.max_rounds > 1
                           and (base.followup_reasons is None or 'no_retrieval_hit' in base.followup_reasons))
    if channel_report is not None and not hit_count and not has_no_hit_followup:
        # On the final available attempt, a verified mandatory-only packet is
        # still evidence to evaluate. Primary hit_count remains zero in the trace.
        hit_count = sum(channel_report.hits.values())
    state.ledger.record_retrieval(ob_id, hit_count=hit_count, result=recovery)
    ob = state.ledger.get(ob_id)
    if channel_report is not None and channel_report.omitted:
        observation = Observation(Outcome.UNKNOWN, "mandatory_channel_omitted")
    elif ob.status == "unresolved":  # nothing usable, or truncated/omitted: do not evaluate partial evidence
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
        retrieval_method=spec.retrieval_method,
        channels=channel_report,
    )
    if ctx.archive is not None:
        data = asdict(record)
        data["observation"]["outcome"] = record.observation.outcome.value
        ctx.archive.record_trace(state.request.request_id, record.sequence, data)
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
CONTRADICTION_QUERY = "contradiction conflicting conflict superseded revision override"


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
    planning_evidence: dict | None = None
    review: object | None = None


def _planning_packet(catalog: Catalog, entries: list[IndexEntry], question: str, applicability: Callable[[str], Applicability],
                     *, want: int, max_bytes: int, role_priors: dict[str, float]) -> dict:
    """Bounded lexical source context; not evidence of semantic coverage."""
    raw = {"primary": bm25_expanded_candidates(entries, question),
           "exception": bm25_expanded_candidates(entries, EXCEPTION_QUERY),
           "contradiction": bm25_expanded_candidates(entries, CONTRADICTION_QUERY)}
    usable, excluded = {}, []
    for name, candidates in raw.items():
        usable[name] = []
        for candidate in candidates:
            problem = check_candidate(catalog, candidate)
            if problem is None:
                verdict = applicability(candidate.revision_id)
                if verdict is not Applicability.MATCH:
                    problem = Exclusion(candidate.entry_id, "inapplicable" if verdict is Applicability.NO_MATCH else "applicability_unknown")
            if problem is None:
                usable[name].append(candidate)
            elif problem not in excluded:
                excluded.append(problem)
    selection = select_unique_with_mandatory(usable, set(raw), want, role_priors)
    recovered = recover_packet(catalog, list(selection.candidates), want=want, max_bytes=max_bytes,
                               applicability=lambda candidate: applicability(candidate.revision_id))
    return {"schema": "qjig.planning-evidence.v1", "assurance": "untrusted_incomplete",
            "packet": json.loads(serialize_packet(recovered.packet)),
            "channel_hits": {name: len(items) for name, items in raw.items()},
            "channel_selected": list(selection.covered),
            "channel_delivered": sorted(name for name, items in usable.items() if any(
                item.entry_id == candidate.entry_id and not item.truncated
                for item in recovered.packet.items for candidate in items)),
            "channel_missing": [name for name, items in raw.items() if not items],
            "channel_excluded": [name for name, items in raw.items() if items and not usable[name]],
            "channel_omitted": list(selection.omitted),
            "excluded": [asdict(item) for item in excluded + list(recovered.exclusions)]}


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
    planner_prompt_version: str = 'legacy_v1',
    judge_max_tokens: int | None = None,
    planner_max_price: dict | None = None,
    judge_max_price: dict | None = None,
    reviewer: tuple[str, str] | None = None,
    reviewer_max_tokens: int = 800,
    reviewer_max_price: dict | None = None,
    review_reservation_factory: ReservationFactory | None = None,
    require_complete_reservations: bool = False,
    reservation_factory: ReservationFactory | None = None, archive=None,
    evaluation_case_binding: dict | None = None,
    evaluation_assignment: dict | None = None,
    required_run_set: str | None = None,
    applicability_inputs: ApplicabilityInputs | None = None,
    role_priors: dict[str, float] | None = None,
    want: int = 3,
    max_bytes: int = 3000,
    full_source_evidence: bool = False,
) -> FreshRun:
    """Plan with a model, then answer each predicate through the canonical retrieval, recovery and judge path.

    Every decisive quote keeps its binding. An unresolved predicate stays unresolved. Because the plan is
    model-written, a material plan-coverage obligation is always opened; retrieval can offer exception
    passages for review but can never close it, so the result is a deferral that names the gap.
    """
    if planner_prompt_version not in PLANNER_PROMPT_VERSIONS:
        raise ContractError('unsupported planner prompt version')
    if evaluation_case_binding is not None and planner_prompt_version != 'legacy_v1':
        raise ContractError('evaluation configuration does not bind this planner prompt version')
    if type(full_source_evidence) is not bool or (full_source_evidence and evaluation_case_binding is None):
        raise ContractError('full source mode requires a checked evaluation case')
    if evaluation_case_binding is not None:
        import re
        b = evaluation_case_binding
        if (not isinstance(b, dict) or set(b) != {'case_id', 'design_sha256', 'case_sha256', 'reference_sha256'}
                or not isinstance(b['case_id'], str) or not b['case_id'].strip()
                or any(not isinstance(b[k], str) or not re.fullmatch(r'[0-9a-f]{64}', b[k])
                       for k in ('design_sha256', 'case_sha256', 'reference_sha256'))):
            raise ContractError('invalid evaluation case binding')
        if archive is None:
            raise ContractError('evaluation case binding requires an archive')
    if evaluation_assignment is not None:
        from .evaluation_budget import validate_assignment_binding
        validate_assignment_binding(evaluation_assignment)
        if evaluation_case_binding is None or required_run_set is None or ledger._goal_budget is None:
            raise ContractError('assignment requires a checked case and goal run set')
    if required_run_set is not None and not require_complete_reservations:
        raise ContractError('assignment requires complete fresh preflight')
    _check_role_priors({} if role_priors is None else role_priors)
    if type(require_complete_reservations) is not bool or (require_complete_reservations and ledger._goal_budget is None):
        raise ContractError('complete fresh preflight requires a goal ledger')
    review_set = None
    fresh_set = None
    # Freeze and validate both limits before archive writes or provider calls.
    def freeze_price(value):
        if value is None:
            return None
        return dict(ProviderRequest('', '', '', '', 1, max_price=value).max_price)
    planner_max_price, judge_max_price, reviewer_max_price = freeze_price(planner_max_price), freeze_price(judge_max_price), freeze_price(reviewer_max_price)
    if reviewer is not None:
        if (not isinstance(reviewer, tuple) or len(reviewer) != 2 or
                any(not isinstance(value, str) or not value.strip() for value in reviewer) or
                type(reviewer_max_tokens) is not int or reviewer_max_tokens < 1 or
                archive is None or applicability_inputs is None):
            raise ContractError("configured review requires reviewer identity, archive and applicability inputs")
        if ledger._goal_budget is not None:
            from .program_review import PlanReviewOutcome
            from decimal import Decimal
            from .budgets import _valid_cost
            from .providers import CallReservation, _ceiling_token_cost, fresh_work_binding
            try:
                if review_reservation_factory is None:
                    raise ContractError('review reservation is required')
                probe = ProviderRequest('plan_review', reviewer[0], reviewer[1], '', reviewer_max_tokens, max_price=reviewer_max_price)
                held = review_reservation_factory(probe)
                if (not isinstance(held, CallReservation) or held.request_sha256 != probe.input_sha256()
                        or held.required_id is None or held.work_binding_sha256 is None
                        or not _valid_cost(held.cost_usd)
                        or Decimal(str(held.cost_usd)) < _ceiling_token_cost(probe, held.input_tokens)
                        or held.work_binding_sha256 != fresh_work_binding(probe, held.input_tokens, held.pricing_sha256)):
                    raise ContractError('review reservation is not bound')
                review_set = ledger._goal_budget.check_required_work(held.required_id, request_id=request.request_id,
                    partition=ledger._partition, stage=probe.stage, provider=probe.provider, model=probe.model,
                    tokens=held.input_tokens + probe.max_tokens, cost_usd=held.cost_usd,
                    work_binding_sha256=held.work_binding_sha256)
            except (ContractError, BudgetExceeded):
                unavailable = PlanReviewOutcome('unavailable', None, None, 'review_preflight_unavailable')
                return FreshRun('deferred', ('plan_coverage_unestablished', 'review_preflight_unavailable'),
                                'review_preflight_unavailable', None, None, None, {}, {}, (), None, unavailable)
    if ledger._goal_budget is not None and (reviewer is not None or require_complete_reservations):
        from .fresh_preflight import check_fresh_stage_slots
        from .plans import MAX_PREDICATES
        from .program_review import PlanReviewOutcome
        try:
            probes = [ProviderRequest('planner', planner[0], planner[1], '',
                                      planner_max_tokens if planner_max_tokens is not None else PLANNER_MAX_TOKENS,
                                      max_price=planner_max_price)]
            probes += [ProviderRequest(stage, judge[0], judge[1], '',
                                       judge_max_tokens if judge_max_tokens is not None else JUDGE_MAX_TOKENS,
                                       max_price=judge_max_price) for stage in ('judge_positive', 'judge_negative')]
            sets = {check_fresh_stage_slots(ledger._goal_budget, request_id=request.request_id, partition=ledger._partition,
                                           request=probe, reservation_factory=reservation_factory,
                                           count=1 if probe.stage == 'planner' else MAX_PREDICATES * MAX_ROUNDS)
                    for probe in probes}
            if review_set is not None:
                sets.add(review_set)
            if len(sets) != 1:
                raise ContractError('fresh stages span different frozen sets')
            fresh_set = sets.pop()
            if required_run_set is not None and fresh_set != required_run_set:
                raise ContractError('fresh reservation set differs from assignment')
        except (ContractError, BudgetExceeded, TypeError, IndexError):
            unavailable = PlanReviewOutcome('unavailable', None, None, 'fresh_preflight_unavailable') if reviewer else None
            return FreshRun('deferred', ('plan_coverage_unestablished', 'fresh_preflight_unavailable'),
                            'fresh_preflight_unavailable', None, None, None, {}, {}, (), None, unavailable)
    revision_ids = sorted({entry.span.revision_id for entry in entries})
    entity_date = {revision_id: revision_applicability(revision_id) for revision_id in revision_ids}
    if any(not isinstance(value, Applicability) for value in entity_date.values()):
        raise ContractError("revision applicability must be an Applicability verdict")
    scopes_by_revision = {row[0]: row[1] for row in catalog.metadata_rows()}
    scopes = {revision_id: scopes_by_revision.get(revision_id) for revision_id in revision_ids}
    scope_verdicts = {key: scope_applicability(request.scope, value) for key, value in scopes.items()}
    if applicability_inputs is not None:
        if not isinstance(applicability_inputs, ApplicabilityInputs):
            raise ContractError("invalid applicability inputs")
        if any(applicability_inputs.verdict(key) is not value for key, value in entity_date.items()):
            raise ContractError("applicability inputs do not match recorded verdicts")
        for member in applicability_inputs.collection.members:
            if member.revision_id in scopes and scopes[member.revision_id] is not None and scopes[member.revision_id] != member.scope:
                raise ContractError("applicability scope differs from catalog metadata")
    applicability = {key: combine_applicability(entity_date[key], scope_verdicts[key]) for key in revision_ids}
    def bound_applicability(revision_id: str) -> Applicability:
        return applicability.get(revision_id, Applicability.UNKNOWN)
    if full_source_evidence:
        from .evaluation import _full_source_entries, _full_source_packet
        if entries != _full_source_entries(catalog.get_revision(key) for key in revision_ids):
            raise ContractError('full source entries differ from pinned revisions')
        if any(bound_applicability(key) is not Applicability.MATCH for key in revision_ids):
            raise ContractError('full source applicability is not established')
        packet = _full_source_packet(entries,max_bytes)
        planning_evidence = {'schema':'qjig.planning-evidence.v1','assurance':'untrusted_incomplete',
                             'packet':json.loads(serialize_packet(packet)),'method':'full_source_v1'}
    else:
        planning_evidence = _planning_packet(catalog, entries, request.question, bound_applicability,
                                             want=want, max_bytes=max_bytes, role_priors=role_priors or {})
    if archive is not None:
        # Bind the exact verdicts, effective settings and corpus before any planner call.
        archive.record_context({
            "schema": "qjig.fresh-context.v1", "request": request.to_dict(),
            **({'planner_prompt_version': planner_prompt_version} if planner_prompt_version != 'legacy_v1' else {}),
            **({"evaluation_case_binding": evaluation_case_binding} if evaluation_case_binding is not None else {}),
            **({"evaluation_assignment": evaluation_assignment} if evaluation_assignment is not None else {}),
            "budget": ledger.budget.to_dict() if ledger.budget else None,
            "planner": {"provider": planner[0], "model": planner[1], "max_tokens": planner_max_tokens if planner_max_tokens is not None else PLANNER_MAX_TOKENS, **({"max_price": planner_max_price} if planner_max_price is not None else {})},
            "judge": {"provider": judge[0], "model": judge[1], "max_tokens": judge_max_tokens if judge_max_tokens is not None else JUDGE_MAX_TOKENS, **({"max_price": judge_max_price} if judge_max_price is not None else {})},
            "transport": transport.label, "want": want, "max_bytes": max_bytes, "retrieval_method": "full_source_v1" if full_source_evidence else EXPANDED_BM25_METHOD,
            "followup_policy": "none_full_source_v1" if full_source_evidence else "request_question_on_no_primary_hit_v2",
            "reservation_factory_configured": reservation_factory is not None, "role_priors": role_priors or {},
            "corpus": {key: value.value for key, value in applicability.items()},
            "scope_policy": "exact_nonempty_v1", "source_scopes": scopes,
            "scope_verdicts": {key: value.value for key, value in scope_verdicts.items()},
            "entity_date_verdicts": {key: value.value for key, value in entity_date.items()},
            "applicability_provenance": "recorded_inputs" if applicability_inputs is not None else "verdict_only",
            "applicability_inputs": applicability_inputs.to_dict() if applicability_inputs is not None else None,
            "planning_evidence": planning_evidence,
            **({'fresh_run_set': fresh_set} if fresh_set is not None else {}),
            **({"reviewer": {"provider": reviewer[0], "model": reviewer[1], "max_tokens": reviewer_max_tokens,
                             "max_price": reviewer_max_price, "prompt_version": "request_id_redacted_v2"}} if reviewer is not None else {}),
        })
        for revision_id in revision_ids:
            archive.add_revision(catalog.get_revision(revision_id))
    kw = {} if planner_max_tokens is None else {"max_tokens": planner_max_tokens}
    prior_intents = {e.call_id for e in ledger._journal.events(request.request_id) if e.kind == 'intent'}
    def planner_failure(failure):
        if archive is not None:
            attempts = [e.call_id for e in ledger._journal.events(request.request_id)
                        if e.kind == 'intent' and e.call_id not in prior_intents]
            archive.record_run_result(request.request_id, {'schema': 'qjig.fresh-failure.v1',
                'request_id': request.request_id, 'stage': 'planner', 'status': 'deferred',
                'failure': failure, 'call_ids': attempts,
                'reconciliation_required': bool(ledger._journal.pending(request.request_id))})
        return FreshRun("deferred", (f"plan_unavailable:{failure}",), failure, None, None, None, {}, {}, (), planning_evidence)
    try:
        outcome = request_fresh_plan(
            ledger, transport, request, corpus_revision_ids=sorted({e.span.revision_id for e in entries}),
            provider=planner[0], model=planner[1], reservation_factory=reservation_factory, archive=archive,
            planning_evidence=planning_evidence, max_price=planner_max_price, prompt_version=planner_prompt_version, **kw,
        )
    except (BudgetExceeded, ProviderUnavailable, UncertainOutcome, ReconciliationRequired) as exc:
        failure = {BudgetExceeded: "budget_exceeded", ProviderUnavailable: "provider_unavailable",
                   UncertainOutcome: "uncertain_outcome", ReconciliationRequired: "reconciliation_required"}[type(exc)]
        return planner_failure(failure)
    if not outcome.ok:
        return planner_failure(outcome.failure)

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
                applicability=bound_applicability, reservation_factory=reservation_factory, archive=archive, max_price=judge_max_price, **jkw,
            )
            halted = any(side.failure in ("uncertain_outcome", "reconciliation_required")
                         for side in (result.positive, result.negative))
            judgments[pid] = result
            used = tuple(r for r in (result.positive.quote_ref, result.negative.quote_ref) if r is not None)
            refs[pid] = used
            return EvalResult(result.outcome, result.observation.reason, tuple(dict.fromkeys(r.entry_id for r in used)))

        return evaluate

    check = lambda c: bound_applicability(c.revision_id)  # noqa: E731
    specs = {}
    for p in plan.predicates:
        evaluator = make_evaluator(p.question, p.id)
        common = {"retrieval_method": 'full_source_v1' if full_source_evidence else EXPANDED_BM25_METHOD,
                  "channel_queries": () if full_source_evidence else (("exception", EXCEPTION_QUERY), ("contradiction", CONTRADICTION_QUERY)),
                  "role_priors": role_priors or {}}
        packet_want = len(entries) if full_source_evidence else want
        followup = (NeedSpec(request.question, packet_want, max_bytes, evaluator, **common)
                    if not full_source_evidence and request.question.strip() != p.question.strip() else None)
        specs[p.id] = NeedSpec(p.question, packet_want, max_bytes, evaluator, followup=followup,
                               followup_reasons=("no_retrieval_hit",), **common)
    obligations = ObligationLedger()
    for p in plan.predicates:
        obligations.open(Obligation(f"ob-{p.id}", "predicate_evidence", p.id, p.question, material=True))
    obligations.open(Obligation(COVERAGE_ID, "exception", "__plan__", "model-written plan completeness is not established", material=True))
    exc = recover_packet(catalog, bm25_candidates(entries, EXCEPTION_QUERY), want=want, max_bytes=max_bytes, applicability=check)
    obligations.record_retrieval(COVERAGE_ID, hit_count=len(bm25_candidates(entries, EXCEPTION_QUERY)), result=exc)

    state = RunState(request, plan, obligations)
    ctx = Context(catalog, entries, check, specs, archive=archive)
    summary = run_until_done(state, ctx)
    reasons = ("plan_coverage_unestablished",) + tuple(r for r in summary.stop.reasons if r != "plan_coverage_unestablished")
    review = None
    if reviewer is not None:
        from .packets import EvidencePacket, Omission, PacketItem
        from .planner import _planner_prompt, corpus_manifest_sha256
        from .program_review import PlanReviewOutcome, review_plan
        from .spans import Span
        import hashlib
        if halted:
            review = PlanReviewOutcome('unavailable', None, None, 'reconciliation_required')
        else:
            try:
                raw_packet = planning_evidence['packet']
                items = tuple(PacketItem(item['entry_id'], Span(item['revision_id'], item['text_sha256'], item['start'], item['end'], item['text']),
                                         item['truncated'], item['original_end']) for item in raw_packet['items'])
                omitted = tuple(Omission(item['entry_id'], item['reason']) for item in raw_packet['omitted'])
                packet = EvidencePacket(items, omitted, tuple(item.entry_id for item in items if item.truncated),
                                        raw_packet['limit'], len(json.dumps(raw_packet, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')))
                member_rows = {row['revision_id']: {key: value for key, value in row.items() if key != 'revision_id'}
                               for row in applicability_inputs.to_dict()['members']}
                planner_prompt = _planner_prompt(request, corpus_manifest_sha256(revision_ids), planning_evidence,
                                                 prompt_version=planner_prompt_version)
                review_binding = {'request': request.to_dict(), 'plan': {'origin': plan.origin,
                                  'predicates': [{'id': p.id, 'question': p.question, 'depends_on': list(p.depends_on),
                                                  **({'exact_operator': p.exact_operator} if p.exact_operator is not None else {})}
                                                 for p in plan.predicates], 'expression': plan.expression},
                                  'corpus_revision_ids': revision_ids, 'source_metadata': {ident: member_rows[ident] for ident in revision_ids},
                                  'as_of': applicability_inputs.as_of, 'entities': sorted(applicability_inputs.request_entities),
                                  'historical_as_known': applicability_inputs.historical_as_known,
                                  'planner': {'provider': planner[0], 'model': planner[1],
                                              'prompt_sha256': hashlib.sha256(planner_prompt.encode('utf-8')).hexdigest(),
                                              'config': {'max_tokens': planner_max_tokens if planner_max_tokens is not None else PLANNER_MAX_TOKENS,
                                                         'max_price': planner_max_price}}}
                review = review_plan(catalog, ledger, transport, review_binding, packet, provider=reviewer[0], model=reviewer[1],
                                     archive=archive, max_tokens=reviewer_max_tokens, max_price=reviewer_max_price,
                                     reservation_factory=review_reservation_factory)
            except (ContractError, KeyError, TypeError, ValueError):
                review = PlanReviewOutcome('unavailable', None, None, 'review_context_or_storage_error')
    if archive is not None:
        archive.record_run_result(request.request_id, {
            "schema": "qjig.fresh-result.v1", "request_id": request.request_id,
            "status": "deferred", "reasons": list(reasons), "expression": plan.expression,
            "observations": {key: {"outcome": value.outcome.value, "reason": value.reason}
                             for key, value in state.observations.items()},
            "trace_count": len(state.trace), "blocking_obligations": list(summary.stop.blocking_obligations),
            **({'review': {'status': review.status, 'failure': review.failure, 'call_id': review.call_id,
                           'review_id': review.record['sha256'] if review.record is not None else None,
                           'draft_id': review.draft_id}}
               if review is not None else {}),
        })
    return FreshRun(
        "deferred", reasons, None, outcome.binding, state, summary, judgments, refs,
        tuple(i.entry_id for i in exc.packet.items), planning_evidence, review,
    )
