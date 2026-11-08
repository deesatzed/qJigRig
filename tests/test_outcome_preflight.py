"""Distinct work slots for separately budgeted request-outcome review."""
import json
import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, ContractError
from qjig.goal_budget import GoalBudget
from qjig.journal import Journal
from qjig.providers import FieldSpec, ProviderRequest, RawResponse, StandInTransport, call_typed


def test_outcome_review_reserves_distinct_route_bound_work(tmp_path):
    from qjig.outcome_preflight import outcome_review_allocation, outcome_review_reservation
    from qjig.semantic_preflight import semantic_review_allocation
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'openrouter','model':model,'input_tokens':100,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3},'route':'provider-a/fp4'}
    slot=outcome_review_allocation(request_id='r',partition='holdout',spec=spec)
    semantic=semantic_review_allocation(request_id='r',partition='holdout',spec=spec)
    assert slot['stage']=='outcome_review' and slot['work_id']!=semantic['work_id']
    request=ProviderRequest('outcome_review','openrouter','synthetic/model','review',100,
                            max_price=spec['max_price'],route=spec['route'])
    limit=Budget(2,1000,1)
    with GoalBudget.open(tmp_path/'goal.sqlite',total=limit,per_request=limit,allocations={'holdout':limit}) as goal, Journal.open(tmp_path/'journal.sqlite') as journal:
        goal.reserve_run_set('evaluation:test',[slot])
        for altered in (ProviderRequest('semantic_review','openrouter','synthetic/model','review',100,max_price=spec['max_price'],route=spec['route']),
                        ProviderRequest('outcome_review','openrouter','synthetic/model','review',100,max_price=spec['max_price'],route='provider-b/fp8')):
            with pytest.raises(ContractError):
                outcome_review_reservation(goal,'evaluation:test',request_id='r',partition='holdout',request=altered,spec=spec)
        assert not journal.events('r')
        bound=outcome_review_reservation(goal,'evaluation:test',request_id='r',partition='holdout',request=request,spec=spec)
        ledger=BudgetLedger(limit,journal,'r',goal_budget=goal,partition='holdout')
        response=RawResponse(200,json.dumps({'assessment':'uncertain'}),{'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.0001})
        assert call_typed(ledger,StandInTransport([response]),request,{'assessment':FieldSpec(str,('uncertain',))},reservation=bound).ok
        assert goal.audit_journal(journal)['status']=='verified'
        with pytest.raises(ContractError,match='unconsumed'):
            outcome_review_reservation(goal,'evaluation:test',request_id='r',partition='holdout',request=request,spec=spec)
