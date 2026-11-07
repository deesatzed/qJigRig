"""Separate, explicitly requested paired-judge escalation; never replaces the original."""
from dataclasses import dataclass
import hashlib
from typing import Callable

from .applicability import Applicability
from .budgets import BudgetLedger
from .contracts import ContractError
from .judge import JUDGE_MAX_TOKENS, SIDE_SCHEMA, JudgeResult, SideResult, _combine_sides, _side_from_value, build_side_prompts, judge_predicate, snapshot_judge_context
from .logic import Support
from .packets import EvidencePacket
from .providers import ReservationFactory, Transport, _validate

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
    if len(calls) != 2:
        raise ContractError('standalone receipts are incomplete')
    recovered = []
    for call, receipt in zip(calls, ledger.judge_receipt_payloads(tuple(call[0] for call in calls))):
        status = receipt.get('validation')
        raw, code = receipt.get('raw_response'), receipt.get('http_status')
        if (not isinstance(raw, str) or type(code) is not int or
                hashlib.sha256(raw.encode('utf-8')).hexdigest() != receipt.get('raw_sha256')):
            raise ContractError('standalone raw response binding unavailable')
        if status == 'ok':
            value = receipt.get('validated_value')
            parsed, failure = _validate(raw, SIDE_SCHEMA)
            if not 200 <= code < 300 or failure or parsed != value:
                raise ContractError('standalone validated result differs from raw response')
            recovered.append(_side_from_value(parsed, call[0]))
        elif isinstance(status, str) and status:
            if status == 'http_error':
                if 200 <= code < 300:
                    raise ContractError('standalone HTTP failure differs from response')
            else:
                _, failure = _validate(raw, SIDE_SCHEMA)
                if not 200 <= code < 300 or failure != status:
                    raise ContractError('standalone failure differs from raw response')
            recovered.append(SideResult(Support.UNKNOWN, f'provider_{status}', '', status, call[0]))
        else:
            raise ContractError('standalone validation unavailable')
    if _combine_sides(recovered[0], recovered[1], packet, applicability) != standalone:
        raise ContractError('standalone result differs from recorded sides')
    result = judge_predicate(ledger, transport, question, packet, provider=provider, model=HY4_MODEL,
                             applicability=applicability, max_tokens=max_tokens,
                             reservation_factory=reservation_factory, stage_prefix='escalation')
    return EscalationResult(standalone, result, reason, provider, HY4_MODEL, transport.label)
