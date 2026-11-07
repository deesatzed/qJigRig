"""Persistent goal-wide reservation ledger; does not itself authorize provider calls.

Original reservations remain recorded; complete usage commits actuals, while unknown
usage retains the bound. One fixed ledger must cover the whole goal.
"""
from __future__ import annotations

import hashlib
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
            con.execute("CREATE TABLE IF NOT EXISTS usage (attempt_id TEXT PRIMARY KEY REFERENCES reservations(attempt_id), input_tokens INTEGER, output_tokens INTEGER, cost TEXT)")
            con.execute("CREATE TABLE IF NOT EXISTS holds (attempt_id TEXT PRIMARY KEY REFERENCES reservations(attempt_id), calls INTEGER NOT NULL, tokens INTEGER NOT NULL, cost TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS recoveries (attempt_id TEXT PRIMARY KEY REFERENCES reservations(attempt_id), call_id TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS required_work (work_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, partition TEXT NOT NULL, tokens INTEGER NOT NULL, cost TEXT NOT NULL, attempt_id TEXT UNIQUE)")
            columns = {row[1] for row in con.execute("PRAGMA table_info(required_work)")}
            for column in ("stage", "provider", "model"):
                if column not in columns:
                    con.execute(f"ALTER TABLE required_work ADD COLUMN {column} TEXT")
            con.execute("CREATE TABLE IF NOT EXISTS run_sets (set_id TEXT PRIMARY KEY, manifest TEXT NOT NULL, sha256 TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS run_set_work (set_id TEXT NOT NULL REFERENCES run_sets(set_id), work_id TEXT UNIQUE NOT NULL REFERENCES required_work(work_id), PRIMARY KEY(set_id,work_id))")
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

    @staticmethod
    def _committed_rows(rows) -> tuple[int, int, Decimal]:
        tokens = 0
        cost = Decimal(0)
        for bound, bound_cost, inp, out, actual_cost in rows:
            if inp is None or out is None or actual_cost is None:
                tokens += bound
                cost += Decimal(bound_cost)
            else:
                tokens += inp + out
                cost += Decimal(actual_cost)
        return len(rows), tokens, cost

    def committed(self) -> Budget:
        rows = self._con.execute("SELECT r.tokens,r.cost,u.input_tokens,u.output_tokens,u.cost FROM reservations r LEFT JOIN usage u ON r.attempt_id=u.attempt_id").fetchall()
        count, tokens, cost = self._committed_rows(rows)
        return Budget(count, tokens, float(cost))

    def record_usage(self, attempt_id: str, *, input_tokens: int | None, output_tokens: int | None, cost_usd: float | None) -> None:
        """Record one observed outcome; missing fields remain unknown and never release reservations."""
        if ((input_tokens is not None and not _valid_tokens(input_tokens)) or
            (output_tokens is not None and not _valid_tokens(output_tokens)) or
            (cost_usd is not None and not _valid_cost(cost_usd))):
            raise ContractError("invalid actual usage")
        self._con.execute("BEGIN IMMEDIATE")
        try:
            if not self._con.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ContractError("unknown reservation")
            if self._con.execute("SELECT 1 FROM usage WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ContractError("usage already recorded")
            self._con.execute("INSERT INTO usage VALUES(?,?,?,?)", (attempt_id, input_tokens, output_tokens,
                              str(_cost(cost_usd)) if cost_usd is not None else None))
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise

    def recover_receipt(self, attempt_id: str, journal) -> str:
        """Recover from a matching journal receipt, without making or retrying a call.

        The caller must supply the original trusted journal. A hash binds the recorded
        recovery to the receipt but does not authenticate the journal or its contents.
        """
        row = self._con.execute("SELECT request_id FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone()
        if row is None:
            raise ContractError("unknown reservation")
        events = journal.events(row[0])
        intents = [e for e in events if e.kind == "intent" and e.payload.get("goal_attempt_id") == attempt_id]
        if len(intents) != 1:
            raise ContractError("no unique matching journal intent")
        intent = intents[0]
        terminal = [e for e in events if e.call_id == intent.call_id and e.kind in ("receipt", "failure", "uncertain", "reconciled")]
        if len(terminal) != 1 or terminal[0].kind != "receipt":
            raise ContractError("no unique completed journal receipt")
        receipt = terminal[0]
        usage = receipt.payload.get("usage")
        if not isinstance(usage, dict):
            raise ContractError("receipt usage is not an object")
        inp, out, cost = usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("cost_usd")
        inp = inp if _valid_tokens(inp) else None
        out = out if _valid_tokens(out) else None
        cost = cost if _valid_cost(cost) else None
        receipt_data = json.dumps({"call_id": receipt.call_id, "input_sha256": receipt.input_sha256,
                                   "payload": receipt.payload, "recorded_at": receipt.recorded_at},
                                  sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(receipt_data.encode("utf-8")).hexdigest()
        self._con.execute("BEGIN IMMEDIATE")
        try:
            if self._con.execute("SELECT 1 FROM usage WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ContractError("usage already recorded")
            self._con.execute("INSERT INTO usage VALUES(?,?,?,?)", (attempt_id, inp, out, str(_cost(cost)) if cost is not None else None))
            self._con.execute("INSERT INTO recoveries VALUES(?,?,?)", (attempt_id, receipt.call_id, digest))
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        return receipt.call_id

    def actual_usage(self) -> dict:
        rows = self._con.execute("SELECT u.input_tokens, u.output_tokens, u.cost FROM reservations r LEFT JOIN usage u ON r.attempt_id=u.attempt_id").fetchall()
        known_input = sum(r[0] for r in rows if r[0] is not None)
        known_output = sum(r[1] for r in rows if r[1] is not None)
        known_cost = float(sum((Decimal(r[2]) for r in rows if r[2] is not None), Decimal(0)))
        return {"calls": len(rows),
                "input_tokens": known_input if all(r[0] is not None for r in rows) else None,
                "output_tokens": known_output if all(r[1] is not None for r in rows) else None,
                "cost_usd": known_cost if all(r[2] is not None for r in rows) else None,
                "known_input_tokens": known_input, "known_output_tokens": known_output,
                "known_cost_usd": known_cost,
                "unknown_calls": sum(any(v is None for v in row) for row in rows)}

    def _check_capacity(self, request_id: str, partition: str, calls: int, tokens: int, cost: Decimal,
                        exclude_required: str | None = None) -> None:
        for label, condition, args, limit in (
            ("goal", "1=1", (), self._total),
            ("partition", "r.partition=?", (partition,), self._allocations[partition]),
            ("request", "r.request_id=?", (request_id,), self._per_request),
        ):
            rows = self._con.execute("SELECT r.tokens,r.cost,u.input_tokens,u.output_tokens,u.cost FROM reservations r LEFT JOIN usage u ON r.attempt_id=u.attempt_id WHERE " + condition, args).fetchall()
            n, t, c = self._committed_rows(rows)
            pending = self._con.execute("SELECT r.tokens,r.cost FROM required_work r WHERE r.attempt_id IS NULL AND " + condition + " AND (? IS NULL OR r.work_id != ?)", (*args, exclude_required, exclude_required)).fetchall()
            pn, pt, pc = self._sum(pending)
            if not _fits((n + pn + calls, t + pt + tokens, c + pc + cost), limit):
                raise BudgetExceeded(label, "reservation exceeds persistent limit")

    def reserve_required(self, request_id: str, partition: str, work: list[tuple[str, int, float, str, str, str]]) -> None:
        """Atomically reserve named future calls; consumed only by their matching request."""
        if any(not isinstance(v, str) or not v.strip() for v in (request_id, partition)) or partition not in self._allocations:
            raise ContractError("invalid required work identity")
        if not isinstance(work, list) or not work:
            raise ContractError("required work must be nonempty")
        normalized = []
        for item in work:
            if not isinstance(item, (tuple, list)) or len(item) != 6:
                raise ContractError("invalid required work")
            ident, tokens, cost, stage, provider, model = item
            if (any(not isinstance(v, str) or not v.strip() for v in (ident, stage, provider, model))
                    or not _valid_tokens(tokens) or not _valid_cost(cost)):
                raise ContractError("invalid required work")
            normalized.append((ident, tokens, _cost(cost), stage, provider, model))
        if len({item[0] for item in normalized}) != len(normalized):
            raise ContractError("duplicate required work")
        self._con.execute("BEGIN IMMEDIATE")
        try:
            if any(self._con.execute("SELECT 1 FROM required_work WHERE work_id=?", (item[0],)).fetchone() for item in normalized):
                raise ContractError("required work already exists")
            self._check_capacity(request_id, partition, len(normalized), sum(item[1] for item in normalized),
                                 sum((item[2] for item in normalized), Decimal(0)))
            self._con.executemany("INSERT INTO required_work (work_id,request_id,partition,tokens,cost,stage,provider,model) VALUES(?,?,?,?,?,?,?,?)",
                                  [(ident, request_id, partition, tokens, str(cost), stage, provider, model)
                                   for ident, tokens, cost, stage, provider, model in normalized])
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise

    def _verify_run_set(self, set_id: str, manifest: str, digest: str) -> None:
        if hashlib.sha256(manifest.encode("utf-8")).hexdigest() != digest:
            raise ContractError("run set digest differs from manifest")
        try:
            items = json.loads(manifest)
            expected = [(x["work_id"], x["request_id"], x["partition"], x["tokens"], x["cost_usd"], x["stage"], x["provider"], x["model"]) for x in items]
        except (ValueError, TypeError, KeyError):
            raise ContractError("run set manifest is invalid") from None
        rows = self._con.execute("SELECT w.work_id,w.request_id,w.partition,w.tokens,w.cost,w.stage,w.provider,w.model FROM run_set_work s JOIN required_work w ON w.work_id=s.work_id WHERE s.set_id=? ORDER BY w.work_id", (set_id,)).fetchall()
        if rows != expected:
            raise ContractError("run set allocations differ from frozen manifest")

    def reserve_run_set(self, set_id: str, assignments: list[dict]) -> str:
        """Freeze and reserve every declared physical call together, or reserve none.

        Call bounds and identities are supplied assertions; this does not verify prices,
        tokenization, experiment coverage, or the authenticity of the database.
        """
        if not isinstance(set_id, str) or not set_id.strip() or not isinstance(assignments, list) or not assignments:
            raise ContractError("run set identity and assignments are required")
        keys = {"work_id", "request_id", "partition", "tokens", "cost_usd", "stage", "provider", "model"}
        normalized = []
        for item in assignments:
            if not isinstance(item, dict) or set(item) != keys:
                raise ContractError("invalid run set assignment fields")
            if any(not isinstance(item[k], str) or not item[k].strip() for k in ("work_id", "request_id", "partition", "stage", "provider", "model")):
                raise ContractError("invalid run set assignment identity")
            if item["partition"] not in self._allocations or not _valid_tokens(item["tokens"]) or not _valid_cost(item["cost_usd"]):
                raise ContractError("invalid run set assignment budget")
            normalized.append({**item, "cost_usd": str(_cost(item["cost_usd"]))})
        if len({item["work_id"] for item in normalized}) != len(normalized):
            raise ContractError("duplicate run set work identity")
        normalized.sort(key=lambda item: item["work_id"])
        manifest = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
        self._con.execute("BEGIN IMMEDIATE")
        try:
            existing = self._con.execute("SELECT manifest,sha256 FROM run_sets WHERE set_id=?", (set_id,)).fetchone()
            if existing is not None:
                if existing != (manifest, digest):
                    raise ContractError("run set differs from frozen manifest")
                self._verify_run_set(set_id, manifest, digest)
                self._con.execute("COMMIT")
                return digest
            self._con.execute("INSERT INTO run_sets VALUES(?,?,?)", (set_id, manifest, digest))
            for x in normalized:
                if self._con.execute("SELECT 1 FROM required_work WHERE work_id=?", (x["work_id"],)).fetchone():
                    raise ContractError("required work already exists")
                self._check_capacity(x["request_id"], x["partition"], 1, x["tokens"], Decimal(x["cost_usd"]))
                self._con.execute("INSERT INTO required_work (work_id,request_id,partition,tokens,cost,stage,provider,model) VALUES(?,?,?,?,?,?,?,?)",
                                  tuple(x[k] for k in ("work_id", "request_id", "partition", "tokens", "cost_usd", "stage", "provider", "model")))
                self._con.execute("INSERT INTO run_set_work VALUES(?,?)", (set_id, x["work_id"]))
            self._con.execute("COMMIT")
            return digest
        except BaseException:
            self._con.execute("ROLLBACK")
            raise

    def reserve(self, attempt_id: str, request_id: str, partition: str, *, tokens: int, cost_usd: float,
                hold_back_calls: int = 0, hold_back_tokens: int = 0, hold_back_cost_usd: float = 0,
                required_id: str | None = None, stage: str | None = None, provider: str | None = None,
                model: str | None = None) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (attempt_id, request_id, partition)):
            raise ContractError("reservation identities must be non-empty")
        if (partition not in self._allocations or not _valid_tokens(tokens) or not _valid_cost(cost_usd)
                or not _valid_tokens(hold_back_calls) or not _valid_tokens(hold_back_tokens) or not _valid_cost(hold_back_cost_usd)):
            raise ContractError("invalid reservation")
        self._con.execute("BEGIN IMMEDIATE")
        try:
            for set_id, manifest, digest in self._con.execute("SELECT set_id,manifest,sha256 FROM run_sets").fetchall():
                self._verify_run_set(set_id, manifest, digest)
            if self._con.execute("SELECT 1 FROM reservations WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise ContractError("attempt already reserved")
            if required_id is not None:
                if not isinstance(required_id, str) or not required_id.strip():
                    raise ContractError("invalid required work identity")
                required = self._con.execute("SELECT request_id,partition,tokens,cost,attempt_id,stage,provider,model FROM required_work WHERE work_id=?", (required_id,)).fetchone()
                if (required is None or required[0] != request_id or required[1] != partition or required[4] is not None
                        or any(not isinstance(v, str) or not v.strip() for v in (stage, provider, model))
                        or (stage, provider, model) != required[5:8]
                        or tokens > required[2] or _cost(cost_usd) > Decimal(required[3])):
                    raise ContractError("required work does not match reservation")
            previous = self._con.execute("SELECT r.tokens, r.cost, u.input_tokens, u.output_tokens, u.cost FROM reservations r LEFT JOIN usage u ON r.attempt_id=u.attempt_id").fetchall()
            if any(i is None or o is None or c is None for _, _, i, o, c in previous):
                raise BudgetExceeded("usage_unknown", "previous call has unknown or pending usage")
            if any(i + o > bound or Decimal(c) > Decimal(cost) for bound, cost, i, o, c in previous):
                raise BudgetExceeded("bound_exceeded", "observed usage exceeded its reservation")
            self._check_capacity(request_id, partition, 1 + hold_back_calls, tokens + hold_back_tokens,
                                 _cost(cost_usd) + _cost(hold_back_cost_usd), required_id)
            self._con.execute("INSERT INTO reservations VALUES(?,?,?,?,?)", (attempt_id, request_id, partition, tokens, str(_cost(cost_usd))))
            self._con.execute("INSERT INTO holds VALUES(?,?,?,?)", (attempt_id, hold_back_calls, hold_back_tokens, str(_cost(hold_back_cost_usd))))
            if required_id is not None:
                self._con.execute("UPDATE required_work SET attempt_id=? WHERE work_id=?", (attempt_id, required_id))
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
