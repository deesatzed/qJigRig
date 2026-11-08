"""Reserve one separately budgeted request-outcome-review stage; not hosted authorization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from .contracts import ContractError
from .providers import ProviderRequest, fresh_work_binding, make_call_reservation


def _slot_id(request_id, partition, request, input_tokens, pricing_sha256):
    data=['qjig.request-outcome-review-slot.v1',request_id,partition,request.provider,request.model,
          input_tokens,request.max_tokens,dict(request.max_price),pricing_sha256]
    if request.route is not None:
        data[0]='qjig.request-outcome-review-slot.v2'
        data.append(request.route)
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def outcome_review_allocation(*, request_id: str, partition: str, spec: dict) -> dict:
    if (any(not isinstance(x,str) or not x.strip() for x in (request_id,partition))
            or not isinstance(spec,dict)
            or set(spec) not in ({'provider','model','input_tokens','output_tokens','max_price'},
                                 {'provider','model','input_tokens','output_tokens','max_price','route'})
            or not isinstance(spec['provider'],str) or not spec['provider'].strip()
            or not isinstance(spec['model'],dict) or not isinstance(spec['model'].get('id'),str)
            or not spec['model']['id'].strip() or spec['max_price'] is None):
        raise ContractError('invalid outcome review allocation')
    pr=ProviderRequest('outcome_review',spec['provider'],spec['model']['id'],'',spec['output_tokens'],max_price=spec['max_price'],route=spec.get('route'))
    bound=make_call_reservation(pr,spec['model'],input_tokens=spec['input_tokens'],
                                input_bound_provenance='declared outcome review bound; not verified')
    return {'work_id':_slot_id(request_id,partition,pr,spec['input_tokens'],bound.pricing_sha256),
            'request_id':request_id,'partition':partition,'tokens':spec['input_tokens']+spec['output_tokens'],
            'cost_usd':bound.cost_usd,'stage':pr.stage,'provider':pr.provider,'model':pr.model,
            'work_binding_sha256':fresh_work_binding(pr,spec['input_tokens'],bound.pricing_sha256)}


def outcome_review_reservation(goal, set_id: str, *, request_id: str, partition: str,
                                request: ProviderRequest, spec: dict):
    if (not isinstance(spec,dict) or not isinstance(request,ProviderRequest) or request.stage!='outcome_review'
            or request.provider != spec.get('provider') or request.model != spec.get('model',{}).get('id')
            or request.max_tokens != spec.get('output_tokens') or request.max_price != spec.get('max_price')
            or request.route != spec.get('route')):
        raise ContractError('outcome review request differs from frozen work')
    slot=outcome_review_allocation(request_id=request_id,partition=partition,spec=spec)
    bound=make_call_reservation(request,spec['model'],input_tokens=spec['input_tokens'],
                                input_bound_provenance='declared outcome review bound; not verified')
    ident=goal.select_required_work(set_id,request_id=request_id,partition=partition,stage=request.stage,
        provider=request.provider,model=request.model,tokens=slot['tokens'],cost_usd=slot['cost_usd'],
        allowed_work_ids={slot['work_id']})
    return replace(bound,required_id=ident,work_binding_sha256=slot['work_binding_sha256'])
