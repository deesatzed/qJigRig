"""Request-wide spend accounting derived from the journal. Every physical attempt counts.

Planner, repair, stability probes, final checks, fallback and escalation all share one cap.
Unknown historical cost blocks further calls; preflight cost reservations are still required.
"""
from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Any, Callable

from .contracts import Budget, ContractError
from .journal import Event, Journal, run_journaled


def _valid_tokens(value: Any) -> bool:
    return type(value) is int and value >= 0


def _valid_cost(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class BudgetExceeded(Exception):
    def __init__(self, limit: str, detail: str) -> None:
        super().__init__(f"{limit} budget: {detail}")
        self.limit = limit


class BudgetLedger:
    def __init__(self, budget: Budget | None, journal: Journal, request_id: str, *, goal_budget=None, partition: str | None = None) -> None:
        if (goal_budget is None) != (partition is None) or (partition is not None and (not isinstance(partition, str) or not partition.strip())):
            raise ContractError("goal ledger and partition must be configured together")
        self.budget, self._journal, self._request_id = budget, journal, request_id
        self._goal_budget, self._partition = goal_budget, partition

    # --- derived from the journal, so it survives restarts ---
    def _calls(self) -> list[tuple[Event, list[Event]]]:
        events = self._journal.events(self._request_id)
        out = []
        for intent in (e for e in events if e.kind == "intent"):
            rest = [e for e in events if e.call_id == intent.call_id and e.kind != "intent"]
            verified_not_run = any(e.kind == "reconciled" and e.payload.get("resolution") == "not_executed" for e in rest)
            if not verified_not_run:  # unresolved, failed, uncertain and executed calls all count
                out.append((intent, rest))
        return out

    def used_calls(self) -> int:
        return len(self._calls())

    def remaining_calls(self) -> int:
        return max(0, (self.budget.max_calls if self.budget else 0) - self.used_calls())

    def committed_tokens(self) -> int:
        total = 0
        for intent, rest in self._calls():
            receipt = next((e for e in rest if e.kind == "receipt"), None)
            usage = receipt.payload.get("usage", {}) if receipt else {}
            p, c = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if _valid_tokens(p) and _valid_tokens(c):
                total += p + c
            else:  # failed, uncertain, unresolved or unreported usage: keep the whole reservation
                total += int(intent.payload.get("reserve_tokens", 0))
        return total

    def known_cost_usd(self) -> float | None:
        calls = self._calls()
        if not calls:
            return 0.0
        costs = []
        for _, rest in calls:
            receipt = next((e for e in rest if e.kind == "receipt"), None)
            c = receipt.payload.get("usage", {}).get("cost_usd") if receipt else None
            if _valid_cost(c):
                costs.append(c)
        return round(sum(costs), 10) if costs else None

    def cost_status(self) -> str:
        calls = self._calls()
        known = 0
        for _, rest in calls:
            receipt = next((e for e in rest if e.kind == "receipt"), None)
            if receipt and _valid_cost(receipt.payload.get("usage", {}).get("cost_usd")):
                known += 1
        if known == len(calls):
            return "known"
        return "unknown" if known == 0 else "partially_unknown"

    def last_call_id(self) -> str:
        """Call id of the most recent journaled event for this request (single writer)."""
        return self._journal.events(self._request_id)[-1].call_id

    def run(
        self, stage: str, call: Callable[[], Any], *, provider: str, model: str, input_sha256: str,
        reserve_tokens: int, reserve_input_tokens: int | None = None, hold_back_calls: int = 0, hold_back_tokens: int = 0,
        reserve_cost_usd: float | None = None, hold_back_cost_usd: float = 0, reservation_binding: dict | None = None,
    ) -> Any:
        """Check every cap, then journal the intent and make the call. Refusals happen before any intent."""
        if self._goal_budget is not None and (reserve_input_tokens is None or reserve_cost_usd is None):
            raise BudgetExceeded("preflight_unavailable", "goal accounting requires input and cost bounds")
        reserve_input_tokens = 0 if reserve_input_tokens is None else reserve_input_tokens
        for name, value in (("reserve_tokens", reserve_tokens), ("reserve_input_tokens", reserve_input_tokens), ("hold_back_calls", hold_back_calls), ("hold_back_tokens", hold_back_tokens)):
            if not _valid_tokens(value):
                raise ContractError(f"{name} must be a non-negative integer")
        if reserve_cost_usd is not None and not _valid_cost(reserve_cost_usd):
            raise ContractError("reserve_cost_usd must be finite and non-negative")
        if not _valid_cost(hold_back_cost_usd):
            raise ContractError("hold_back_cost_usd must be finite and non-negative")
        if reserve_cost_usd is None and hold_back_cost_usd:
            raise ContractError("held-back cost requires a call cost bound")
        if self.budget is None:
            raise BudgetExceeded("calls", "no budget was provided, so no external work is authorized")
        if self.used_calls() + 1 + hold_back_calls > self.budget.max_calls:
            raise BudgetExceeded("calls", f"{self.used_calls()} used of {self.budget.max_calls}; {stage} needs 1 plus {hold_back_calls} held back")
        if self.committed_tokens() + reserve_input_tokens + reserve_tokens + hold_back_tokens > self.budget.max_tokens:
            raise BudgetExceeded("tokens", f"{self.committed_tokens()} committed of {self.budget.max_tokens}; {stage} reserves {reserve_tokens}")
        if self.cost_status() != "known":
            raise BudgetExceeded("cost_unknown", "previous call has unknown cost; further calls are not authorized")
        known = self.known_cost_usd()
        if known is not None and known >= self.budget.max_cost_usd:
            raise BudgetExceeded("cost", f"known cost {known} has reached the requested cap {self.budget.max_cost_usd}")
        if reserve_cost_usd is not None:
            spent = sum((Decimal(str(e.payload.get("usage", {}).get("cost_usd")))
                         for _, rest in self._calls() for e in rest if e.kind == "receipt"), Decimal(0))
            if spent + Decimal(str(reserve_cost_usd)) + Decimal(str(hold_back_cost_usd)) > Decimal(str(self.budget.max_cost_usd)):
                raise BudgetExceeded("cost", "reserved work exceeds cost cap")
        goal_attempt_id = None
        if self._goal_budget is not None:
            goal_attempt_id = uuid.uuid4().hex
            self._goal_budget.reserve(goal_attempt_id, self._request_id, self._partition,
                                      tokens=reserve_input_tokens + reserve_tokens, cost_usd=reserve_cost_usd,
                                      hold_back_calls=hold_back_calls, hold_back_tokens=hold_back_tokens,
                                      hold_back_cost_usd=hold_back_cost_usd)
        result = run_journaled(
            self._journal, call=call, request_id=self._request_id, stage=stage, provider=provider, model=model,
            input_sha256=input_sha256, intent_payload={"reserve_tokens": reserve_input_tokens + reserve_tokens,
                                                       "reserve_input_tokens": reserve_input_tokens, "reserve_output_tokens": reserve_tokens,
                                                       "reserve_cost_usd": reserve_cost_usd,
                                                       "hold_back_cost_usd": hold_back_cost_usd, "goal_attempt_id": goal_attempt_id,
                                                       "reservation_binding": reservation_binding},
        )
        if goal_attempt_id is not None:
            receipt = self._journal.events(self._request_id)[-1]
            usage = receipt.payload.get("usage", {})
            inp, out, cost = usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("cost_usd")
            self._goal_budget.record_usage(goal_attempt_id, input_tokens=inp if _valid_tokens(inp) else None,
                                           output_tokens=out if _valid_tokens(out) else None,
                                           cost_usd=cost if _valid_cost(cost) else None)
        return result
