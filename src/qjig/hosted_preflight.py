"""Account and price observations for a reserved hosted attempt.

This is not an authorization capability and never invokes a model. It must not
be used to bypass the hosted dispatch guard while billing assurance is unknown.
"""
from __future__ import annotations

from decimal import Decimal
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
    refresh_account_constraints(goal, Path(env_path))
    goal._check_capacity(ledger._request_id, ledger._partition, 0, 0, Decimal(0))
    snapshot = fetch_endpoint_snapshot(request.model)
    now = clock() if clock is not None else datetime.now(timezone.utc)
    price = check_current_endpoint_cost(request, reservation, snapshot=snapshot, now=now,
                                        max_age_seconds=max_age_seconds)
    if goal.audit_journal(ledger._journal)['status'] != 'verified':
        raise BudgetExceeded('accounting', 'goal and journal changed during preflight')
    return {'run_set':run_set, 'pricing':price, 'billing_assurance':'unknown',
            'hosted_authorized':False}
