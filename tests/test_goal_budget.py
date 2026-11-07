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
        resumed.record_usage("attempt-2", input_tokens=100, output_tokens=50, cost_usd=0.35)
        with pytest.raises(BudgetExceeded):
            resumed.reserve("attempt-3", "request-3", "holdout", tokens=201, cost_usd=0.3)
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
        assert ledger.committed() == Budget(1, 100, 0.1)
    with GoalBudget.open(tmp_path / "overrun.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as ledger:
        ledger.reserve("a", "r", "smoke", tokens=100, cost_usd=0.1)
        ledger.record_usage("a", input_tokens=100, output_tokens=1, cost_usd=0.11)
        assert ledger.actual_usage()["cost_usd"] == 0.11
        assert ledger.committed() == Budget(1, 101, 0.11)
        with pytest.raises(BudgetExceeded, match="bound_exceeded"):
            ledger.reserve("b", "r", "smoke", tokens=50, cost_usd=0.05)


def test_request_ledger_reserves_goal_before_call_and_records_receipt(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / "goal.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "journal.sqlite") as journal:
        ledger = BudgetLedger(limit, journal, "r", goal_budget=goal, partition="smoke")
        def call():
            assert goal.totals() == Budget(1, 150, 0.2)
            assert [e.kind for e in journal.events("r")] == ["intent"]
            return "ok", {"prompt_tokens": 40, "completion_tokens": 20, "cost_usd": 0.1}
        assert ledger.run("planner", call, provider="stand-in", model="m", input_sha256="a" * 64,
                          reserve_tokens=50, reserve_input_tokens=100, reserve_cost_usd=0.2) == "ok"
        assert goal.actual_usage() == {"calls": 1, "input_tokens": 40, "output_tokens": 20, "cost_usd": 0.1, "unknown_calls": 0}
        assert journal.events("r")[0].payload["goal_attempt_id"]


def test_request_ledger_crash_retains_goal_reservation(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / "goal.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "journal.sqlite") as journal:
        ledger = BudgetLedger(limit, journal, "r", goal_budget=goal, partition="smoke")
        with pytest.raises(KeyboardInterrupt):
            ledger.run("planner", lambda: (_ for _ in ()).throw(KeyboardInterrupt()), provider="stand-in", model="m",
                       input_sha256="b" * 64, reserve_tokens=50, reserve_input_tokens=100, reserve_cost_usd=0.2)
        assert goal.actual_usage()["unknown_calls"] == 1 and len(journal.pending("r")) == 1
        with pytest.raises(BudgetExceeded):
            goal.reserve("another", "other", "smoke", tokens=1, cost_usd=0.01)


def test_goal_reservation_holds_back_mandatory_work(tmp_path):
    limit = Budget(3, 500, 0.5)
    with GoalBudget.open(tmp_path / "g.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve("a", "r", "smoke", tokens=100, cost_usd=0.1, hold_back_calls=2,
                         hold_back_tokens=401, hold_back_cost_usd=0.4)
        assert goal.totals().max_calls == 0
        goal.reserve("a", "r", "smoke", tokens=100, cost_usd=0.1, hold_back_calls=2,
                     hold_back_tokens=400, hold_back_cost_usd=0.4)
        assert goal.totals() == Budget(1, 100, 0.1)


def test_request_goal_accounting_requires_both_bounds_before_reserving(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / "g.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "j.sqlite") as journal:
        ledger = BudgetLedger(limit, journal, "r", goal_budget=goal, partition="smoke")
        for kwargs in ({"reserve_input_tokens": 100}, {"reserve_cost_usd": 0.2}):
            with pytest.raises(BudgetExceeded, match="preflight_unavailable"):
                ledger.run("planner", lambda: ("ok", {}), provider="stand-in", model="m", input_sha256="a" * 64,
                           reserve_tokens=50, **kwargs)
        assert goal.totals().max_calls == 0 and journal.events("r") == []


def test_recover_goal_usage_from_matching_durable_receipt(tmp_path):
    from qjig.journal import Journal, run_journaled

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / "g.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "j.sqlite") as journal:
        goal.reserve("attempt", "r", "smoke", tokens=100, cost_usd=0.2)
        run_journaled(journal, call=lambda: ("ok", {"prompt_tokens": 20, "completion_tokens": 10, "cost_usd": 0.1}),
                      request_id="r", stage="planner", provider="stand-in", model="m", input_sha256="a" * 64,
                      intent_payload={"goal_attempt_id": "attempt"})
        assert goal.actual_usage()["unknown_calls"] == 1
        assert goal.recover_receipt("attempt", journal) == "r#1"
        assert goal.actual_usage() == {"calls": 1, "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.1, "unknown_calls": 0}
        goal.reserve("next", "r2", "smoke", tokens=100, cost_usd=0.2)
        with pytest.raises(ContractError):
            goal.recover_receipt("attempt", journal)


def test_recover_refuses_missing_or_uncertain_receipt(tmp_path):
    from qjig.journal import Journal

    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / "g.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "j.sqlite") as journal:
        goal.reserve("attempt", "r", "smoke", tokens=100, cost_usd=0.2)
        with pytest.raises(ContractError):
            goal.recover_receipt("attempt", journal)
        intent = journal.record_intent(request_id="r", stage="planner", provider="stand-in", model="m", input_sha256="a" * 64,
                                       payload={"goal_attempt_id": "attempt"})
        journal.record_terminal(intent, "uncertain", {"detail": "timeout"})
        with pytest.raises(ContractError):
            goal.recover_receipt("attempt", journal)
        assert goal.actual_usage()["unknown_calls"] == 1


def test_recover_after_interruption_between_journal_receipt_and_goal_update(tmp_path, monkeypatch):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / "g.sqlite", total=limit, per_request=limit, allocations={"smoke": limit}) as goal, Journal.open(tmp_path / "j.sqlite") as journal:
        ledger = BudgetLedger(limit, journal, "r", goal_budget=goal, partition="smoke")
        with monkeypatch.context() as patch:
            patch.setattr(goal, "record_usage", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
            with pytest.raises(KeyboardInterrupt):
                ledger.run("planner", lambda: ("ok", {"prompt_tokens": 40, "completion_tokens": 20, "cost_usd": 0.1}),
                           provider="stand-in", model="m", input_sha256="a" * 64,
                           reserve_tokens=50, reserve_input_tokens=100, reserve_cost_usd=0.2)
        events = journal.events("r")
        assert [e.kind for e in events] == ["intent", "receipt"]
        assert goal.actual_usage()["unknown_calls"] == 1
        assert goal.recover_receipt(events[0].payload["goal_attempt_id"], journal) == events[0].call_id
        assert goal.actual_usage()["cost_usd"] == 0.1


def test_complete_usage_releases_only_unused_reservation_after_restart(tmp_path):
    path = tmp_path / "g.sqlite"
    limit = Budget(2, 100, 0.2)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={"smoke": limit}) as goal:
        goal.reserve("a", "r", "smoke", tokens=90, cost_usd=0.18)
        goal.record_usage("a", input_tokens=20, output_tokens=10, cost_usd=0.06)
        assert goal.totals() == Budget(1, 90, 0.18)  # original reservation is preserved
        assert goal.committed() == Budget(1, 30, 0.06)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={"smoke": limit}) as goal:
        goal.reserve("b", "r", "smoke", tokens=70, cost_usd=0.14)
        assert goal.totals() == Budget(2, 160, 0.32)  # sum of original bounds, not actual spend
        assert goal.committed() == Budget(2, 100, 0.2)
