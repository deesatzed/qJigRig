"""Synthetic reservations only; no provider calls or real prices."""
import pytest

from qjig.contracts import Budget, ContractError
from qjig.budgets import BudgetExceeded
from qjig.goal_budget import GoalBudget


def test_goal_budget_survives_restart_and_enforces_partition_and_request_caps(tmp_path):
    path = tmp_path / "budget.sqlite"
    total = Budget(4, 1000, 1.0)
    per_request = Budget(2, 400, 0.4)
    allocations = {"smoke": Budget(2, 400, 0.4), "holdout": Budget(2, 600, 0.6)}
    with GoalBudget.open(path, total=total, per_request=per_request, allocations=allocations) as ledger:
        ledger.reserve("attempt-1", "request-1", "smoke", tokens=200, cost_usd=0.2)
        with pytest.raises(BudgetExceeded):
            ledger.reserve("attempt-2", "request-1", "smoke", tokens=201, cost_usd=0.2)
        assert ledger.totals().max_calls == 1
        ledger.record_usage("attempt-1", input_tokens=100, output_tokens=50, cost_usd=0.1)
    with GoalBudget.open(path, total=total, per_request=per_request, allocations=allocations) as resumed:
        with pytest.raises(ContractError):
            resumed.reserve("attempt-1", "request-1", "smoke", tokens=200, cost_usd=0.2)
        resumed.reserve("attempt-2", "request-2", "holdout", tokens=400, cost_usd=0.4)
        resumed.record_usage("attempt-2", input_tokens=100, output_tokens=50, cost_usd=0.1)
        with pytest.raises(BudgetExceeded):
            resumed.reserve("attempt-3", "request-3", "holdout", tokens=201, cost_usd=0.1)
        assert resumed.totals() == Budget(2, 600, 0.6)
    with pytest.raises(ContractError):
        GoalBudget.open(path, total=Budget(5, 1000, 1.0), per_request=per_request, allocations=allocations)


def test_concurrent_connections_cannot_overreserve(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "budget.sqlite"
    total = Budget(1, 100, 0.1)
    allocations = {"smoke": total}
    with GoalBudget.open(path, total=total, per_request=total, allocations=allocations):
        pass
    barrier = Barrier(2)
    def attempt(ident):
        with GoalBudget.open(path, total=total, per_request=total, allocations=allocations) as ledger:
            barrier.wait(timeout=5)
            try:
                ledger.reserve(ident, ident, "smoke", tokens=100, cost_usd=0.1)
                return "reserved"
            except BudgetExceeded:
                return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ("a", "b"))) == ["refused", "reserved"]
    with GoalBudget.open(path, total=total, per_request=total, allocations=allocations) as ledger:
        assert ledger.totals() == total


@pytest.mark.parametrize("total,request_limit", [
    (Budget(2001, 8000000, 25), Budget(30, 160000, 1)),
    (Budget(2000, 8000001, 25), Budget(30, 160000, 1)),
    (Budget(2000, 8000000, 25.01), Budget(30, 160000, 1)),
    (Budget(2000, 8000000, 25), Budget(31, 160000, 1)),
    (Budget(2000, 8000000, 25), Budget(30, 160001, 1)),
    (Budget(2000, 8000000, 25), Budget(30, 160000, 1.01)),
])
def test_contract_ceilings_cannot_be_raised(tmp_path, total, request_limit):
    with pytest.raises(ContractError):
        GoalBudget.open(tmp_path / "budget.sqlite", total=total, per_request=request_limit,
                        allocations={"smoke": Budget(1, 100, 0.1)})


def test_actual_and_unknown_usage_survive_restart_and_block_dispatch(tmp_path):
    path = tmp_path / "budget.sqlite"
    limit = Budget(3, 1000, 1.0)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={"smoke": limit}) as ledger:
        ledger.reserve("a", "r", "smoke", tokens=300, cost_usd=0.3)
        with pytest.raises(BudgetExceeded, match="unknown"):
            ledger.reserve("b", "r", "smoke", tokens=100, cost_usd=0.1)
        ledger.record_usage("a", input_tokens=100, output_tokens=40, cost_usd=0.12)
        assert ledger.actual_usage() == {"calls": 1, "input_tokens": 100, "output_tokens": 40, "cost_usd": 0.12, "unknown_calls": 0}
        ledger.reserve("b", "r", "smoke", tokens=100, cost_usd=0.1)
        ledger.record_usage("b", input_tokens=None, output_tokens=None, cost_usd=None)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={"smoke": limit}) as ledger:
        assert ledger.totals() == Budget(2, 400, 0.4)
        assert ledger.actual_usage()["unknown_calls"] == 1
        with pytest.raises(BudgetExceeded, match="unknown"):
            ledger.reserve("c", "other", "smoke", tokens=50, cost_usd=0.05)
        with pytest.raises(ContractError):
            ledger.record_usage("a", input_tokens=1, output_tokens=1, cost_usd=0.01)


def test_actual_usage_unknown_and_exceeded_bounds_are_not_hidden(tmp_path):
    limit = Budget(3, 1000, 1.0)
    with GoalBudget.open(tmp_path / "unknown.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as ledger:
        ledger.reserve("a", "r", "smoke", tokens=100, cost_usd=0.1)
        assert ledger.actual_usage()["cost_usd"] is None
    with GoalBudget.open(tmp_path / "overrun.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as ledger:
        ledger.reserve("a", "r", "smoke", tokens=100, cost_usd=0.1)
        ledger.record_usage("a", input_tokens=100, output_tokens=1, cost_usd=0.11)
        assert ledger.actual_usage()["cost_usd"] == 0.11
        with pytest.raises(BudgetExceeded, match="bound_exceeded"):
            ledger.reserve("b", "r", "smoke", tokens=50, cost_usd=0.05)
