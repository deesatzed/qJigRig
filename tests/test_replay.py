"""Synthetic stand-in run; replay makes no provider calls or quality claims."""
import sqlite3
from qjig.acquisition import run_fresh
from qjig.applicability import Applicability, ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import current_entries, index_entries, save_entries
from qjig.journal import Journal
from qjig.providers import RawResponse, StandInTransport
from qjig.run_archive import RunArchive
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog
from qjig.replay import verify_archive


def make_archive(tmp_path):
    source = SourceRevision.create("synthetic/rules.md", "synthetic", decode_source(b"# Rules\nRefunds within fourteen days.\n", encoding="utf-8"))
    request = Request("r", "refund fourteen?", "reviewer", "1", "project")
    usage = {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0}
    transport = StandInTransport([RawResponse(200, '{"predicates":[{"id":"p1","question":"refund fourteen?"}],"expression":{"ref":"p1"}}', usage),
                                  RawResponse(200, '{"supported":false,"quote":"","reason":"none"}', usage),
                                  RawResponse(200, '{"supported":false,"quote":"","reason":"none"}', usage)])
    directory = tmp_path / "run"
    with Catalog.open(tmp_path / "c.sqlite") as catalog, Journal.open(tmp_path / "j.sqlite") as journal, RunArchive.open(directory) as archive:
        catalog.add_revision(source)
        save_entries(catalog, index_entries(source))
        ledger = BudgetLedger(Budget(5, 50000, 1), journal, "r")
        inputs = ApplicabilityInputs(Collection((MemberMetadata(source.revision_id, "project", Interval("2026-01-01", OPEN)),)), frozenset(), "2026-11-15", False)
        result = run_fresh(request=request, catalog=catalog, entries=current_entries(catalog, source.source_id, source.revision_id),
                           ledger=ledger, transport=transport, planner=("stand-in", "planner"), judge=("stand-in", "judge"),
                           revision_applicability=lambda _: Applicability.MATCH, applicability_inputs=inputs, archive=archive)
        assert result.status == "deferred"
    return directory, transport.calls_made


def test_archive_replay_detects_changed_evidence_without_inference(tmp_path, monkeypatch):
    directory, calls = make_archive(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted inference")
    monkeypatch.setattr(StandInTransport, "send", forbidden)
    with RunArchive.open(directory) as archive:
        initial = verify_archive(archive)
        assert initial.status == "unanchored" and not initial.issues
        replay = verify_archive(archive, expected_digest=initial.digest)
        assert replay.status == "structurally_verified" and replay.checked_traces == 1
    assert calls == 3  # replay did not invoke the stand-in
    # Deliberately bypass a SQLite guard in a temporary fixture to test detection.
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER revision_no_update")
        con.execute("UPDATE revisions SET raw=?", (b"tampered",))
    with RunArchive.open(directory) as archive:
        changed = verify_archive(archive, expected_digest=initial.digest)
        assert changed.status == "invalid" and changed.issues


def test_replay_reports_interrupted_request_as_incomplete(tmp_path):
    directory = tmp_path / "partial"
    with RunArchive.open(directory) as archive:
        archive.record_context({"schema": "qjig.fresh-context.v1", "corpus": {}})
        archive.record_request("r#1", __import__("qjig.providers", fromlist=["ProviderRequest"]).ProviderRequest("planner", "stand-in", "m", "question", 20))
        report = verify_archive(archive)
        assert report.status == "incomplete"
        assert "pending_request:r#1" in report.issues


def test_replay_rejects_tampered_trace_and_response(tmp_path):
    import json
    directory, _ = make_archive(tmp_path)
    with RunArchive.open(directory) as archive:
        digest = verify_archive(archive).digest
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='trace'").fetchone()
        trace = json.loads(raw)
        trace["evidence"][0]["text"] = "fabricated"
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(trace), seq))
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='response' LIMIT 1").fetchone()
        response = json.loads(raw)
        response["body"] = "changed"
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(response), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive, expected_digest=digest)
        assert report.status == "invalid"
        assert "archive_digest_mismatch" in report.issues
        assert any(issue.startswith("invalid_trace:") for issue in report.issues)
        assert any(issue.startswith("invalid_response:") for issue in report.issues)


def test_replay_checks_planning_packet_even_if_context_hash_is_rewritten(tmp_path):
    import hashlib
    import json

    directory, _ = make_archive(tmp_path)
    with RunArchive.open(directory) as archive:
        digest = verify_archive(archive).digest
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER context_no_update")
        (raw,) = con.execute("SELECT data FROM run_context WHERE id=1").fetchone()
        context = json.loads(raw)
        context["planning_evidence"]["packet"]["items"][0]["text"] = "fabricated"
        encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        con.execute("UPDATE run_context SET data=?, sha256=? WHERE id=1", (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive, expected_digest=digest)
        assert report.status == "invalid"
        assert "invalid_planning_or_applicability" in report.issues
        assert "archive_digest_mismatch" in report.issues


def test_replay_requires_final_run_record(tmp_path):
    directory, _ = make_archive(tmp_path)
    # Remove a final record if present, simulating interruption after the last trace.
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_delete")
        con.execute("DELETE FROM events WHERE kind='run_result'")
    with RunArchive.open(directory) as archive:
        snapshot = verify_archive(archive)
        assert snapshot.status == "incomplete"
        assert "missing_run_result" in snapshot.issues


def test_replay_rejects_result_that_disagrees_with_archived_plan(tmp_path):
    import json
    directory, _ = make_archive(tmp_path)
    with sqlite3.connect(directory / "run.sqlite") as con:
        con.execute("DROP TRIGGER event_no_update")
        seq, raw = con.execute("SELECT seq,data FROM events WHERE kind='run_result'").fetchone()
        result = json.loads(raw)
        result["expression"] = {"op": "not", "args": [{"ref": "p1"}]}
        con.execute("UPDATE events SET data=? WHERE seq=?", (json.dumps(result), seq))
    with RunArchive.open(directory) as archive:
        report = verify_archive(archive)
        assert report.status == "invalid"
        assert any(item.startswith("invalid_run_result:") for item in report.issues)
