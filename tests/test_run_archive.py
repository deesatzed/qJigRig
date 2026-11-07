"""Synthetic source and request payloads only; no credentials or network."""
import hashlib
import pytest
from qjig.run_archive import RunArchive
from qjig.providers import ProviderRequest, RawResponse


def test_interrupted_run_retains_inputs_and_responses(tmp_path):
    path = tmp_path / "local-run"
    request = ProviderRequest("planner", "stand-in", "m", "synthetic question", 20)
    with pytest.raises(KeyboardInterrupt):
        with RunArchive.open(path) as run:
            source_hash = run.add_source("synthetic/source.md", b"# Source\nText\n")
            run.record_request("call-1", request)
            run.record_response("call-1", RawResponse(200, '{"x":1}', {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0}, "finish_reason=stop"))
            run.record_request("call-2", request)
            raise KeyboardInterrupt()
    with RunArchive.open(path) as run:
        assert run.source("synthetic/source.md") == b"# Source\nText\n"
        assert source_hash == hashlib.sha256(b"# Source\nText\n").hexdigest()
        events = run.events()
        assert [event["kind"] for event in events] == ["request", "response", "request"]
        assert events[0]["data"]["prompt"] == request.prompt
        assert events[1]["data"]["body"] == '{"x":1}'
        assert events[1]["data"]["usage"]["completion_tokens"] == 3
        assert events[2]["call_id"] == "call-2"


def test_archive_survives_abrupt_process_exit(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / "abrupt"
    script = '''from qjig.run_archive import RunArchive
from qjig.providers import ProviderRequest
import os,sys
run = RunArchive.open(sys.argv[1])
run.add_source("source.md", b"fixture")
run.record_request("attempt", ProviderRequest("planner", "stand-in", "m", "question", 20))
os._exit(17)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.run([sys.executable, "-c", script, str(path)], env=env, check=False)
    assert child.returncode == 17
    with RunArchive.open(path) as run:
        assert run.source("source.md") == b"fixture"
        assert [(e["kind"], e["call_id"]) for e in run.events()] == [("request", "attempt")]


def test_archive_refuses_source_rebinding_and_orphan_response(tmp_path):
    from qjig.contracts import ContractError
    with RunArchive.open(tmp_path / "run") as run:
        run.add_source("source.md", b"original")
        with pytest.raises(ContractError):
            run.add_source("source.md", b"different")
        with pytest.raises(ContractError):
            run.record_response("missing", RawResponse(500, "error", None))
        assert run.source("source.md") == b"original" and run.events() == []


def test_typed_call_archives_before_dispatch(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget
    from qjig.journal import Journal
    from qjig.providers import FieldSpec, StandInTransport, call_typed

    request = ProviderRequest("planner", "stand-in", "m", "question", 20)
    with RunArchive.open(tmp_path / "run") as archive, Journal.open(tmp_path / "journal.sqlite") as journal:
        class ObservingTransport(StandInTransport):
            def send(self, value):
                assert [event["kind"] for event in archive.events()] == ["request"]
                return super().send(value)
        transport = ObservingTransport([RawResponse(200, '{"x":1}', {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0})])
        ledger = BudgetLedger(Budget(2, 100, 1), journal, "r")
        result = call_typed(ledger, transport, request, {"x": FieldSpec(int)}, archive=archive)
        assert result.ok and result.value == {"x": 1}
        events = archive.events()
        assert [e["kind"] for e in events] == ["request", "response", "validation"]
        assert all(e["call_id"] == result.call_id for e in events)
        assert events[-1]["data"] == {"value": {"x": 1}, "failure": None}


def test_archive_failure_after_dispatch_preserves_uncertainty(tmp_path, monkeypatch):
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget
    from qjig.journal import Journal, UncertainOutcome
    from qjig.providers import FieldSpec, StandInTransport, call_typed

    request = ProviderRequest("planner", "stand-in", "m", "question", 20)
    with RunArchive.open(tmp_path / "run") as archive, Journal.open(tmp_path / "journal.sqlite") as journal:
        transport = StandInTransport([RawResponse(200, '{"x":1}', {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0})])
        monkeypatch.setattr(archive, "record_response", lambda *args: (_ for _ in ()).throw(OSError("disk")))
        ledger = BudgetLedger(Budget(2, 100, 1), journal, "r")
        with pytest.raises(UncertainOutcome):
            call_typed(ledger, transport, request, {"x": FieldSpec(int)}, archive=archive)
        assert transport.calls_made == 1
        assert [e["kind"] for e in archive.events()] == ["request"]
        assert [e.kind for e in journal.events("r")] == ["intent", "uncertain"]
        assert len(journal.pending("r")) == 1


def test_typed_call_archives_malformed_output_and_timeout(tmp_path):
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget
    from qjig.journal import Journal, UncertainOutcome
    from qjig.providers import FieldSpec, StandInTransport, call_typed

    request = ProviderRequest("planner", "stand-in", "m", "question", 20)
    with RunArchive.open(tmp_path / "run") as archive, Journal.open(tmp_path / "journal.sqlite") as journal:
        good_usage = {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.0}
        transport = StandInTransport([RawResponse(200, "not json", good_usage), TimeoutError("timeout")])
        ledger = BudgetLedger(Budget(2, 100, 1), journal, "r")
        result = call_typed(ledger, transport, request, {"x": FieldSpec(int)}, archive=archive)
        assert result.failure == "malformed_output"
        assert archive.events()[1]["data"]["body"] == "not json"
        assert archive.events()[2]["data"] == {"value": None, "failure": "malformed_output"}
        with pytest.raises(UncertainOutcome):
            call_typed(ledger, transport, request, {"x": FieldSpec(int)}, archive=archive)
        assert archive.events()[-1]["data"] == {"failure": "uncertain_outcome"}
        assert len(journal.pending("r")) == 1


def test_validator_exception_retains_response_and_usage(tmp_path):
    """A failed validator is not a provider failure and must retain billed work."""
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget
    from qjig.journal import Journal
    from qjig.providers import StandInTransport, call_typed

    request = ProviderRequest("planner", "stand-in", "m", "question", 20)
    usage = {"prompt_tokens": 5, "completion_tokens": 3, "cost_usd": 0.01}
    with RunArchive.open(tmp_path / "run") as archive, Journal.open(tmp_path / "journal.sqlite") as journal:
        ledger = BudgetLedger(Budget(2, 100, 1), journal, "r")
        transport = StandInTransport([RawResponse(200, '{"x":1}', usage)])
        def broken_validator(text):
            raise RuntimeError("internal diagnostic with potentially sensitive text")
        result = call_typed(ledger, transport, request, broken_validator, archive=archive)
        assert result.failure == "validator_error" and result.value is None
        assert archive.events()[1]["data"]["body"] == '{"x":1}'
        assert archive.events()[2]["data"] == {"value": None, "failure": "validator_error"}
        assert [e.kind for e in journal.events("r")] == ["intent", "receipt"]
        assert journal.events("r")[-1].payload["usage"] == usage
        assert not journal.pending("r") and ledger.used_calls() == 1
        assert "sensitive text" not in repr(archive.events()) + repr(journal.events("r"))


def test_archive_preserves_multiple_source_revisions(tmp_path):
    from dataclasses import replace
    from qjig.contracts import ContractError
    from qjig.sources import SourceRevision, decode_source

    first = SourceRevision.create("src/policy.md", "synthetic", decode_source(b"line\r\n", encoding="utf-8"))
    second = SourceRevision.create("src/policy.md", "synthetic", decode_source(b"new\n", encoding="utf-8"))
    with RunArchive.open(tmp_path / "run") as archive:
        archive.add_revision(first)
        archive.add_revision(second)
        assert archive.revision(first.revision_id) == first
        assert archive.revision(second.revision_id) == second
        with pytest.raises(ContractError):
            archive.add_revision(replace(first, revision_id=second.revision_id))
    with RunArchive.open(tmp_path / "run") as reopened:
        assert reopened.revision(first.revision_id).decoded.raw == b"line\r\n"


def test_archive_context_is_immutable_and_hash_checked(tmp_path):
    from qjig.contracts import ContractError

    with RunArchive.open(tmp_path / "run") as archive:
        first = {"request": {"id": "r"}, "corpus": {"rev": "unknown"}}
        digest = archive.record_context(first)
        assert archive.record_context(first) == digest
        with pytest.raises(ContractError):
            archive.record_context({"request": {"id": "changed"}, "corpus": {"rev": "unknown"}})
        assert archive.context() == first
