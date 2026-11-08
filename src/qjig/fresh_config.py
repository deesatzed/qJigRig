"""Trusted local fresh-workbench configuration; not hosted-call authorization."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .contracts import Budget, ContractError
from .fresh_preflight import fresh_run_allocations
from .fresh_service import FreshWorkbench
from .goal_budget import GoalBudget
from .providers import OpenRouterTransport


def load_fresh_config(path: Path) -> FreshWorkbench:
    """Load local settings. Price and token values remain unverified assertions."""
    data = json.loads(path.read_text(encoding='utf-8'))
    fields = {'schema', 'state_dir', 'env_path', 'partition', 'total', 'per_request',
              'allocations', 'planner', 'judge', 'reviewer'}
    if not isinstance(data, dict) or set(data) != fields or data['schema'] != 'qjig.fresh-config.v1':
        raise ContractError('invalid fresh configuration')
    if any(not isinstance(data[k], str) or not data[k].strip() for k in ('state_dir', 'env_path', 'partition')):
        raise ContractError('fresh paths and partition are required')
    total, per_request = Budget.from_dict(data['total']), Budget.from_dict(data['per_request'])
    if not isinstance(data['allocations'], dict) or set(data['allocations']) != {'smoke', 'pilot', 'holdout', 'acceptance'}:
        raise ContractError('smoke, pilot, holdout and acceptance allocations are required')
    allocations = {name: Budget.from_dict(value) for name, value in data['allocations'].items()}
    if any(not isinstance(name, str) or not name.strip() for name in allocations) or data['partition'] not in allocations:
        raise ContractError('invalid fresh allocation')
    def fits(budget, ceiling):
        return (budget.max_calls <= ceiling.max_calls and budget.max_tokens <= ceiling.max_tokens
                and Decimal(str(budget.max_cost_usd)) <= Decimal(str(ceiling.max_cost_usd)))
    if not fits(total, Budget(2000, 8000000, 25)) or not fits(per_request, Budget(30, 160000, 1)):
        raise ContractError('fresh configuration exceeds goal limits')
    combined = Budget(sum(b.max_calls for b in allocations.values()), sum(b.max_tokens for b in allocations.values()),
                      float(sum(Decimal(str(b.max_cost_usd)) for b in allocations.values())))
    if not fits(combined, total):
        raise ContractError('fresh allocations exceed goal limit')
    planner, judge, reviewer = (data[k] for k in ('planner', 'judge', 'reviewer'))
    keys = {'provider', 'model', 'input_tokens', 'output_tokens', 'max_price'}
    if any(not isinstance(s, dict) or set(s) != keys or s['provider'] != 'openrouter'
           or not isinstance(s['model'], dict) for s in (planner, judge, reviewer)):
        raise ContractError('invalid fresh stage')
    if (planner['model'].get('id') != 'deepseek/deepseek-v4.1-flash-1017'
            or judge['model'].get('id') != 'tencent/hy4'
            or reviewer['model'].get('id') not in ('deepseek/deepseek-v4.1-flash-1017', 'tencent/hy4')):
        raise ContractError('fresh stage model is not selected for this goal')
    fresh_run_allocations(request_id='configuration-check', partition=data['partition'], provider='openrouter',
        planner_model=planner['model'], judge_model=judge['model'], planner_input=planner['input_tokens'],
        planner_output=planner['output_tokens'], judge_input=judge['input_tokens'], judge_output=judge['output_tokens'],
        planner_price=planner['max_price'], judge_price=judge['max_price'], reviewer=reviewer)
    state_dir = Path(data['state_dir'])
    env_path = Path(data['env_path'])
    def account_bound_goal():
        # Refresh only when a run starts; configuration loading never contacts the provider.
        from .account_client import fetch_account_snapshot, refresh_account_constraints
        path = state_dir / 'goal.sqlite'
        if path.is_symlink():
            raise ContractError('unsafe goal ledger path')
        if not path.exists():
            snapshot = fetch_account_snapshot(env_path)
            return GoalBudget.open(path, total=total, per_request=per_request,
                                   allocations=allocations, account_snapshot=snapshot)
        goal = GoalBudget.resume_account_bound(path, total=total, per_request=per_request,
                                                allocations=allocations)
        try:
            refresh_account_constraints(goal, env_path)
        except BaseException:
            goal.close()
            raise
        return goal
    return FreshWorkbench(state_dir, goal_factory=account_bound_goal,
                          transport_factory=lambda: OpenRouterTransport(env_path), partition=data['partition'],
                          planner=planner, judge=judge, reviewer=reviewer, budget=per_request)
