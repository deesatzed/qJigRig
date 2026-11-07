import sqlite3

import pytest

from qjig.contracts import ContractError
from qjig.journal import Journal, run_journaled

INTENT = dict(request_id="req-1", stage="judge", provider="stand-in", model="stand-in-model", input_sha256="a" * 64)


class Crash(BaseException):
    """Simulates the process dying mid-call (not an ordinary exception)."""


def test_intent_before_call(tmp_path):
    db = tmp_path / "journal.sqlite"
    seen_during_call = []

    def call():
        # the intent must already be durable while the side effect is in flight
        with Journal.open(db) as other:
            seen_during_call.extend(other.pending("req-1"))
        raise Crash()

    with Journal.open(db) as j:
        with pytest.raises(Crash):
            run_journaled(j, call=call, **INTENT)
    assert len(seen_during_call) == 1
    # after the crash, a fresh process still sees the pending intent with request and input identity
    with Journal.open(db) as j:
        (p,) = j.pending("req-1")
        assert (p.request_id, p.stage, p.provider, p.model, p.input_sha256) == ("req-1", "judge", "stand-in", "stand-in-model", "a" * 64)
        assert p.call_id and p.request_seq == 1
        assert j.pending("other-request") == []


def test_receipt_and_failure_close_an_intent(tmp_path):
    with Journal.open(tmp_path / "j.sqlite") as j:
        ok = run_journaled(j, call=lambda: ("answer", {"prompt_tokens": 10, "completion_tokens": 3, "cost_usd": None}), **INTENT)
        assert ok == "answer" and j.pending("req-1") == []
        with pytest.raises(RuntimeError):
            run_journaled(j, call=lambda: (_ for _ in ()).throw(RuntimeError("boom")), **{**INTENT, "stage": "planner"})
        assert j.pending("req-1") == []  # a definite failure is recorded, not left pending
        events = j.events("req-1")
        assert [(e.request_seq, e.kind, e.stage) for e in events] == [
            (1, "intent", "judge"), (2, "receipt", "judge"), (3, "intent", "planner"), (4, "failure", "planner")]
        assert events[1].payload["usage"] == {"prompt_tokens": 10, "completion_tokens": 3, "cost_usd": None}  # unknown stays None
        assert "boom" in events[3].payload["detail"]


def test_journal_is_append_only(tmp_path):
    db = tmp_path / "j.sqlite"
    with Journal.open(db) as j:
        run_journaled(j, call=lambda: ("x", {}), **INTENT)
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE events SET kind='intent'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM events")
    con.close()


def test_invalid_intents_rejected_before_any_call(tmp_path):
    calls = []
    with Journal.open(tmp_path / "j.sqlite") as j:
        for bad in ({"request_id": ""}, {"input_sha256": "short"}, {"stage": ""}, {"model": 3}):
            with pytest.raises(ContractError):
                run_journaled(j, call=lambda: calls.append(1), **{**INTENT, **bad})
        assert calls == [] and j.events("req-1") == []
