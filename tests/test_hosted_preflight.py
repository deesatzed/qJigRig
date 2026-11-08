"""Synthetic account and catalog inputs; no model calls."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget, ContractError
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from qjig.pricing import model_from_endpoint_snapshot
from qjig.providers import ProviderRequest, fresh_work_binding, make_call_reservation


def test_preflight_requires_account_and_current_prices_for_reserved_work(tmp_path, monkeypatch):
    from qjig.hosted_preflight import prepare_hosted_attempt
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    account = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
               {'data': {'total_credits': 1, 'total_usage': 0}})
    snapshot = {'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog','observed_at':now.isoformat(),
                'endpoints':[{'model_id':'tencent/hy4','provider_name':'Tencent','context_length':100000,
                              'max_completion_tokens':1000,
                              'pricing':{'prompt':'0.000001','completion':'0.000002','discount':0}}]}
    monkeypatch.setattr('qjig.account_client.fetch_account_snapshot', lambda *a, **kw: account)
    monkeypatch.setattr('qjig.pricing.fetch_endpoint_snapshot', lambda model: snapshot)
    request = ProviderRequest('planner','openrouter','tencent/hy4','test question',100,
                              max_price={'prompt':2,'completion':4})
    model = model_from_endpoint_snapshot(snapshot,now=now,max_age_seconds=30)
    raw = make_call_reservation(request,model,input_tokens=5000,input_bound_provenance='synthetic estimate')
    binding = fresh_work_binding(request,raw.input_tokens,raw.pricing_sha256)
    bound = replace(raw,required_id='work-one',work_binding_sha256=binding)
    limit = Budget(5, 10000, 0.5)
    with GoalBudget.open(tmp_path/'goal.sqlite', total=limit, per_request=limit,
                         allocations={'smoke':limit},account_snapshot=account) as goal, Journal.open(tmp_path/'journal.sqlite') as journal:
        goal.reserve_run_set('run-one',[{'work_id':'work-one','request_id':'r','partition':'smoke',
            'tokens':5100,'cost_usd':bound.cost_usd,'stage':'planner','provider':'openrouter',
            'model':'tencent/hy4','work_binding_sha256':binding}])
        ledger = BudgetLedger(limit,journal,'r',goal_budget=goal,partition='smoke')
        result = prepare_hosted_attempt(ledger,request,bound,env_path=tmp_path/'env',max_age_seconds=30,clock=lambda:now)
        assert result['run_set'] == 'run-one'
        assert result['billing_assurance'] == 'unknown'
        assert journal.events('r') == []
        assert goal._con.execute('SELECT count(*) FROM account_restrictions').fetchone()[0] == 1
        raised = {**snapshot, 'endpoints':[{**snapshot['endpoints'][0],
                  'pricing':{'prompt':'0.1','completion':'0.2','discount':0}}]}
        monkeypatch.setattr('qjig.pricing.fetch_endpoint_snapshot', lambda model: raised)
        with pytest.raises(ContractError, match='reservation'):
            prepare_hosted_attempt(ledger,request,bound,env_path=tmp_path/'env',max_age_seconds=30,clock=lambda:now)
        assert journal.events('r') == []
