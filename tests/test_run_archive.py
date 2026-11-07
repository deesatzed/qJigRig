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
