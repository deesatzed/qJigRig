"""Append-only call journal. An intent is durable BEFORE any provider side effect."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError

_SCHEMA = """
CREATE TABLE events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  request_seq INTEGER NOT NULL,
  call_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('intent','receipt','failure','uncertain','reconciled')),
  stage TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_sha256 TEXT NOT NULL,
  payload TEXT NOT NULL,
  recorded_at REAL NOT NULL,
  UNIQUE(request_id, request_seq)
);
CREATE INDEX events_call ON events(call_id);
CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'journal is append-only'); END;
PRAGMA user_version = 1;
"""
_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Event:
    request_id: str
    request_seq: int
    call_id: str
    kind: str
    stage: str
    provider: str
    model: str
    input_sha256: str
    payload: dict[str, Any]
    recorded_at: float


class UncertainOutcome(Exception):
    """Raised by a transport when it cannot tell whether the provider executed the call."""


class ReconciliationRequired(Exception):
    """An earlier identical call is unresolved; repeating it blindly could be a second paid call."""


@dataclass(frozen=True)
class ResumeReport:
    unresolved: tuple[Event, ...]
    reconciliation_required: bool


class Journal:
    def __init__(self, con: sqlite3.Connection, clock: Callable[[], float]) -> None:
        self._con, self._clock = con, clock

    @classmethod
    def open(cls, path: str | Path, clock: Callable[[], float] = time.time) -> "Journal":
        con = sqlite3.connect(str(path), isolation_level=None)  # explicit transactions below
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            con.executescript(_SCHEMA)
        elif version != 1:
            con.close()
            raise ContractError(f"unsupported journal version {version}")
        return cls(con, clock)

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _append(self, request_id: str, call_id: str | None, kind: str, stage: str, provider: str, model: str, input_sha256: str, payload: dict) -> Event:
        self._con.execute("BEGIN IMMEDIATE")
        try:
            n = self._con.execute("SELECT COALESCE(MAX(request_seq),0)+1 FROM events WHERE request_id=?", (request_id,)).fetchone()[0]
            call_id = call_id or f"{request_id}#{n}"
            now = self._clock()
            self._con.execute(
                "INSERT INTO events(request_id,request_seq,call_id,kind,stage,provider,model,input_sha256,payload,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (request_id, n, call_id, kind, stage, provider, model, input_sha256, json.dumps(payload, sort_keys=True), now),
            )
            self._con.execute("COMMIT")  # durable before returning
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        return Event(request_id, n, call_id, kind, stage, provider, model, input_sha256, payload, now)

    def record_intent(self, *, request_id: str, stage: str, provider: str, model: str, input_sha256: str, payload: dict | None = None) -> Event:
        for name, v in (("request_id", request_id), ("stage", stage), ("provider", provider), ("model", model)):
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"{name} must be a non-empty string")
        if not isinstance(input_sha256, str) or not _SHA.fullmatch(input_sha256):
            raise ContractError("input_sha256 must be 64 lowercase hex characters")
        return self._append(request_id, None, "intent", stage, provider, model, input_sha256, payload or {})

    def record_terminal(self, intent: Event, kind: str, payload: dict) -> Event:
        return self._append(intent.request_id, intent.call_id, kind, intent.stage, intent.provider, intent.model, intent.input_sha256, payload)

    def events(self, request_id: str) -> list[Event]:
        rows = self._con.execute(
            "SELECT request_id,request_seq,call_id,kind,stage,provider,model,input_sha256,payload,recorded_at FROM events WHERE request_id=? ORDER BY request_seq",
            (request_id,),
        ).fetchall()
        return [Event(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.loads(r[8]), r[9]) for r in rows]

    def reconcile(self, call_id: str, *, resolution: str, detail: str) -> Event:
        """Record an operator's verified finding about an unresolved call: executed or not_executed."""
        if resolution not in ("executed", "not_executed"):
            raise ContractError("resolution must be 'executed' or 'not_executed'")
        if not detail.strip():
            raise ContractError("reconciliation needs a recorded detail (what was checked)")
        request_id = call_id.rsplit("#", 1)[0]
        match = [e for e in self.pending(request_id) if e.call_id == call_id]
        if not match:
            if not any(e.call_id == call_id for e in self.events(request_id)):
                raise KeyError(call_id)
            raise ContractError(f"{call_id} is not unresolved")
        return self.record_terminal(match[0], "reconciled", {"resolution": resolution, "detail": detail})

    def pending(self, request_id: str) -> list[Event]:
        """Intents with no receipt, failure or reconciliation yet."""
        evs = self.events(request_id)
        closed = {e.call_id for e in evs if e.kind in ("receipt", "failure", "reconciled")}
        return [e for e in evs if e.kind == "intent" and e.call_id not in closed]


def run_journaled(
    journal: Journal, *, call: Callable[[], Any], request_id: str, stage: str, provider: str, model: str, input_sha256: str,
    intent_payload: dict | None = None,
) -> Any:
    """Write the intent, then call. `call` returns (result, usage). A crash leaves the intent pending."""
    blocking = [e for e in journal.pending(request_id) if (e.stage, e.provider, e.model, e.input_sha256) == (stage, provider, model, input_sha256)]
    if blocking:
        raise ReconciliationRequired(
            "unresolved earlier call(s) with the same input: " + ", ".join(e.call_id for e in blocking)
            + "; verify whether they executed, then reconcile before retrying"
        )
    intent = journal.record_intent(request_id=request_id, stage=stage, provider=provider, model=model, input_sha256=input_sha256, payload=intent_payload)
    try:
        result, usage = call()
    except UncertainOutcome as exc:  # sent, outcome unknown: stays unresolved
        journal.record_terminal(intent, "uncertain", {"detail": str(exc)})
        raise
    except Exception as exc:  # a definite failure; BaseException (a crash) deliberately leaves it pending
        journal.record_terminal(intent, "failure", {"error": type(exc).__name__, "detail": str(exc)})
        raise
    journal.record_terminal(intent, "receipt", {"usage": usage})
    return result


def resume_report(journal: Journal, request_id: str) -> ResumeReport:
    """After a restart: which calls are unresolved. Nothing here ever invokes a provider."""
    unresolved = tuple(journal.pending(request_id))
    return ResumeReport(unresolved, bool(unresolved))
