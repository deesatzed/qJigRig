"""STAND-IN local runner (D018): an authored function, not a model. Tests the environment and
input-size guards only; no local model, weights or environment are used or validated for real."""
import json
import stat

import pytest

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.local_judge import (
    EnvironmentUnavailable, InputTooLarge, LocalJudgeConfig, run_local_judge, validate_environment,
)
from qjig.logic import Outcome
from qjig.packets import build_packet
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source

QUESTION = "Is the purchase inside the 14 day refund window?"
QUOTE = "Refunds are accepted within 14 days of purchase."


def packet(extra=""):
    r = SourceRevision.create("p/a.md", "/x", decode_source(f"# Refunds\n{QUOTE}\n{extra}".encode(), encoding="utf-8"))
    return build_packet(bm25_candidates(index_entries(r), "refund days"), max_bytes=20000)


class Runner:
    label = "STAND_IN local runner"

    def __init__(self):
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return json.dumps({"supported": self.calls == 1, "quote": QUOTE if self.calls == 1 else "", "reason": "authored"})


def env(tmp_path, executable=True):
    py = tmp_path / "judge-env" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\n")
    py.chmod(py.stat().st_mode | (stat.S_IXUSR if executable else 0))
    if not executable:
        py.chmod(stat.S_IRUSR | stat.S_IWUSR)
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.bin").write_bytes(b"x")
    return py, model


def listing(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def ledger_for(tmp_path, name="j.sqlite", calls=4):
    j = Journal.open(tmp_path / name)
    return j, BudgetLedger(Budget(calls, 50000, 1.0), j, "req-1")


def test_oversize_no_truncation(tmp_path):
    py, model = env(tmp_path)
    runner = Runner()
    pk = packet()
    before = listing(tmp_path)
    j, ledger = ledger_for(tmp_path)
    before = listing(tmp_path)  # includes the journal file created above
    with j:
        small = LocalJudgeConfig(py, model, max_input_chars=100, model_label="local-stand-in")
        with pytest.raises(InputTooLarge) as exc:
            run_local_judge(ledger, small, runner, QUESTION, pk)
        assert exc.value.size > 100 and exc.value.limit == 100
        # rejected before any inference: no runner call, no journal intent, nothing created or copied
        assert runner.calls == 0 and j.events("req-1") == []
        assert listing(tmp_path) == before
    # the same input passes when the limit is large enough, and it is passed whole, never cut down
    seen = []
    class Spy(Runner):
        def __call__(self, prompt):
            seen.append(prompt)
            return super().__call__(prompt)
    j, ledger = ledger_for(tmp_path, "k.sqlite")
    with j:
        big = LocalJudgeConfig(py, model, max_input_chars=50000, model_label="local-stand-in")
        r = run_local_judge(ledger, big, Spy(), QUESTION, pk)
        assert r.outcome is Outcome.TRUE and len(seen) == 1 and all(QUOTE in p for p in seen)
        assert r.negative.failure == "budget_exceeded"  # unmeasured cost prevents another call
        assert {e.provider for e in j.events("req-1")} == {"local"}


def test_exact_limit_boundary(tmp_path):
    py, model = env(tmp_path)
    j, ledger = ledger_for(tmp_path)
    with j:
        # find the exact size of the larger prompt, then test limit == size and limit == size-1
        probe = LocalJudgeConfig(py, model, max_input_chars=1, model_label="m")
        with pytest.raises(InputTooLarge) as exc:
            run_local_judge(ledger, probe, Runner(), QUESTION, packet())
        size = exc.value.size
        with pytest.raises(InputTooLarge):
            run_local_judge(ledger, LocalJudgeConfig(py, model, size - 1, "m"), Runner(), QUESTION, packet())
        assert run_local_judge(ledger, LocalJudgeConfig(py, model, size, "m"), Runner(), QUESTION, packet()).outcome is Outcome.TRUE


def test_missing_or_unusable_environment_is_reported_and_never_created(tmp_path):
    before = listing(tmp_path)
    cfg = LocalJudgeConfig(tmp_path / "judge-env" / "bin" / "python", tmp_path / "model", 1000, "m")
    report = validate_environment(cfg)
    assert report.ok is False and set(report.problems) == {"interpreter_missing", "model_dir_missing"}
    j, ledger = ledger_for(tmp_path)
    before = listing(tmp_path)
    runner = Runner()
    with j:
        with pytest.raises(EnvironmentUnavailable) as exc:
            run_local_judge(ledger, cfg, runner, QUESTION, packet())
        assert "interpreter_missing" in str(exc.value) and runner.calls == 0 and j.events("req-1") == []
    assert listing(tmp_path) == before  # nothing was created, copied or installed
    py, model = env(tmp_path, executable=False)
    assert validate_environment(LocalJudgeConfig(py, model, 1000, "m")).problems == ("interpreter_not_executable",)
    py2, model2 = py, model
    (model2 / "weights.bin").unlink()
    model2.rmdir()
    assert "model_dir_missing" in validate_environment(LocalJudgeConfig(py2, model2, 1000, "m")).problems
    assert validate_environment(LocalJudgeConfig(None, None, 1000, "m")).problems == ("interpreter_not_configured", "model_dir_not_configured")


def test_invalid_limits_are_rejected():
    from qjig.contracts import ContractError

    for bad in (0, -1, True, 1.5):
        with pytest.raises(ContractError):
            LocalJudgeConfig(None, None, bad, "m")
