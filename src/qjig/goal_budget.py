"""Persistent goal-wide reservation ledger; does not itself authorize provider calls.

Reservations are conservative and never released here. The caller must use one fixed
ledger for the whole goal; moving or replacing the file is not an accounting reset.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from .budgets import BudgetExceeded, _valid_cost, _valid_tokens
from .contracts import Budget, ContractError


def _cost(value: int | float) -> Decimal:
    return Decimal(str(value))


def _fits(used: tuple[int, int, Decimal], limit: Budget) -> bool:
    return used[0] <= limit.max_calls and used[1] <= limit.max_tokens and used[2] <= _cost(limit.max_cost_usd)


class GoalBudget:
    def __init__(self, con: sqlite3.Connection, total: Budget, per_request: Budget, allocations: dict[str, Budget]):
        self._con, self._total, self._per_request, self._allocations = con, total, per_request, allocations

    @classmethod
    def open(cls, path: str | Path, *, total: Budget, per_request: Budget, allocations: dict[str, Budget]) -> "GoalBudget":
        if not isinstance(total, Budget) or not isinstance(per_request, Budget) or not isinstance(allocations, dict) or not allocations:
            raise ContractError("goal, request and partition budgets are required")
        if not _fits((total.max_calls, total.max_tokens, _cost(total.max_cost_usd)), Budget(2000, 8000000, 25)):
            raise ContractError("goal budget exceeds contract ceiling")
        if not _fits((per_request.max_calls, per_request.max_tokens, _cost(per_request.max_cost_usd)), Budget(30, 160000, 1)):
            raise ContractError("request budget exceeds contract ceiling")
        if any(not isinstance(k, str) or not k.strip() or not isinstance(v, Budget) for k, v in allocations.items()):
            raise ContractError("invalid allocation")
        assigned = (sum(b.max_calls for b in allocations.values()), sum(b.max_tokens for b in allocations.values()),
                    sum((_cost(b.max_cost_usd) for b in allocations.values()), Decimal(0)))
        if not _fits(assigned, total):
            raise ContractError("partition allocations exceed total")
        policy = json.dumps({"total": total.to_dict(), "per_request": per_request.to_dict(),
                             "allocations": {k: v.to_dict() for k, v in allocations.items()}}, sort_keys=True, separators=(",", ":"))
        con = sqlite3.connect(str(path), isolation_level=None, timeout=10)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS reservations (attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, partition TEXT NOT NULL, tokens INTEGER NOT NULL, cost TEXT NOT NULL)")
            row = con.execute("SELECT value FROM policy WHERE id=1").fetchone()
            if row is None:
                con.execute("INSERT INTO policy VALUES(1, ?)", (policy,))
            elif row[0] != policy:
                raise ContractError("persisted goal budget policy differs")
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            con.close()
            raise
        return cls(con, total, per_request, dict(allocations))

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "GoalBudget":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _sum(rows) -> tuple[int, int, Decimal]:
        return len(rows), sum(row[0] for row in rows), sum((Decimal(row[1]) for row in rows), Decimal(0))

    def totals(self) -> Budget:
        count, tokens, cost = self._sum(self._con.execute("SELECT tokens, cost FROM reservations").fetchall())
        return Budget(count, tokens, float(cost))

    def reserve(self, attempt_id: str, request_id: str, partition: str, *, tokens: int, cost_usd: float) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (attempt_id, request_id, partition)):
            raise ContractError("reservation identities must be non-empty")
        if partition not in self._allocations or not _valid_tokens(tokens) or not _valid_cost(cost_usd):
            raise ContractError("invalid reservation")
        self._con.execute("BEGIN IMMEDIATE")
        try:
            if self._con.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ContractError("attempt already reserved")
            for label, query, args, limit in (
                ("goal", "SELECT tokens,cost FROM reservations", (), self._total),
                ("partition", "SELECT tokens,cost FROM reservations WHERE partition=?", (partition,), self._allocations[partition]),
                ("request", "SELECT tokens,cost FROM reservations WHERE request_id=?", (request_id,), self._per_request),
            ):
                n, t, c = self._sum(self._con.execute(query, args).fetchall())
                if not _fits((n + 1, t + tokens, c + _cost(cost_usd)), limit):
                    raise BudgetExceeded(label, "reservation exceeds persistent limit")
            self._con.execute("INSERT INTO reservations VALUES(?,?,?,?,?)", (attempt_id, request_id, partition, tokens, str(_cost(cost_usd))))
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
