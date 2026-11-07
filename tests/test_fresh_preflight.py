"""Synthetic resource bounds; never authenticates costs or makes hosted calls."""
from qjig.contracts import Budget
from qjig.goal_budget import GoalBudget
from qjig.plans import MAX_PREDICATES
from qjig.acquisition import MAX_ROUNDS
import pytest
from qjig.budgets import BudgetExceeded
from qjig.contracts import ContractError


def test_fresh_run_set_reserves_all_worst_case_slots(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    allocations = fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                                        planner_model=model, judge_model=model,
                                        planner_input=100, planner_output=50,
                                        judge_input=100, judge_output=50,
                                        planner_price={'prompt': 2, 'completion': 3},
                                        judge_price={'prompt': 2, 'completion': 3})
    assert len(allocations) == 1 + 2 * MAX_PREDICATES * MAX_ROUNDS
    assert len({x['work_id'] for x in allocations}) == len(allocations)
    assert [x['stage'] for x in allocations].count('planner') == 1
    assert [x['stage'] for x in allocations].count('judge_positive') == MAX_PREDICATES * MAX_ROUNDS
    assert [x['stage'] for x in allocations].count('judge_negative') == MAX_PREDICATES * MAX_ROUNDS
    limit = Budget(30, 10000, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        digest = goal.reserve_run_set('pilot-work', allocations)
        assert len(digest) == 64
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0] == len(allocations)
    short_limit = Budget(len(allocations) - 1, 10000, 1)
    with GoalBudget.open(tmp_path / 'short.sqlite', total=short_limit, per_request=short_limit, allocations={'pilot': short_limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve_run_set('too-small', allocations)
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0] == 0
        assert goal._con.execute('SELECT COUNT(*) FROM run_sets').fetchone()[0] == 0
    with pytest.raises(ContractError, match='ceiling'):
        fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                              planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                              judge_input=100, judge_output=50, planner_price=None, judge_price={'prompt': 2, 'completion': 3})


def test_frozen_slot_selection_survives_restart_and_rejects_mismatch(tmp_path):
    from qjig.fresh_preflight import fresh_run_allocations
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    slots = fresh_run_allocations(request_id='request-1', partition='pilot', provider='stand-in',
                                  planner_model=model, judge_model=model, planner_input=100, planner_output=50,
                                  judge_input=100, judge_output=50, planner_price={'prompt': 2, 'completion': 3},
                                  judge_price={'prompt': 2, 'completion': 3})
    path = tmp_path / 'goal.sqlite'
    limit = Budget(30, 10000, 1)
    args = dict(request_id='request-1', partition='pilot', stage='judge_positive', provider='stand-in',
                model='synthetic/model', tokens=150, cost_usd=0.0005)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        goal.reserve_run_set('pilot-set', slots)
        first = goal.select_required_work('pilot-set', **args)
        goal.reserve('attempt-1', required_id=first, **args)
        goal.record_usage('attempt-1', input_tokens=10, output_tokens=5, cost_usd=0.0001)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        second = goal.select_required_work('pilot-set', **args)
        assert second != first
        with pytest.raises(ContractError):
            goal.select_required_work('other-set', **args)
        with pytest.raises(ContractError):
            goal.select_required_work('pilot-set', **{**args, 'model': 'wrong'})
        with pytest.raises(ContractError):
            goal.select_required_work('pilot-set', **{**args, 'tokens': 151})
