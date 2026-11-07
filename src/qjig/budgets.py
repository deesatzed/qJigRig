"""Request-wide spend accounting derived from the journal. Every physical attempt counts.

Planner, repair, stability probes, final checks, fallback and escalation all share one cap.
Dollar limits are the requester's cap checked against KNOWN cost only; they are not provider-enforced.
"""
from __future__ import annotations

from typing import Any, Callable

from .contracts import Budget
from .journal import Event, Journal, run_journaled


class BudgetExceeded(Exception):
    def __init__(self, limit: str, detail: str) -> None:
        super().__init__(f"{limit} budget: {detail}")
        self.limit = limit


class BudgetLedger:
    def __init__(self, budget: Budget | None, journal: Journal, request_id: str) -> None:
        self.budget, self._journal, self._request_id = budget, journal, request_id

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
            if type(p) is int and type(c) is int:
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
            if c is not None:
                costs.append(c)
        return round(sum(costs), 10) if costs else None

    def cost_status(self) -> str:
        calls = self._calls()
        known = 0
        for _, rest in calls:
            receipt = next((e for e in rest if e.kind == "receipt"), None)
            if receipt and receipt.payload.get("usage", {}).get("cost_usd") is not None:
                known += 1
        if known == len(calls):
            return "known"
        return "unknown" if known == 0 else "partially_unknown"

    def run(
        self, stage: str, call: Callable[[], Any], *, provider: str, model: str, input_sha256: str,
        reserve_tokens: int, hold_back_calls: int = 0, hold_back_tokens: int = 0,
    ) -> Any:
        """Check every cap, then journal the intent and make the call. Refusals happen before any intent."""
        if self.budget is None:
            raise BudgetExceeded("calls", "no budget was provided, so no external work is authorized")
        if self.used_calls() + 1 + hold_back_calls > self.budget.max_calls:
            raise BudgetExceeded("calls", f"{self.used_calls()} used of {self.budget.max_calls}; {stage} needs 1 plus {hold_back_calls} held back")
        if self.committed_tokens() + reserve_tokens + hold_back_tokens > self.budget.max_tokens:
            raise BudgetExceeded("tokens", f"{self.committed_tokens()} committed of {self.budget.max_tokens}; {stage} reserves {reserve_tokens}")
        known = self.known_cost_usd()
        if known is not None and known >= self.budget.max_cost_usd:
            raise BudgetExceeded("cost", f"known cost {known} has reached the requested cap {self.budget.max_cost_usd}")
        return run_journaled(
            self._journal, call=call, request_id=self._request_id, stage=stage, provider=provider, model=model,
            input_sha256=input_sha256, intent_payload={"reserve_tokens": reserve_tokens},
        )
