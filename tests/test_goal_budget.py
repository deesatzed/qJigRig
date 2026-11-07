"""Synthetic reservations only; no provider calls or real prices."""
import pytest

from qjig.contracts import Budget, ContractError


def test_account_snapshot_binds_persistent_policy_without_authorizing_calls(tmp_path):
    key = {'data': {'limit_remaining': 0.6, 'include_byok_in_limit': False, 'is_free_tier': False,
                    'label': 'private-account-label'}}
    credits = {'data': {'total_credits': 1, 'total_usage': 0.2}}
    snapshot = (key, credits)
    path = tmp_path / 'account.sqlite'
    too_high = Budget(2, 500, 0.7)
    with pytest.raises(ContractError):
        GoalBudget.open(path, total=too_high, per_request=too_high, allocations={'smoke': too_high}, account_snapshot=snapshot)
    assert not path.exists()
    limit = Budget(2, 500, 0.6)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}, account_snapshot=snapshot) as goal:
        goal.reserve('attempt', 'request', 'smoke', tokens=10, cost_usd=0.1)
        goal.record_usage('attempt', input_tokens=3, output_tokens=2, cost_usd=0.05)
        assert 'private-account-label' not in goal._con.execute('SELECT value FROM policy').fetchone()[0]
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}, account_snapshot=snapshot) as goal:
        assert goal.actual_usage()['cost_usd'] == 0.05
    with pytest.raises(ContractError):
        GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit})
    changed = ({'data': {**key['data'], 'limit_remaining': 0.5}}, credits)
    with pytest.raises(ContractError):
        GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}, account_snapshot=changed)
from qjig.budgets import BudgetExceeded
from qjig.goal_budget import GoalBudget


def test_resume_account_bound_policy_from_persisted_constraints(tmp_path):
    from decimal import Decimal
    snapshot = ({'data': {'limit_remaining': Decimal('0.60000000000000001'),
                          'include_byok_in_limit': False, 'is_free_tier': False, 'label': 'private'}},
                {'data': {'total_credits': Decimal('1.00000000000000001'), 'total_usage': Decimal('0.2')}})
    limit = Budget(3, 500, 0.6)
    path = tmp_path / 'goal.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'s': limit}, account_snapshot=snapshot) as goal:
        goal.reserve('a', 'r', 's', tokens=10, cost_usd=0.1)
        goal.record_usage('a', input_tokens=2, output_tokens=2, cost_usd=0.05)
        baseline = goal.account_refresh_baseline()
        reduced = ({'data': {**snapshot[0]['data'], 'limit_remaining': Decimal('0.1')}}, snapshot[1])
        goal.restrict_account_snapshot(baseline, reduced)
    with GoalBudget.resume_account_bound(path, total=limit, per_request=limit, allocations={'s': limit}) as goal:
        assert goal.actual_usage()['cost_usd'] == 0.05
        with pytest.raises(BudgetExceeded):
            goal.reserve('b', 'r', 's', tokens=10, cost_usd=0.11)
        assert 'private' not in goal._con.execute('SELECT value FROM policy').fetchone()[0]
    with pytest.raises(ContractError):
        GoalBudget.resume_account_bound(path, total=Budget(3, 500, 0.5), per_request=limit, allocations={'s': limit})
    missing = tmp_path / 'missing.sqlite'
    with pytest.raises(ContractError):
        GoalBudget.resume_account_bound(missing, total=limit, per_request=limit, allocations={'s': limit})
    assert not missing.exists()


def test_resume_rejects_unbound_or_invalid_stored_account_policy(tmp_path):
    import json
    import sqlite3
    limit = Budget(2, 100, 0.5)
    path = tmp_path / 'goal.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'s': limit}):
        pass
    with pytest.raises(ContractError):
        GoalBudget.resume_account_bound(path, total=limit, per_request=limit, allocations={'s': limit})
    snapshot = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
                {'data': {'total_credits': 1, 'total_usage': 0}})
    path = tmp_path / 'bound.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'s': limit}, account_snapshot=snapshot):
        pass
    with sqlite3.connect(path) as con:
        policy = json.loads(con.execute('SELECT value FROM policy').fetchone()[0])
        policy['account_snapshot']['hosted_authorized'] = True
        con.execute('UPDATE policy SET value=?', (json.dumps(policy),))
    with pytest.raises(ContractError):
        GoalBudget.resume_account_bound(path, total=limit, per_request=limit, allocations={'s': limit})


def test_refresh_restricts_remaining_account_budget_without_reset(tmp_path):
    initial = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
               {'data': {'total_credits': 1, 'total_usage': 0}})
    limit = Budget(4, 1000, 1)
    path = tmp_path / 'goal.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}, account_snapshot=initial) as goal:
        goal.reserve('a', 'r', 'smoke', tokens=10, cost_usd=0.2)
        goal.record_usage('a', input_tokens=3, output_tokens=2, cost_usd=0.1)
        baseline = goal.account_refresh_baseline()
        reduced = ({'data': {**initial[0]['data'], 'limit_remaining': 0.2}}, initial[1])
        goal.restrict_account_snapshot(baseline, reduced)
        goal.reserve('b', 'r', 'smoke', tokens=10, cost_usd=0.2)
        goal.record_usage('b', input_tokens=3, output_tokens=2, cost_usd=0.1)
        baseline = goal.account_refresh_baseline()
        goal.restrict_account_snapshot(baseline, initial)  # a higher observation cannot raise the cap
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}, account_snapshot=initial) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve('c', 'r', 'smoke', tokens=10, cost_usd=0.11)
        goal.reserve('c', 'r', 'smoke', tokens=10, cost_usd=0.1)
        with pytest.raises(BudgetExceeded):
            goal.account_refresh_baseline()  # pending usage cannot be treated as spent


def test_refresh_rejects_intervening_usage_and_unbound_policy(tmp_path):
    snapshot = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
                {'data': {'total_credits': 1, 'total_usage': 0}})
    limit = Budget(3, 500, 1)
    with GoalBudget.open(tmp_path / 'unbound.sqlite', total=limit, per_request=limit, allocations={'s': limit}) as goal:
        with pytest.raises(ContractError):
            goal.account_refresh_baseline()
    with GoalBudget.open(tmp_path / 'bound.sqlite', total=limit, per_request=limit, allocations={'s': limit}, account_snapshot=snapshot) as goal:
        baseline = goal.account_refresh_baseline()
        goal.reserve('a', 'r', 's', tokens=10, cost_usd=0.1)
        goal.record_usage('a', input_tokens=2, output_tokens=2, cost_usd=0.05)
        with pytest.raises(ContractError, match='changed'):
            goal.restrict_account_snapshot(baseline, snapshot)


def test_refresh_restriction_includes_preallocated_required_work(tmp_path):
    initial = ({'data': {'limit_remaining': 1, 'include_byok_in_limit': False, 'is_free_tier': False}},
               {'data': {'total_credits': 1, 'total_usage': 0}})
    limit = Budget(3, 500, 1)
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=limit, per_request=limit, allocations={'s': limit}, account_snapshot=initial) as goal:
        goal.reserve_required('r', 's', [('mandatory', 10, 0.25, 'judge', 'stand-in', 'm')])
        baseline = goal.account_refresh_baseline()
        reduced = ({'data': {**initial[0]['data'], 'limit_remaining': 0.2}}, initial[1])
        goal.restrict_account_snapshot(baseline, reduced)
        with pytest.raises(BudgetExceeded, match='account'):
            goal.reserve('a', 'r', 's', tokens=1, cost_usd=0.01)
        with pytest.raises(BudgetExceeded, match='account'):
            goal.reserve('a', 'r', 's', tokens=10, cost_usd=0.25, required_id='mandatory',
                         stage='judge', provider='stand-in', model='m')


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
        assert ledger.actual_usage() == {"calls": 1, "input_tokens": 100, "output_tokens": 40, "cost_usd": 0.12, "known_input_tokens": 100, "known_output_tokens": 40, "known_cost_usd": 0.12, "unknown_calls": 0}
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
        assert goal.actual_usage() == {"calls": 1, "input_tokens": 40, "output_tokens": 20, "cost_usd": 0.1, "known_input_tokens": 40, "known_output_tokens": 20, "known_cost_usd": 0.1, "unknown_calls": 0}
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
                      intent_payload={"goal_attempt_id": "attempt", "reserve_tokens": 100, "reserve_cost_usd": 0.2})
        assert goal.actual_usage()["unknown_calls"] == 1
        assert goal.recover_receipt("attempt", journal) == "r#1"
        assert goal.actual_usage() == {"calls": 1, "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.1, "known_input_tokens": 20, "known_output_tokens": 10, "known_cost_usd": 0.1, "unknown_calls": 0}
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


def test_goal_actual_usage_does_not_report_partial_sums_as_totals(tmp_path):
    limit = Budget(3, 1000, 1)
    path = tmp_path / 'goal.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        goal.reserve('known', 'r', 'smoke', tokens=100, cost_usd=0.1)
        goal.record_usage('known', input_tokens=30, output_tokens=10, cost_usd=0.04)
        goal.reserve('unknown', 'r', 'smoke', tokens=100, cost_usd=0.1)
        goal.record_usage('unknown', input_tokens=20, output_tokens=None, cost_usd=None)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        usage = goal.actual_usage()
        assert usage['input_tokens'] == 50
        assert usage['output_tokens'] is None
        assert usage['cost_usd'] is None
        assert usage['known_input_tokens'] == 50
        assert usage['known_output_tokens'] == 10
        assert usage['known_cost_usd'] == 0.04
        assert usage['unknown_calls'] == 1
        with pytest.raises(BudgetExceeded, match='unknown'):
            goal.reserve('later', 'r', 'smoke', tokens=1, cost_usd=0.01)


def test_required_work_reservations_survive_restart_and_cannot_be_spent_by_other_calls(tmp_path):
    path = tmp_path / 'goal.sqlite'
    limit = Budget(3, 300, 0.3)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        goal.reserve_required('r', 'smoke', [('judge-a', 100, 0.1, 'judge', 'stand-in', 'm'), ('judge-b', 100, 0.1, 'judge', 'stand-in', 'm')])
        goal.reserve('planner', 'r', 'smoke', tokens=100, cost_usd=0.1)
        goal.record_usage('planner', input_tokens=40, output_tokens=10, cost_usd=0.05)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve('discretionary', 'other', 'smoke', tokens=1, cost_usd=0.01)
        with pytest.raises(ContractError):
            goal.reserve('wrong-request', 'other', 'smoke', tokens=100, cost_usd=0.1, required_id='judge-a', stage='judge', provider='stand-in', model='m')
        with pytest.raises(ContractError):
            goal.reserve('too-large', 'r', 'smoke', tokens=101, cost_usd=0.1, required_id='judge-a', stage='judge', provider='stand-in', model='m')
        goal.reserve('attempt-a', 'r', 'smoke', tokens=100, cost_usd=0.1, required_id='judge-a', stage='judge', provider='stand-in', model='m')
        goal.record_usage('attempt-a', input_tokens=30, output_tokens=20, cost_usd=0.05)
        with pytest.raises(ContractError):
            goal.reserve('duplicate', 'r', 'smoke', tokens=100, cost_usd=0.1, required_id='judge-a', stage='judge', provider='stand-in', model='m')
        goal.reserve('attempt-b', 'r', 'smoke', tokens=100, cost_usd=0.1, required_id='judge-b', stage='judge', provider='stand-in', model='m')
        assert goal.totals().max_calls == 3


def test_request_ledger_consumes_only_its_reserved_required_call(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(1, 100, 0.1)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        goal.reserve_required('r', 'smoke', [('judge', 100, 0.1, 'judge', 'stand-in', 'm')])
        ledger = BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='smoke')
        assert ledger.run('judge', lambda: ('ok', {'prompt_tokens': 40, 'completion_tokens': 10, 'cost_usd': 0.05}),
                          provider='stand-in', model='m', input_sha256='a' * 64,
                          reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.1,
                          required_id='judge') == 'ok'
        assert goal.actual_usage()['unknown_calls'] == 0
        assert journal.events('r')[0].payload['required_id'] == 'judge'


def test_required_work_batch_is_atomic_and_concurrent_plans_cannot_overbook(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / 'goal.sqlite'
    limit = Budget(2, 200, 0.2)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        with pytest.raises(ContractError):
            goal.reserve_required('r', 'smoke', [('valid', 100, 0.1, 'judge', 'stand-in', 'm'), ('bad', -1, 0.1, 'judge', 'stand-in', 'm')])
        with pytest.raises(BudgetExceeded):
            goal.reserve_required('r', 'smoke', [('valid', 100, 0.1, 'judge', 'stand-in', 'm'), ('other', 101, 0.1, 'judge', 'stand-in', 'm')])
    barrier = Barrier(2)
    def plan(ident):
        with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
            barrier.wait(timeout=5)
            try:
                goal.reserve_required(ident, 'smoke', [(ident, 150, 0.15, 'judge', 'stand-in', 'm')])
                return 'reserved'
            except BudgetExceeded:
                return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(plan, ('one', 'two'))) == ['refused', 'reserved']
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve_required('third', 'smoke', [('valid', 100, 0.1, 'judge', 'stand-in', 'm')])


def test_required_allocation_rejects_wrong_stage_provider_or_model_before_dispatch(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(1, 100, 0.1)
    path = tmp_path / 'goal.sqlite'
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        goal.reserve_required('r', 'smoke', [('judge', 100, 0.1, 'judge', 'stand-in', 'judge-model')])
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='smoke')
        seen = []
        for stage, provider, model in [('planner', 'stand-in', 'judge-model'),
                                       ('judge', 'other', 'judge-model'),
                                       ('judge', 'stand-in', 'other')]:
            with pytest.raises(ContractError):
                ledger.run(stage, lambda: seen.append('called'), provider=provider, model=model, input_sha256='a'*64,
                           reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.1, required_id='judge')
        assert not seen and journal.events('r') == [] and goal.totals().max_calls == 0
        assert ledger.run('judge', lambda: ('ok', {'prompt_tokens': 1, 'completion_tokens': 1, 'cost_usd': 0.01}),
                          provider='stand-in', model='judge-model', input_sha256='a'*64,
                          reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.1, required_id='judge') == 'ok'


def test_legacy_unbound_required_allocation_stays_reserved_but_cannot_be_consumed(tmp_path):
    import sqlite3

    path = tmp_path / 'goal.sqlite'
    limit = Budget(1, 100, 0.1)
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}):
        pass
    with sqlite3.connect(path) as con:
        con.execute('DROP TABLE required_work')
        con.execute('CREATE TABLE required_work (work_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, partition TEXT NOT NULL, tokens INTEGER NOT NULL, cost TEXT NOT NULL, attempt_id TEXT UNIQUE)')
        con.execute("INSERT INTO required_work VALUES ('old', 'r', 'smoke', 100, '0.1', NULL)")
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        with pytest.raises(ContractError):
            goal.reserve('a', 'r', 'smoke', tokens=100, cost_usd=0.1, required_id='old', stage='judge', provider='stand-in', model='m')
        with pytest.raises(BudgetExceeded):
            goal.reserve('b', 'r', 'smoke', tokens=1, cost_usd=0.01)


def test_full_run_set_reservation_is_atomic_frozen_and_survives_restart(tmp_path):
    path = tmp_path / 'goal.sqlite'
    total = Budget(4, 400, 0.4)
    partitions = {'pilot': Budget(2, 200, 0.2), 'holdout': Budget(2, 200, 0.2)}
    assignments = [
        {'work_id': 'p1', 'request_id': 'pilot-1', 'partition': 'pilot', 'tokens': 100, 'cost_usd': 0.1, 'stage': 'judge', 'provider': 'stand-in', 'model': 'm'},
        {'work_id': 'h1', 'request_id': 'hold-1', 'partition': 'holdout', 'tokens': 100, 'cost_usd': 0.1, 'stage': 'judge', 'provider': 'stand-in', 'model': 'm'},
    ]
    with GoalBudget.open(path, total=total, per_request=total, allocations=partitions) as goal:
        oversized = assignments + [{**assignments[1], 'work_id': 'h2', 'request_id': 'hold-2', 'tokens': 101}]
        with pytest.raises(BudgetExceeded):
            goal.reserve_run_set('evaluation', oversized)
        assert goal.totals().max_calls == 0
        digest = goal.reserve_run_set('evaluation', assignments)
        assert len(digest) == 64
    with GoalBudget.open(path, total=total, per_request=total, allocations=partitions) as goal:
        assert goal.reserve_run_set('evaluation', assignments) == digest
        with pytest.raises(ContractError):
            goal.reserve_run_set('evaluation', assignments[:1])
        with pytest.raises(BudgetExceeded):
            goal.reserve('extra', 'hold-other', 'holdout', tokens=101, cost_usd=0.1)
        goal.reserve('attempt', 'hold-1', 'holdout', tokens=100, cost_usd=0.1,
                     required_id='h1', stage='judge', provider='stand-in', model='m')
        assert goal.reserve_run_set('evaluation', assignments) == digest


def test_run_set_refuses_corruption_and_concurrent_aggregate_overbooking(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import sqlite3

    path = tmp_path / 'goal.sqlite'
    limit = Budget(2, 200, 0.2)
    assignment = {'work_id': 'one', 'request_id': 'r1', 'partition': 'pilot', 'tokens': 150,
                  'cost_usd': 0.15, 'stage': 'judge', 'provider': 'stand-in', 'model': 'm'}
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}):
        pass
    barrier = Barrier(2)
    def plan(i):
        with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
            barrier.wait(timeout=5)
            try:
                goal.reserve_run_set(i, [{**assignment, 'work_id': i, 'request_id': i}])
                return 'reserved'
            except BudgetExceeded:
                return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(plan, ('one', 'two'))) == ['refused', 'reserved']
    with sqlite3.connect(path) as con:
        ident = con.execute('SELECT set_id FROM run_sets').fetchone()[0]
        con.execute('UPDATE required_work SET model = ? WHERE work_id = ?', ('altered', ident))
    with GoalBudget.open(path, total=limit, per_request=limit, allocations={'pilot': limit}) as goal:
        with pytest.raises(ContractError, match='differ'):
            goal.reserve('attempt', ident, 'pilot', tokens=150, cost_usd=0.15, required_id=ident, stage='judge', provider='stand-in', model='altered')
        with pytest.raises(ContractError, match='differ'):
            goal.reserve_run_set(ident, [{**assignment, 'work_id': ident, 'request_id': ident}])


def test_recover_rejects_journal_reservation_mismatch_without_releasing_budget(tmp_path):
    from qjig.journal import Journal, run_journaled

    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        goal.reserve('attempt', 'r', 'smoke', tokens=100, cost_usd=0.2)
        run_journaled(journal, call=lambda: ('ok', {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}),
                      request_id='r', stage='judge', provider='stand-in', model='m', input_sha256='a'*64,
                      intent_payload={'goal_attempt_id': 'attempt', 'reserve_tokens': 101, 'reserve_cost_usd': 0.2})
        with pytest.raises(ContractError, match='reservation'):
            goal.recover_receipt('attempt', journal)
        assert goal.actual_usage()['unknown_calls'] == 1
        with pytest.raises(BudgetExceeded, match='unknown'):
            goal.reserve('next', 'r2', 'smoke', tokens=1, cost_usd=0.01)


def test_recover_rejects_receipt_with_different_request_binding(tmp_path):
    from dataclasses import replace
    from qjig.journal import Journal

    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        goal.reserve('attempt', 'r', 'smoke', tokens=100, cost_usd=0.2)
        intent = journal.record_intent(request_id='r', stage='judge', provider='stand-in', model='m', input_sha256='a'*64,
                                       payload={'goal_attempt_id': 'attempt', 'reserve_tokens': 100, 'reserve_cost_usd': 0.2})
        journal.record_terminal(replace(intent, input_sha256='b'*64), 'receipt',
                                {'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}})
        with pytest.raises(ContractError, match='binding'):
            goal.recover_receipt('attempt', journal)
        assert goal.actual_usage()['unknown_calls'] == 1


def test_audit_journal_detects_orphans_and_usage_mismatch_without_mutating(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(4, 1000, 1)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='smoke')
        ledger.run('judge', lambda: ('ok', {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}),
                   provider='stand-in', model='m', input_sha256='a'*64,
                   reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        assert goal.audit_journal(journal) == {'status': 'verified', 'checked_attempts': 1, 'issues': []}
        goal.reserve('orphan', 'r2', 'smoke', tokens=100, cost_usd=0.2)
        report = goal.audit_journal(journal)
        assert report['status'] == 'incomplete' and 'missing_intent:orphan' in report['issues']
        journal.record_intent(request_id='untracked', stage='judge', provider='stand-in', model='m', input_sha256='b'*64)
        report = goal.audit_journal(journal)
        assert report['status'] == 'invalid' and 'untracked_intent:untracked#1' in report['issues']
        goal._con.execute("UPDATE usage SET cost='0.11' WHERE attempt_id != 'orphan'")
        report = goal.audit_journal(journal)
        assert report['status'] == 'invalid' and any(x.startswith('usage_mismatch:') for x in report['issues'])
        assert goal.actual_usage()['unknown_calls'] == 1


def test_audit_journal_rejects_orphan_and_duplicate_terminal_events(tmp_path):
    from qjig.journal import Event, Journal

    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        fake = Event('r', 1, 'r#missing', 'intent', 'judge', 'stand-in', 'm', 'a'*64, {}, 0)
        journal.record_terminal(fake, 'receipt', {'usage': {}})
        report = goal.audit_journal(journal)
        assert report['status'] == 'invalid' and 'orphan_terminal:r#missing' in report['issues']


def test_audit_journal_marks_duplicate_receipts_invalid(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='smoke')
        usage = {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}
        ledger.run('judge', lambda: ('ok', usage), provider='stand-in', model='m', input_sha256='a'*64,
                   reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        intent = journal.events('r')[0]
        journal.record_terminal(intent, 'receipt', {'usage': usage})
        report = goal.audit_journal(journal)
        assert report['status'] == 'invalid'
        assert any(x.startswith('duplicate_terminal:') for x in report['issues'])


def test_audit_journal_treats_malformed_attempt_identity_as_invalid(tmp_path):
    from qjig.journal import Journal
    limit = Budget(1, 100, 0.1)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        journal.record_intent(request_id='r', stage='judge', provider='stand-in', model='m', input_sha256='a'*64,
                              payload={'goal_attempt_id': ['not-a-string']})
        report = goal.audit_journal(journal)
        assert report['status'] == 'invalid' and 'untracked_intent:r#1' in report['issues']


def test_budgeted_dispatch_refuses_cross_store_mismatch_before_reservation(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        first = BudgetLedger(limit, journal, 'r1', goal_budget=goal, partition='smoke')
        first.run('judge', lambda: ('ok', {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}),
                  provider='stand-in', model='m', input_sha256='a'*64,
                  reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        goal._con.execute("UPDATE usage SET cost='0.11'")
        seen = []
        second = BudgetLedger(limit, journal, 'r2', goal_budget=goal, partition='smoke')
        with pytest.raises(BudgetExceeded, match='accounting'):
            second.run('judge', lambda: seen.append('called'), provider='stand-in', model='m', input_sha256='b'*64,
                       reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        assert seen == [] and journal.events('r2') == [] and goal.totals().max_calls == 1


def test_budgeted_dispatch_refuses_malformed_untracked_intent(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal
    limit = Budget(2, 500, 0.5)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        journal.record_intent(request_id='other', stage='judge', provider='stand-in', model='m', input_sha256='a'*64,
                              payload=['bad-payload'])
        seen = []
        with pytest.raises(BudgetExceeded, match='accounting'):
            BudgetLedger(limit, journal, 'r', goal_budget=goal, partition='smoke').run(
                'judge', lambda: seen.append('called'), provider='stand-in', model='m', input_sha256='b'*64,
                reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        assert seen == [] and goal.totals().max_calls == 0


@pytest.mark.parametrize('input_tokens,output_tokens', [(61, 10), (10, 41)])
def test_audit_rejects_individual_token_bound_overruns(tmp_path, input_tokens, output_tokens):
    from qjig.budgets import BudgetLedger
    from qjig.journal import Journal

    limit = Budget(3, 1000, 1)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal, Journal.open(tmp_path / 'j.sqlite') as journal:
        first = BudgetLedger(limit, journal, 'r1', goal_budget=goal, partition='smoke')
        first.run('judge', lambda: ('ok', {'prompt_tokens': input_tokens, 'completion_tokens': output_tokens, 'cost_usd': 0.1}),
                  provider='stand-in', model='m', input_sha256='a'*64,
                  reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        assert goal.audit_journal(journal)['status'] == 'invalid'
        seen = []
        second = BudgetLedger(limit, journal, 'r2', goal_budget=goal, partition='smoke')
        with pytest.raises(BudgetExceeded, match='accounting'):
            second.run('judge', lambda: seen.append('called'), provider='stand-in', model='m', input_sha256='b'*64,
                       reserve_tokens=40, reserve_input_tokens=60, reserve_cost_usd=0.2)
        assert seen == [] and journal.events('r2') == [] and goal.totals().max_calls == 1


@pytest.mark.parametrize('extra', [1e-30, 5e-324])
def test_required_work_costs_cannot_round_below_goal_cap(tmp_path, extra):
    limit = Budget(4, 1000, 1.0)
    with GoalBudget.open(tmp_path / 'g.sqlite', total=limit, per_request=limit, allocations={'smoke': limit}) as goal:
        with pytest.raises(BudgetExceeded):
            goal.reserve_required('r', 'smoke', [
                ('first', 1, 0.5, 'judge', 'stand-in', 'm'),
                ('second', 1, 0.5, 'judge', 'stand-in', 'm'),
                ('third', 1, extra, 'judge', 'stand-in', 'm'),
            ])
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0] == 0
