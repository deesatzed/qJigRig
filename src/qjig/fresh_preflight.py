"""Build conservative fresh-run slot allocations from explicit caller bounds.

This enumerates work; it does not authenticate prices or input-token bounds,
cover retries, review or escalation, or authorize provider dispatch.
"""
from __future__ import annotations

import hashlib
import json

from .acquisition import MAX_ROUNDS
from .contracts import ContractError
from .plans import MAX_PREDICATES
from .providers import ProviderRequest, make_call_reservation


def fresh_run_allocations(*, request_id: str, partition: str, provider: str,
                          planner_model: dict, judge_model: dict,
                          planner_input: int, planner_output: int,
                          judge_input: int, judge_output: int,
                          planner_price: dict, judge_price: dict) -> list[dict]:
    """Enumerate one planner and a pair of judges per possible predicate/round.

    The upper bound intentionally holds slots even when a no-hit round makes no
    judge calls. Prices and token counts supplied here are assertions only.
    """
    if any(not isinstance(v, str) or not v.strip() for v in (request_id, partition, provider)):
        raise ContractError('invalid fresh allocation identity')
    slots = [('planner', 0, planner_model, planner_input, planner_output, planner_price)]
    for index in range(MAX_PREDICATES * MAX_ROUNDS):
        slots.extend((stage, index, judge_model, judge_input, judge_output, judge_price)
                     for stage in ('judge_positive', 'judge_negative'))
    result = []
    for stage, index, model, input_tokens, output_tokens, price in slots:
        if not isinstance(model, dict) or not isinstance(model.get('id'), str) or not model['id']:
            raise ContractError('missing model identity')
        if price is None:
            raise ContractError('routing price ceiling required')
        request = ProviderRequest(stage, provider, model['id'], '', output_tokens, max_price=price)
        bound = make_call_reservation(request, model, input_tokens=input_tokens,
                                      input_bound_provenance='declared allocation bound; not verified')
        identity = json.dumps(['qjig.fresh-slot.v1', request_id, stage, index],
                              ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        result.append({'work_id': hashlib.sha256(identity).hexdigest(), 'request_id': request_id,
                       'partition': partition, 'tokens': input_tokens + output_tokens,
                       'cost_usd': bound.cost_usd, 'stage': stage, 'provider': provider, 'model': model['id']})
    return result
