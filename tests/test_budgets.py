import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget
from qjig.journal import Journal, UncertainOutcome

H = "c" * 64


def run(ledger, stage, call=None, tokens=10, **kw):
    return ledger.run(stage, call or (lambda: ("ok", {"prompt_tokens": 4, "completion_tokens": 1, "cost_usd": 0.0})),
                      provider="stand-in", model="stand-in-model", input_sha256=H, reserve_tokens=tokens, **kw)


def make(tmp_path, calls=3, tokens=1000, cost=1.0, name="j.sqlite"):
    j = Journal.open(tmp_path / name)
    return j, BudgetLedger(Budget(calls, tokens, cost), j, "req-1")


def test_physical_call_cap(tmp_path):
    j, ledger = make(tmp_path, calls=3)
    with j:
        for stage in ("planner", "repair", "stability_probe"):
            run(ledger, stage)
        assert ledger.used_calls() == 3 and ledger.remaining_calls() == 0
        invoked = []
        for stage in ("final_check", "fallback", "escalation"):
            with pytest.raises(BudgetExceeded) as exc:
                run(ledger, stage, call=lambda: invoked.append(1))
            assert exc.value.limit == "calls"
        assert invoked == []
    with Journal.open(tmp_path / "j.sqlite") as j2:
        assert BudgetLedger(Budget(3, 1000, 1.0), j2, "req-1").used_calls() == 3
        assert BudgetLedger(Budget(3, 1000, 1.0), j2, "req-2").used_calls() == 0


def test_hold_back_reserves_room_for_required_later_calls(tmp_path):
    j, ledger = make(tmp_path, calls=3)
    with j:
        with pytest.raises(BudgetExceeded):
            run(ledger, "planner", hold_back_calls=3)  # planner + 3 reserved would be 4
        assert ledger.used_calls() == 0
        run(ledger, "planner", hold_back_calls=2)  # leaves room for repair + final check
        assert ledger.remaining_calls() == 2


def test_token_cap_uses_declared_reservation_then_actuals(tmp_path):
    j, ledger = make(tmp_path, tokens=100)
    with j:
        run(ledger, "planner", tokens=60)  # actual use 5 tokens is reported in the receipt
        assert ledger.committed_tokens() == 5
        run(ledger, "judge", tokens=60)  # fits because the first call really used only 5
        assert ledger.committed_tokens() == 10  # two calls that each really used 5 tokens
        with pytest.raises(BudgetExceeded) as exc:
            run(ledger, "judge", tokens=95)  # 10 committed + 95 reserved > 100
        assert exc.value.limit == "tokens"
        # a failed call has unknown usage: its full reservation stays committed, not zero
        j2, l2 = make(tmp_path, tokens=100, name="k.sqlite")
        with j2:
            with pytest.raises(RuntimeError):
                run(l2, "planner", tokens=70, call=lambda: (_ for _ in ()).throw(RuntimeError("x")))
            assert l2.committed_tokens() == 70
            with pytest.raises(BudgetExceeded):
                run(l2, "judge", tokens=40)


def test_unknown_cost_is_not_zero_and_missing_or_zero_budget_authorizes_nothing(tmp_path):
    j, ledger = make(tmp_path, calls=10, cost=0.5)
    with j:
        run(ledger, "known", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.4}))
        run(ledger, "unknown", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": None}))
        assert ledger.known_cost_usd() == 0.4 and ledger.cost_status() == "partially_unknown"
        with pytest.raises(BudgetExceeded) as exc:
            run(ledger, "judge")
        assert exc.value.limit == "cost_unknown"
    for budget in (None, Budget(0, 0, 0)):
        with Journal.open(tmp_path / "z.sqlite") as jz:
            with pytest.raises(BudgetExceeded):
                BudgetLedger(budget, jz, "req-9").run("planner", lambda: ("x", {}), provider="p", model="m", input_sha256=H, reserve_tokens=1)
            assert jz.events("req-9") == []


@pytest.mark.parametrize("usage", [
    {"prompt_tokens": -1, "completion_tokens": 1, "cost_usd": 0.1},
    {"prompt_tokens": 1, "completion_tokens": True, "cost_usd": 0.1},
    {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": float("nan")},
    {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": -1},
    {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": float("inf")},
])
def test_invalid_usage_stays_unknown_and_reservation_is_preserved(tmp_path, usage):
    j, ledger = make(tmp_path)
    with j:
        run(ledger, "planner", tokens=20, call=lambda: ("ok", usage))
        if type(usage["prompt_tokens"]) is not int or usage["prompt_tokens"] < 0 or type(usage["completion_tokens"]) is not int:
            assert ledger.committed_tokens() == 20
        if not (0 <= usage["cost_usd"] < float("inf")):
            assert ledger.known_cost_usd() is None
            assert ledger.cost_status() == "unknown"


def test_unknown_cost_blocks_further_calls_after_restart(tmp_path):
    j, ledger = make(tmp_path, calls=4)
    with j:
        run(ledger, "first", call=lambda: ("ok", {"prompt_tokens": 2, "completion_tokens": 1, "cost_usd": None}))
        assert ledger.cost_status() == "unknown"
    with Journal.open(tmp_path / "j.sqlite") as reopened:
        resumed = BudgetLedger(Budget(4, 1000, 1), reopened, "req-1")
        invoked = []
        with pytest.raises(BudgetExceeded) as error:
            run(resumed, "next", call=lambda: invoked.append(True))
        assert error.value.limit == "cost_unknown"
        assert invoked == [] and resumed.used_calls() == 1


@pytest.mark.parametrize("error", [RuntimeError("failed"), UncertainOutcome("uncertain")])
def test_failed_and_uncertain_calls_count_and_block_unknown_cost(tmp_path, error):
    j, ledger = make(tmp_path, calls=3)
    with j:
        with pytest.raises(type(error)):
            run(ledger, "planner", call=lambda: (_ for _ in ()).throw(error))
        assert ledger.used_calls() == 1 and ledger.cost_status() == "unknown"
        with pytest.raises(BudgetExceeded, match="cost_unknown"):
            run(ledger, "repair")
        assert ledger.used_calls() == 1


def test_known_spend_at_cap_blocks_call(tmp_path):
    j, ledger = make(tmp_path, cost=0.5)
    with j:
        run(ledger, "planner", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.5}))
        with pytest.raises(BudgetExceeded) as error:
            run(ledger, "judge")
        assert error.value.limit == "cost"


@pytest.mark.parametrize("kwargs", [
    {"tokens": -1}, {"tokens": True}, {"reserve_input_tokens": -1}, {"reserve_input_tokens": True}, {"hold_back_calls": -1}, {"hold_back_tokens": -1},
])
def test_invalid_reservations_never_dispatch(tmp_path, kwargs):
    from qjig.contracts import ContractError
    j, ledger = make(tmp_path)
    with j:
        invoked = []
        with pytest.raises(ContractError):
            run(ledger, "planner", call=lambda: invoked.append(True), **kwargs)
        assert invoked == [] and j.events("req-1") == []


def test_cost_reservation_includes_required_held_back_work(tmp_path):
    j, ledger = make(tmp_path, calls=5, cost=0.5)
    with j:
        run(ledger, "first", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.2}), reserve_cost_usd=0.2)
        invoked = []
        with pytest.raises(BudgetExceeded) as exc:
            run(ledger, "planner", call=lambda: invoked.append(True), reserve_cost_usd=0.2, hold_back_cost_usd=0.11)
        assert exc.value.limit == "cost"
        assert not invoked and ledger.used_calls() == 1
        run(ledger, "planner", reserve_cost_usd=0.2, hold_back_cost_usd=0.1)
        intent = [e for e in j.events("req-1") if e.kind == "intent"][-1]
        assert intent.payload["reserve_cost_usd"] == 0.2
        assert intent.payload["hold_back_cost_usd"] == 0.1


@pytest.mark.parametrize("reservation", [-1, True, float("nan"), float("inf")])
def test_invalid_cost_reservation_never_dispatches(tmp_path, reservation):
    from qjig.contracts import ContractError
    j, ledger = make(tmp_path)
    with j:
        invoked = []
        with pytest.raises(ContractError):
            run(ledger, "planner", call=lambda: invoked.append(True), reserve_cost_usd=reservation)
        assert not invoked and j.events("req-1") == []


def test_held_back_cost_requires_call_cost_bound(tmp_path):
    from qjig.contracts import ContractError
    j, ledger = make(tmp_path)
    with j:
        with pytest.raises(ContractError):
            run(ledger, "planner", hold_back_cost_usd=0.1)
        assert j.events("req-1") == []


def test_input_output_and_held_back_tokens_are_reserved_together(tmp_path):
    j, ledger = make(tmp_path, tokens=100)
    with j:
        invoked = []
        with pytest.raises(BudgetExceeded) as error:
            run(ledger, "planner", tokens=50, reserve_input_tokens=40, hold_back_tokens=11,
                call=lambda: invoked.append(True))
        assert error.value.limit == "tokens" and not invoked and j.events("req-1") == []
        run(ledger, "planner", tokens=50, reserve_input_tokens=40, hold_back_tokens=10)
        intent = next(e for e in j.events("req-1") if e.kind == "intent")
        assert intent.payload["reserve_tokens"] == 90
        assert intent.payload["reserve_input_tokens"] == 40
        assert intent.payload["reserve_output_tokens"] == 50
