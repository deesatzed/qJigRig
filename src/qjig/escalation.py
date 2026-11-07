"""Separate, explicitly requested paired-judge escalation; never replaces the original."""
from dataclasses import dataclass
from typing import Callable

from .applicability import Applicability
from .budgets import BudgetLedger
from .contracts import ContractError
from .judge import JUDGE_MAX_TOKENS, JudgeResult, build_side_prompts, judge_predicate, snapshot_judge_context
from .packets import EvidencePacket
from .providers import ReservationFactory, Transport

HY4_MODEL = 'tencent/hy4'


@dataclass(frozen=True)
class EscalationResult:
    standalone: JudgeResult
    result: JudgeResult
    reason: str
    provider: str
    model: str
    transport: str


def escalate_predicate(standalone: JudgeResult, ledger: BudgetLedger, transport: Transport,
                       question: str, packet: EvidencePacket, *, reason: str, provider: str,
                       applicability: Callable[[str], Applicability] | None = None,
                       max_tokens: int = JUDGE_MAX_TOKENS,
                       reservation_factory: ReservationFactory | None = None) -> EscalationResult:
    """Run one explicitly identified escalation using the caller's shared ledger.

    Model identity is fixed, but a stand-in transport is still only a fixture.
    This result does not activate a plan, establish coverage, or select an outcome.
    """
    if not isinstance(standalone, JudgeResult) or not isinstance(reason, str) or not reason.strip():
        raise ContractError('standalone result and escalation reason are required')
    if not isinstance(provider, str) or not provider.strip():
        raise ContractError('escalation provider is required')
    prompts = build_side_prompts(question, packet)
    calls = tuple((side.call_id, prompt.stage, prompt.prompt) for side, prompt in zip((standalone.positive, standalone.negative), prompts) if side.call_id is not None)
    binding, applicability = snapshot_judge_context(packet, applicability)
    if not ledger.has_judge_calls(calls, binding):
        raise ContractError('standalone ledger binding differs from question or evidence packet')
    result = judge_predicate(ledger, transport, question, packet, provider=provider, model=HY4_MODEL,
                             applicability=applicability, max_tokens=max_tokens,
                             reservation_factory=reservation_factory, stage_prefix='escalation')
    return EscalationResult(standalone, result, reason, provider, HY4_MODEL, transport.label)
