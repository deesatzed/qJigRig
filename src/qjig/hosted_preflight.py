"""Account and price observations for a reserved hosted attempt.

This is not an authorization capability and never invokes a model. It must not
be used to bypass the hosted dispatch guard while billing assurance is unknown.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .budgets import BudgetExceeded, BudgetLedger
from .contracts import ContractError
from .providers import (CallReservation, ProviderRequest, check_current_endpoint_cost,
                        fresh_work_binding)


def prepare_hosted_attempt(ledger: BudgetLedger, request: ProviderRequest, reservation: CallReservation,
                           *, env_path: Path, max_age_seconds: int, clock=None) -> dict:
    """Refresh account and pricing for a pre-reserved physical call, without sending it."""
    from .account_client import refresh_account_constraints
    from .pricing import fetch_endpoint_snapshot
    if (not isinstance(ledger, BudgetLedger) or ledger._goal_budget is None
            or not ledger._goal_budget._account_bound or not isinstance(request, ProviderRequest)
            or not isinstance(reservation, CallReservation) or reservation.required_id is None
            or reservation.work_binding_sha256 is None or request.max_price is None
            or reservation.request_sha256 != request.input_sha256()
            or reservation.work_binding_sha256 != fresh_work_binding(request, reservation.input_tokens,
                                                                       reservation.pricing_sha256)):
        raise ContractError('hosted attempt requires an account-bound goal and reserved work')
    goal = ledger._goal_budget
    if goal.audit_journal(ledger._journal)['status'] != 'verified':
        raise BudgetExceeded('accounting', 'goal and journal must be reconciled before preflight')
    run_set = goal.check_required_work(reservation.required_id, request_id=ledger._request_id,
        partition=ledger._partition, stage=request.stage, provider=request.provider, model=request.model,
        tokens=reservation.input_tokens + request.max_tokens, cost_usd=reservation.cost_usd,
        work_binding_sha256=reservation.work_binding_sha256)
    goal.bind_hosted_journal(ledger._journal)
    refresh_account_constraints(goal, Path(env_path))
    goal._check_capacity(ledger._request_id, ledger._partition, 0, 0, Decimal(0))
    snapshot = fetch_endpoint_snapshot(request.model)
    now = clock() if clock is not None else datetime.now(timezone.utc)
    price = check_current_endpoint_cost(request, reservation, snapshot=snapshot, now=now,
                                        max_age_seconds=max_age_seconds)
    if goal.audit_journal(ledger._journal)['status'] != 'verified':
        raise BudgetExceeded('accounting', 'goal and journal changed during preflight')
    candidate=(estimate_candidate_hosted_attempt(request,input_tokens=reservation.input_tokens,snapshot=snapshot,
                                                  now=now,max_age_seconds=max_age_seconds) if request.route is not None else None)
    return {'run_set':run_set, 'pricing':price, 'candidate_pricing':candidate, 'billing_assurance':'unknown',
            'hosted_authorized':False}


def estimate_candidate_hosted_attempt(request: ProviderRequest, *, input_tokens: int, snapshot: dict,
                                      now: datetime, max_age_seconds: int) -> dict:
    """Bind a non-authorizing alternative token-cost calculation to an exact routed body.

    Catalog prices, provider routing, input framing and all non-token charges remain
    assertions or unknown; this is not a CallReservation or dispatch capability.
    """
    from .pricing import candidate_provider_pricing, candidate_token_price_bound
    from .providers import estimate_hosted_input_tokens, openrouter_wire_payload_v5
    if (not isinstance(request,ProviderRequest) or request.provider!='openrouter' or request.route is None
            or request.max_price is None or type(input_tokens) is not int
            or input_tokens < estimate_hosted_input_tokens(request.prompt)):
        raise ContractError('candidate estimate requires a bounded routed request')
    candidate=candidate_provider_pricing(snapshot,provider_slug=request.route,now=now,max_age_seconds=max_age_seconds)
    model=candidate['model']
    bound=candidate_token_price_bound(model,input_tokens=input_tokens,output_tokens=request.max_tokens,
                                      max_price=dict(request.max_price))
    encoded=json.dumps(model,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    wire=openrouter_wire_payload_v5(request).encode('utf-8')
    return {'schema':'qjig.candidate-hosted-cost.v1','request_sha256':request.input_sha256(),
            'wire_payload_sha256':hashlib.sha256(wire).hexdigest(),'pricing_sha256':hashlib.sha256(encoded).hexdigest(),
            'route':request.route,'route_count':candidate['route_count'],'input_tokens':input_tokens,
            'output_tokens':request.max_tokens,'cost_usd':str(bound['cost_usd']),'observed_at':snapshot['observed_at'],
            'input_assurance':'estimated_not_verified','pricing_assurance':'provider_catalog_assertion',
            'billing_assurance':'unknown','hosted_authorized':False}
