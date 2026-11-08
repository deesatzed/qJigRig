"""Account and price observations for a reserved hosted attempt.

This is not an authorization capability and never invokes a model. It must not
be used to bypass the hosted dispatch guard while billing assurance is unknown.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .budgets import BudgetExceeded, BudgetLedger
from .contracts import ContractError
from .providers import (CallReservation, ProviderRequest, check_current_endpoint_cost,
                        fresh_work_binding)



def _verify_hosted_accounting_binding(goal, journal, env_path: Path) -> None:
    """Require the v2 configured ledger and journal; this cannot detect coordinated rollback."""
    anchor_dir=Path(env_path).resolve().parent/'.local'
    directory_anchor=anchor_dir/'qjig-active-goal-directory'
    initialized_anchor=anchor_dir/'qjig-active-goal-initialized'
    identity_anchor=anchor_dir/'qjig-active-goal-identity'
    if anchor_dir.is_symlink() or any(path.is_symlink() for path in (directory_anchor,initialized_anchor,identity_anchor)):
        raise ContractError('unsafe goal accounting binding')
    try:
        directory=directory_anchor.read_text(encoding='utf-8')
        if (not directory or not Path(directory).is_absolute() or Path(directory).is_symlink()
                or str(Path(directory).resolve())!=directory or initialized_anchor.read_text(encoding='utf-8')!=directory):
            raise ContractError('goal directory binding differs')
        identity=identity_anchor.read_text(encoding='ascii')
        row=goal._con.execute('SELECT identity FROM local_ledger_identity WHERE id=1').fetchone()
        if not re.fullmatch(r'[0-9a-f]{64}',identity) or row is None or row[0]!=identity:
            raise ContractError('goal identity binding differs')
        def filename(con):
            path=next((entry[2] for entry in con.execute('PRAGMA database_list') if entry[1]=='main'),None)
            if not path:
                raise ContractError('persistent accounting database required')
            return Path(path).resolve()
        if filename(goal._con)!=Path(directory)/'goal.sqlite':
            raise ContractError('goal directory binding differs')
        if filename(journal._con)!=Path(directory)/'journal.sqlite':
            raise ContractError('journal directory binding differs')
    except (OSError,UnicodeError,sqlite3.Error) as exc:
        raise ContractError('goal accounting binding unavailable') from exc

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
    _verify_hosted_accounting_binding(goal,ledger._journal,Path(env_path))
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
