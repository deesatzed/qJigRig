import sqlite3

import pytest

from qjig.contracts import ContractError
from qjig.journal import Journal, ReconciliationRequired, UncertainOutcome, resume_report, run_journaled

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


def crash_once(db):
    with Journal.open(db) as j:
        with pytest.raises(Crash):
            run_journaled(j, call=lambda: (_ for _ in ()).throw(Crash()), **INTENT)


def test_uncertain_resume(tmp_path):
    db = tmp_path / "j.sqlite"
    crash_once(db)
    calls = []
    with Journal.open(db) as j:
        report = resume_report(j, "req-1")
        assert report.reconciliation_required is True and [e.call_id for e in report.unresolved] == ["req-1#1"]
        # the same call is NOT blindly repeated: refused, with no second invocation
        with pytest.raises(ReconciliationRequired) as exc:
            run_journaled(j, call=lambda: calls.append(1) or ("x", {}), **INTENT)
        assert calls == [] and "req-1#1" in str(exc.value)
        assert len(j.events("req-1")) == 1  # the refusal did not even write a new intent
        # a different input is a different call and is allowed
        run_journaled(j, call=lambda: calls.append(2) or ("y", {}), **{**INTENT, "input_sha256": "b" * 64})
        assert calls == [2]
        # after an operator verifies the first call did NOT execute, a retry is allowed and journaled
        j.reconcile("req-1#1", resolution="not_executed", detail="provider dashboard shows no request")
        assert resume_report(j, "req-1").reconciliation_required is False
        run_journaled(j, call=lambda: calls.append(3) or ("z", {}), **INTENT)
        assert calls == [2, 3]
        rec = [e for e in j.events("req-1") if e.kind == "reconciled"][0]
        assert rec.payload == {"resolution": "not_executed", "detail": "provider dashboard shows no request"}


def test_uncertain_outcome_is_journaled_and_blocks_retry(tmp_path):
    db = tmp_path / "j.sqlite"
    calls = []

    def timeout():
        calls.append(1)
        raise UncertainOutcome("read timeout after request sent")

    with Journal.open(db) as j:
        with pytest.raises(UncertainOutcome):
            run_journaled(j, call=timeout, **INTENT)
        kinds = [e.kind for e in j.events("req-1")]
        assert kinds == ["intent", "uncertain"]
        assert [e.call_id for e in j.pending("req-1")] == ["req-1#1"]  # still unresolved
        with pytest.raises(ReconciliationRequired):
            run_journaled(j, call=timeout, **INTENT)
        assert calls == [1]
        j.reconcile("req-1#1", resolution="executed", detail="billing shows one call")
        assert j.pending("req-1") == []
        assert [e.payload["resolution"] for e in j.events("req-1") if e.kind == "reconciled"] == ["executed"]


def test_reconcile_validates(tmp_path):
    with Journal.open(tmp_path / "j.sqlite") as j:
        with pytest.raises(KeyError):
            j.reconcile("nope#1", resolution="executed", detail="x")
        run_journaled(j, call=lambda: ("x", {}), **INTENT)
        with pytest.raises(ContractError):
            j.reconcile("req-1#1", resolution="executed", detail="already has a receipt")  # nothing to reconcile
        crash_once(tmp_path / "j.sqlite")
        with pytest.raises(ContractError):
            j.reconcile("req-1#3", resolution="maybe", detail="x")
        with pytest.raises(ContractError):
            j.reconcile("req-1#3", resolution="executed", detail="  ")
