import pytest

from qjig.budgets import BudgetExceeded, BudgetLedger
from qjig.contracts import Budget
from qjig.journal import Journal, UncertainOutcome

H = "c" * 64


def run(ledger, stage, call=None, tokens=10, **kw):
    return ledger.run(stage, call or (lambda: ("ok", {"prompt_tokens": 4, "completion_tokens": 1, "cost_usd": None})),
                      provider="stand-in", model="stand-in-model", input_sha256=H, reserve_tokens=tokens, **kw)


def make(tmp_path, calls=3, tokens=1000, cost=1.0, name="j.sqlite"):
    j = Journal.open(tmp_path / name)
    return j, BudgetLedger(Budget(calls, tokens, cost), j, "req-1")


def test_physical_call_cap(tmp_path):
    j, ledger = make(tmp_path, calls=3)
    with j:
        run(ledger, "planner")
        with pytest.raises(RuntimeError):
            run(ledger, "repair", call=lambda: (_ for _ in ()).throw(RuntimeError("bad json")))  # a failed call still counts
        def timeout():
            raise UncertainOutcome("timeout after send")
        with pytest.raises(UncertainOutcome):
            run(ledger, "stability_probe", call=timeout)  # an uncertain call counts too
        assert ledger.used_calls() == 3 and ledger.remaining_calls() == 0
        # the final check, a fallback and an escalation all share the same cap: none may run
        invoked = []
        for stage in ("final_check", "fallback", "escalation"):
            with pytest.raises(BudgetExceeded) as exc:
                run(ledger, stage, call=lambda: invoked.append(1) or ("x", {}))
            assert exc.value.limit == "calls"
        assert invoked == [] and ledger.used_calls() == 3  # refused before any intent or call
    # the count survives a restart because it is derived from the journal
    with Journal.open(tmp_path / "j.sqlite") as j2:
        assert BudgetLedger(Budget(3, 1000, 1.0), j2, "req-1").used_calls() == 3
    # a different request has its own cap
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
        run(ledger, "planner")
        assert ledger.cost_status() == "unknown" and ledger.known_cost_usd() is None  # not 0.0
        run(ledger, "judge", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.4}))
        assert ledger.known_cost_usd() == 0.4 and ledger.cost_status() == "partially_unknown"
        run(ledger, "judge", call=lambda: ("ok", {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.2}))
        with pytest.raises(BudgetExceeded) as exc:  # known spend 0.6 already exceeds the requested 0.5
            run(ledger, "judge")
        assert exc.value.limit == "cost"
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
