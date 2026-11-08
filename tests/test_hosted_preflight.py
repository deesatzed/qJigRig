"""Synthetic account and catalog inputs; no model calls."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget, ContractError
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from qjig.pricing import model_from_endpoint_snapshot
from qjig.providers import ProviderRequest, fresh_work_binding, make_call_reservation


@pytest.mark.parametrize('route',[None,'tencent'])
def test_preflight_requires_account_and_current_prices_for_reserved_work(tmp_path, monkeypatch, route):
    from qjig.hosted_preflight import prepare_hosted_attempt
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    account = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
               {'data': {'total_credits': 1, 'total_usage': 0}})
    snapshot = {'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog','observed_at':now.isoformat(),
                'endpoints':[{'model_id':'tencent/hy4','provider_name':'Tencent','tag':'tencent/fp4','context_length':100000,
                              'max_completion_tokens':1000,
                              'pricing':{'prompt':'0.000001','completion':'0.000002','discount':0}}]}
    if route:
        snapshot['endpoints'].append({**snapshot['endpoints'][0],'tag':'other/fp4',
                                      'pricing':{'prompt':'0.1','completion':'0.2','discount':0}})
    monkeypatch.setattr('qjig.account_client.fetch_account_snapshot', lambda *a, **kw: account)
    monkeypatch.setattr('qjig.pricing.fetch_endpoint_snapshot', lambda model: snapshot)
    request = ProviderRequest('planner','openrouter','tencent/hy4','test question',100,
                              max_price={'prompt':2,'completion':4},route=route)
    if route:
        from qjig.pricing import candidate_provider_pricing
        model=candidate_provider_pricing(snapshot,provider_slug=route,now=now,max_age_seconds=30)['model']
    else:
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
        assert result['billing_assurance'] == 'unknown' and result['hosted_authorized'] is False
        if route:
            assert result['pricing']['route']==route and result['pricing']['route_count']==1
            assert result['candidate_pricing']['hosted_authorized'] is False
            assert result['candidate_pricing']['request_sha256']==request.input_sha256()
            assert Decimal(result['candidate_pricing']['cost_usd'])<=Decimal(str(result['pricing']['current_cost_usd']))

        assert journal.events('r') == []
        assert goal._con.execute('SELECT count(*) FROM account_restrictions').fetchone()[0] == 1
        with Journal.open(tmp_path/'other-journal.sqlite') as other:
            other_ledger=BudgetLedger(limit,other,'r',goal_budget=goal,partition='smoke')
            with pytest.raises(ContractError,match='journal.*binding'):
                prepare_hosted_attempt(other_ledger,request,bound,env_path=tmp_path/'env',max_age_seconds=30,clock=lambda:now)
        raised = {**snapshot, 'endpoints':[{**snapshot['endpoints'][0],
                  'pricing':{'prompt':'0.1','completion':'0.2','discount':0}}]}
        monkeypatch.setattr('qjig.pricing.fetch_endpoint_snapshot', lambda model: raised)
        with pytest.raises(ContractError, match='reservation'):
            prepare_hosted_attempt(ledger,request,bound,env_path=tmp_path/'env',max_age_seconds=30,clock=lambda:now)
        assert journal.events('r') == []


def test_hosted_journal_binding_survives_restart_and_rejects_memory(tmp_path):
    account=({'data':{'limit_remaining':1,'include_byok_in_limit':False,'is_free_tier':False}},
             {'data':{'total_credits':1,'total_usage':0}})
    limit=Budget(5,10000,0.5)
    path=tmp_path/'goal.sqlite'
    with GoalBudget.open(path,total=limit,per_request=limit,allocations={'smoke':limit},account_snapshot=account) as goal:
        with Journal.open(':memory:') as memory:
            with pytest.raises(ContractError,match='persistent journal'):
                goal.bind_hosted_journal(memory)
        with Journal.open(tmp_path/'first.sqlite') as first:
            goal.bind_hosted_journal(first)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            goal._con.execute("UPDATE hosted_journal_binding SET path='different'")
    with GoalBudget.resume_account_bound(path,total=limit,per_request=limit,allocations={'smoke':limit}) as goal:
        with Journal.open(tmp_path/'first.sqlite') as first:
            goal.bind_hosted_journal(first)
        with Journal.open(tmp_path/'second.sqlite') as second:
            with pytest.raises(ContractError,match='journal.*binding'):
                goal.bind_hosted_journal(second)


def test_candidate_nonadditive_cost_binds_exact_routed_request_without_authorizing():
    from qjig.hosted_preflight import estimate_candidate_hosted_attempt
    from qjig.providers import estimate_hosted_input_tokens
    now=datetime(2026,11,8,tzinfo=timezone.utc)
    def endpoint(tag,prompt):
        return {'model_id':'tencent/hy4','provider_name':'Synthetic','tag':tag,'context_length':100000,
                'max_completion_tokens':1000,'pricing':{'prompt':prompt,'completion':'0.000002',
                'input_cache_read':'0.0000003','discount':0}}
    snapshot={'model':'tencent/hy4','source':'openrouter_public_endpoint_catalog','observed_at':now.isoformat(),
              'endpoints':[endpoint('alpha/fp4','0.000001'),endpoint('alpha/fp8','0.000002'),endpoint('other/fp4','0.1')]}
    request=ProviderRequest('planner','openrouter','tencent/hy4','test question',100,
                            max_price={'prompt':3,'completion':4},route='alpha')
    bound=estimate_hosted_input_tokens(request.prompt)
    result=estimate_candidate_hosted_attempt(request,input_tokens=bound,snapshot=snapshot,now=now,max_age_seconds=60)
    assert result['request_sha256']==request.input_sha256() and result['route']=='alpha' and result['route_count']==2
    assert result['hosted_authorized'] is False and result['billing_assurance']=='unknown'
    assert len(result['wire_payload_sha256'])==64 and len(result['pricing_sha256'])==64
    with pytest.raises(ContractError):
        estimate_candidate_hosted_attempt(request,input_tokens=bound-1,snapshot=snapshot,now=now,max_age_seconds=60)
    with pytest.raises(ContractError):
        estimate_candidate_hosted_attempt(request,input_tokens=bound,snapshot=snapshot,now=now.replace(minute=2),max_age_seconds=60)
    altered={**snapshot,'endpoints':[endpoint('alpha/fp4','0.000001'),endpoint('alpha/fp8','0.000004'),endpoint('other/fp4','0.1')]}
    increased=estimate_candidate_hosted_attempt(request,input_tokens=bound,snapshot=altered,now=now,max_age_seconds=60)
    assert Decimal(increased['cost_usd'])>Decimal(result['cost_usd']) and increased['pricing_sha256']!=result['pricing_sha256']
    changed=ProviderRequest('planner','openrouter','tencent/hy4','changed question',100,max_price={'prompt':3,'completion':4},route='alpha')
    changed_result=estimate_candidate_hosted_attempt(changed,input_tokens=estimate_hosted_input_tokens(changed.prompt),
        snapshot=snapshot,now=now,max_age_seconds=60)
    assert changed_result['request_sha256']!=result['request_sha256'] and changed_result['wire_payload_sha256']!=result['wire_payload_sha256']
