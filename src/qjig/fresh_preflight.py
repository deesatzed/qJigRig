"""Build conservative fresh-run slot allocations from explicit caller bounds.

This enumerates work; it does not authenticate prices or input-token bounds,
cover retries or escalation, or authorize provider dispatch.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

from .acquisition import MAX_ROUNDS
from .contracts import ContractError
from .plans import MAX_PREDICATES
from .providers import CallReservation, ProviderRequest, _ceiling_token_cost, fresh_work_binding, make_call_reservation
from .budgets import _valid_cost


def _slot_id(request_id, partition, request, input_tokens, pricing_sha256, index):
    identity = ['qjig.fresh-slot.v3', request_id, partition, request.stage, index,
                request.provider, request.model, input_tokens, request.max_tokens,
                dict(request.max_price), pricing_sha256]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def fresh_run_allocations(*, request_id: str, partition: str, provider: str,
                          planner_model: dict, judge_model: dict,
                          planner_input: int, planner_output: int,
                          judge_input: int, judge_output: int,
                          planner_price: dict, judge_price: dict, reviewer: dict | None = None) -> list[dict]:
    """Enumerate one planner and a pair of judges per possible predicate/round.

    The upper bound intentionally holds slots even when a no-hit round makes no
    judge calls. Prices and token counts supplied here are assertions only.
    """
    if any(not isinstance(v, str) or not v.strip() for v in (request_id, partition, provider)):
        raise ContractError('invalid fresh allocation identity')
    slots = [('planner', 0, provider, planner_model, planner_input, planner_output, planner_price)]
    for index in range(MAX_PREDICATES * MAX_ROUNDS):
        slots.extend((stage, index, provider, judge_model, judge_input, judge_output, judge_price)
                     for stage in ('judge_positive', 'judge_negative'))
    if reviewer is not None:
        if (not isinstance(reviewer, dict) or set(reviewer) != {'provider', 'model', 'input_tokens', 'output_tokens', 'max_price'}
                or not isinstance(reviewer['provider'], str) or not reviewer['provider'].strip()):
            raise ContractError('invalid review allocation')
        slots.append(('plan_review', 0, reviewer['provider'], reviewer['model'], reviewer['input_tokens'],
                      reviewer['output_tokens'], reviewer['max_price']))
    result = []
    for stage, index, slot_provider, model, input_tokens, output_tokens, price in slots:
        if not isinstance(model, dict) or not isinstance(model.get('id'), str) or not model['id']:
            raise ContractError('missing model identity')
        if price is None:
            raise ContractError('routing price ceiling required')
        request = ProviderRequest(stage, slot_provider, model['id'], '', output_tokens, max_price=price)
        bound = make_call_reservation(request, model, input_tokens=input_tokens,
                                      input_bound_provenance='declared allocation bound; not verified')
        ident = _slot_id(request_id, partition, request, input_tokens, bound.pricing_sha256, index)
        result.append({'work_id': ident, 'request_id': request_id,
                       'partition': partition, 'tokens': input_tokens + output_tokens,
                       'cost_usd': bound.cost_usd, 'stage': stage, 'provider': slot_provider, 'model': model['id'],
                       'work_binding_sha256': fresh_work_binding(request, input_tokens, bound.pricing_sha256)})
    return result


def fresh_slot_reservation(goal, set_id: str, *, request_id: str, partition: str,
                           request: ProviderRequest, model: dict, input_tokens: int,
                           input_bound_provenance: str):
    """Select a persisted slot for one request; the ledger consumes it atomically.

    This does not establish the truth of the supplied model or input bound.
    """
    if not isinstance(request, ProviderRequest) or request.max_price is None:
        raise ContractError('capped provider request required')
    if request.stage not in ('planner', 'judge_positive', 'judge_negative', 'plan_review'):
        raise ContractError('unsupported fresh request stage')
    bound = make_call_reservation(request, model, input_tokens=input_tokens,
                                  input_bound_provenance=input_bound_provenance)
    count = 1 if request.stage in ('planner', 'plan_review') else MAX_PREDICATES * MAX_ROUNDS
    allowed = {_slot_id(request_id, partition, request, input_tokens, bound.pricing_sha256, index)
               for index in range(count)}
    ident = goal.select_required_work(set_id, request_id=request_id, partition=partition,
                                      stage=request.stage, provider=request.provider, model=request.model,
                                      tokens=input_tokens + request.max_tokens, cost_usd=bound.cost_usd,
                                      allowed_work_ids=allowed)
    return replace(bound, required_id=ident,
                   work_binding_sha256=fresh_work_binding(request, input_tokens, bound.pricing_sha256))


def check_fresh_stage_slots(goal, *, request_id: str, partition: str, request: ProviderRequest,
                            reservation_factory, count: int) -> str:
    """Verify all expected slots for one stage and return their common frozen set ID."""
    if reservation_factory is None or type(count) is not int or count < 1:
        raise ContractError('fresh stage reservations are unavailable')
    bound = reservation_factory(request)
    if (not isinstance(bound, CallReservation) or bound.request_sha256 != request.input_sha256()
            or bound.required_id is None or bound.work_binding_sha256 is None or not _valid_cost(bound.cost_usd)
            or Decimal(str(bound.cost_usd)) < _ceiling_token_cost(request, bound.input_tokens)
            or bound.work_binding_sha256 != fresh_work_binding(request, bound.input_tokens, bound.pricing_sha256)):
        raise ContractError('fresh stage reservation is not bound')
    set_ids = set()
    for index in range(count):
        ident = _slot_id(request_id, partition, request, bound.input_tokens, bound.pricing_sha256, index)
        set_ids.add(goal.check_required_work(ident, request_id=request_id, partition=partition, stage=request.stage,
                    provider=request.provider, model=request.model, tokens=bound.input_tokens + request.max_tokens,
                    cost_usd=bound.cost_usd, work_binding_sha256=bound.work_binding_sha256))
    if len(set_ids) != 1:
        raise ContractError('fresh stage slots span different frozen sets')
    return set_ids.pop()
