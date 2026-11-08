"""Trusted local fresh-workbench configuration; not hosted-call authorization."""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

from .contracts import Budget, ContractError
from .fresh_preflight import fresh_run_allocations
from .fresh_service import FreshWorkbench
from .goal_budget import GoalBudget
from .providers import OpenRouterTransport


def _bind_goal_directory(env_path: Path, goal_dir: Path, *, version: str) -> None:
    """Bind v2 workbenches to one local accounting directory per credential root.

    The local anchor is not tamper-proof and does not cover other entrypoints.
    """
    anchor_dir = env_path.resolve().parent / '.local'
    anchor = anchor_dir / 'qjig-active-goal-directory'
    if anchor_dir.is_symlink() or anchor.is_symlink():
        raise ContractError('unsafe goal directory anchor')
    if version == 'qjig.fresh-config.v1':
        if anchor.exists():
            raise ContractError('goal directory already bound; v2 configuration required')
        return
    anchor_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    expected = str(goal_dir.resolve())
    try:
        fd = os.open(anchor, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        try:
            if anchor.is_symlink() or anchor.read_text(encoding='utf-8') != expected:
                raise ContractError('goal directory differs from existing binding')
        except (OSError, UnicodeError) as exc:
            raise ContractError('goal directory binding unavailable') from exc
    else:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(expected)
            output.flush()
            os.fsync(output.fileno())


def load_fresh_config(path: Path) -> FreshWorkbench:
    """Load local settings. Price and token values remain unverified assertions."""
    data = json.loads(path.read_text(encoding='utf-8'))
    fields = {'schema', 'state_dir', 'env_path', 'partition', 'total', 'per_request',
              'allocations', 'planner', 'judge', 'reviewer'}
    if not isinstance(data, dict):
        raise ContractError('invalid fresh configuration')
    version = data.get('schema')
    if version == 'qjig.fresh-config.v2':
        fields.add('goal_dir')
    if set(data) != fields or version not in ('qjig.fresh-config.v1', 'qjig.fresh-config.v2'):
        raise ContractError('invalid fresh configuration')
    if version == 'qjig.fresh-config.v2' and (not isinstance(data['goal_dir'], str) or not data['goal_dir'].strip()):
        raise ContractError('goal directory required')
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
    goal_dir = Path(data['goal_dir']) if version == 'qjig.fresh-config.v2' else state_dir
    if goal_dir.is_symlink():
        raise ContractError('unsafe goal directory')
    _bind_goal_directory(env_path, goal_dir, version=version)
    goal_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    def account_bound_goal():
        # Refresh only when a run starts; configuration loading never contacts the provider.
        from .account_client import fetch_account_snapshot, refresh_account_constraints
        path = goal_dir / 'goal.sqlite'
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
    return FreshWorkbench(state_dir, goal_factory=account_bound_goal, journal_path=goal_dir / 'journal.sqlite',
                          transport_factory=lambda: OpenRouterTransport(env_path), partition=data['partition'],
                          planner=planner, judge=judge, reviewer=reviewer, budget=per_request)
