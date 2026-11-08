"""Direct-run frozen slots from declared bounds; not a hosted-call authorization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal

from .budgets import _valid_cost
from .contracts import ContractError
from .providers import CallReservation, ProviderRequest, _ceiling_token_cost, fresh_work_binding, make_call_reservation


def _slot_id(request_id, partition, request, input_tokens, pricing_sha256):
    identity = ['qjig.direct-slot.v1', request_id, partition, request.stage, request.provider, request.model,
                input_tokens, request.max_tokens, dict(request.max_price), pricing_sha256]
    if request.route is not None:
        identity[0]='qjig.direct-slot.v2'
        identity.append(request.route)
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def direct_run_allocations(*, request_id: str, partition: str, provider: str, model: dict,
                           input_tokens: int, output_tokens: int, max_price: dict, followups: int, route: str | None = None) -> list[dict]:
    """Enumerate the initial call and optional final call using caller-asserted bounds."""
    if (any(not isinstance(v, str) or not v.strip() for v in (request_id, partition, provider))
            or not isinstance(model, dict) or not isinstance(model.get('id'), str) or not model['id'].strip()
            or max_price is None or type(followups) is not int or followups not in (0, 1)):
        raise ContractError('invalid direct allocation configuration')
    result = []
    for stage in ('direct_initial', 'direct_final')[:1 + followups]:
        request = ProviderRequest(stage, provider, model['id'], '', output_tokens, max_price=max_price,route=route)
        bound = make_call_reservation(request, model, input_tokens=input_tokens,
                                      input_bound_provenance='declared direct allocation; not verified')
        result.append({'work_id': _slot_id(request_id, partition, request, input_tokens, bound.pricing_sha256),
                       'request_id': request_id, 'partition': partition, 'tokens': input_tokens + output_tokens,
                       'cost_usd': bound.cost_usd, 'stage': stage, 'provider': provider, 'model': model['id'],
                       'work_binding_sha256': fresh_work_binding(request, input_tokens, bound.pricing_sha256)})
    return result


def direct_slot_reservation(goal, set_id: str, *, request_id: str, partition: str, request: ProviderRequest,
                            model: dict, input_tokens: int, input_bound_provenance: str) -> CallReservation:
    if not isinstance(request, ProviderRequest) or request.stage not in ('direct_initial', 'direct_final') or request.max_price is None:
        raise ContractError('capped direct request required')
    bound = make_call_reservation(request, model, input_tokens=input_tokens, input_bound_provenance=input_bound_provenance)
    ident = _slot_id(request_id, partition, request, input_tokens, bound.pricing_sha256)
    selected = goal.select_required_work(set_id, request_id=request_id, partition=partition, stage=request.stage,
                                         provider=request.provider, model=request.model,
                                         tokens=input_tokens + request.max_tokens, cost_usd=bound.cost_usd,
                                         allowed_work_ids={ident})
    return replace(bound, required_id=selected, work_binding_sha256=fresh_work_binding(request, input_tokens, bound.pricing_sha256))


def check_direct_slots(goal, *, request_id: str, partition: str, provider: str, model: str, output_tokens: int,
                       max_price: dict, followups: int, reservation_factory) -> str:
    """Check every stage is unconsumed and belongs to the same frozen run set."""
    if reservation_factory is None or max_price is None or type(followups) is not int or followups not in (0, 1):
        raise ContractError('direct reservations unavailable')
    sets = set()
    for stage in ('direct_initial', 'direct_final')[:1 + followups]:
        probe = ProviderRequest(stage, provider, model, '', output_tokens, max_price=max_price)
        bound = reservation_factory(probe)
        if (not isinstance(bound, CallReservation) or bound.request_sha256 != probe.input_sha256()
                or not _valid_cost(bound.cost_usd) or Decimal(str(bound.cost_usd)) < _ceiling_token_cost(probe, bound.input_tokens)
                or bound.work_binding_sha256 != fresh_work_binding(probe, bound.input_tokens, bound.pricing_sha256)
                or bound.required_id != _slot_id(request_id, partition, probe, bound.input_tokens, bound.pricing_sha256)):
            raise ContractError('direct reservation does not match stage')
        sets.add(goal.check_required_work(bound.required_id, request_id=request_id, partition=partition,
                                         stage=stage, provider=provider, model=model,
                                         tokens=bound.input_tokens + output_tokens, cost_usd=bound.cost_usd,
                                         work_binding_sha256=bound.work_binding_sha256))
    if len(sets) != 1:
        raise ContractError('direct slots span different frozen sets')
    return sets.pop()
