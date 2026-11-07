"""End-to-end through real subprocesses. All sources and policies below are SYNTHETIC TEST FIXTURES
written to a temp directory; they exercise mechanics, not real-world policy or any model."""
import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

REFUND = "# Refund limit\nRefunds are accepted within 14 days of purchase.\n"
WAIVER = "# Waivers\nA manager may grant a waiver of the refund limit.\n"

POLICY = {
    "label": "SYNTHETIC FIXTURE",
    "entities": ["customer:42"],
    "as_of": "2026-11-15",
    "historical_as_known": False,
    "mode": "snapshot",
    "facts": {"refund_days": 20},
    "plan": {
        "origin": "authored",
        "predicates": [
            {"id": "within_limit", "question": "Is the refund inside the limit?"},
            {"id": "exception", "question": "Does a waiver or exception apply?"},
        ],
        "expression": {"op": "or", "args": [{"ref": "within_limit"}, {"ref": "exception"}]},
    },
    "needs": {
        "within_limit": {
            "query": "refund days limit", "want": 2, "max_bytes": 4000,
            "evaluator": {"kind": "numeric_threshold", "field": "refund_days", "pattern": "within (\\d+) days", "operator": "lte"},
        },
        "exception": {
            "kind": "exception", "query": "waiver exception", "want": 2, "max_bytes": 4000,
            "evaluator": {"kind": "phrase_present", "pattern": "waiver|exception"},
        },
    },
}
REQUEST = {
    "schema_version": "qjig.request.v1", "request_id": "req-cli-1", "question": "Can customer 42 get a refund after 20 days?",
    "role": "reviewer", "role_version": "1", "scope": "project",
    "budget": {"max_calls": 0, "max_tokens": 0, "max_cost_usd": 0},
}


def cli(*args, cwd):
    env = {"PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1", "PATH": os.environ.get("PATH", "")}  # no API keys passed
    return subprocess.run([sys.executable, "-m", "qjig", *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True)


def setup(tmp_path):
    (tmp_path / "refund.md").write_text(REFUND, encoding="utf-8")
    (tmp_path / "waiver.md").write_text(WAIVER, encoding="utf-8")
    (tmp_path / "policy.json").write_text(json.dumps(POLICY))
    (tmp_path / "request.json").write_text(json.dumps(REQUEST))
    return tmp_path / "catalog.sqlite"


def do_import(tmp_path, db, name, source_id, **extra):
    args = ["import", "--catalog", db, "--source-id", source_id, "--file", tmp_path / name, "--encoding", "utf-8",
            "--scope", "project", "--effective-from", "2026-01-01", "--effective-to", "open", "--observed-at", "2026-01-01"]
    for k, v in extra.items():
        args += [f"--{k.replace('_', '-')}", v]
    return cli(*args, "--entity", "customer:42", cwd=tmp_path)


def ask(tmp_path, db, policy="policy.json"):
    return cli("ask", "--catalog", db, "--request", tmp_path / "request.json", "--policy", tmp_path / policy,
               "--trace-out", tmp_path / "trace.json", cwd=tmp_path)


def test_fixture_end_to_end(tmp_path):
    db = setup(tmp_path)
    r = do_import(tmp_path, db, "refund.md", "policy/refund.md")
    assert r.returncode == 0, r.stderr
    imported = json.loads(r.stdout)
    assert imported["source_id"] == "policy/refund.md" and imported["entries"] == 1 and imported["revision_id"].startswith("rev1:")

    # the exception source has not been imported: ordinary fails, the exception is unknown -> deferred, not "no"
    a = ask(tmp_path, db)
    assert a.returncode == 3, (a.stdout, a.stderr)
    out = json.loads(a.stdout)
    assert out["status"] == "deferred" and out["outcome"] is None
    assert out["observations"]["within_limit"]["outcome"] == "false"
    assert out["observations"]["exception"] == {"outcome": "unknown", "reason": "no_retrieval_hit"}
    assert out["providers_called"] == 0 and out["policy_label"] == "SYNTHETIC FIXTURE"
    assert out["plan_origin"] == "authored" and "not established" in out["plan_caveat"]
    assert "outcome_not_determined" in out["reasons"]

    # the saved trace can be rendered for a person
    t = cli("trace", "--file", tmp_path / "trace.json", cwd=tmp_path)
    assert t.returncode == 0
    assert "within_limit" in t.stdout and "within 14 days" in t.stdout and "DEFERRED" in t.stdout
    assert "no_retrieval_hit" in t.stdout and "plan_caveat" not in t.stdout  # plain wording, not field names
    assert "not established" in t.stdout

    # importing the waiver source lets the same question resolve, through the same pipeline
    assert do_import(tmp_path, db, "waiver.md", "policy/waiver.md").returncode == 0
    b = ask(tmp_path, db)
    assert b.returncode == 0, (b.stdout, b.stderr)
    done = json.loads(b.stdout)
    assert done["status"] == "decided" and done["outcome"] is True
    assert done["observations"]["exception"]["outcome"] == "true" and done["providers_called"] == 0


def test_current_required_defers_when_origin_changed(tmp_path):
    db = setup(tmp_path)
    assert do_import(tmp_path, db, "refund.md", "policy/refund.md").returncode == 0
    assert do_import(tmp_path, db, "waiver.md", "policy/waiver.md").returncode == 0
    (tmp_path / "refund.md").write_text(REFUND.replace("14", "21"), encoding="utf-8")  # origin edited after import
    pol = json.loads((tmp_path / "policy.json").read_text())
    pol["mode"] = "current_required"
    (tmp_path / "policy_cur.json").write_text(json.dumps(pol))
    a = ask(tmp_path, db, "policy_cur.json")
    assert a.returncode == 3
    out = json.loads(a.stdout)
    assert out["status"] == "deferred" and "source_changed_no_restart" in out["reasons"]
    assert out["origin_updates"][0]["source_id"] == "policy/refund.md"
    # snapshot mode over the same state still answers from the imported revision and reports the change
    snap = ask(tmp_path, db)
    sout = json.loads(snap.stdout)
    assert snap.returncode == 0 and sout["status"] == "decided"
    assert [u["source_id"] for u in sout["origin_updates"]] == ["policy/refund.md"]  # reported, not applied


def test_bad_inputs_fail_with_exit_2_and_a_message(tmp_path):
    db = setup(tmp_path)
    bad = cli("import", "--catalog", db, "--source-id", "/abs/path.md", "--file", tmp_path / "refund.md", "--encoding", "utf-8", cwd=tmp_path)
    assert bad.returncode == 2 and "portable" in bad.stderr
    missing = cli("import", "--catalog", db, "--source-id", "a/b.md", "--file", tmp_path / "nope.md", "--encoding", "utf-8", cwd=tmp_path)
    assert missing.returncode == 2
    (tmp_path / "request.json").write_text(json.dumps({**REQUEST, "budget": {"max_calls": True, "max_tokens": 0, "max_cost_usd": 0}}))
    r = ask(tmp_path, db)
    assert r.returncode == 2 and "max_calls" in r.stderr
    assert cli(cwd=tmp_path).returncode == 2  # no command


def test_unreviewed_origin_cannot_decide(tmp_path):
    db = setup(tmp_path)
    assert do_import(tmp_path, db, "refund.md", "policy/refund.md").returncode == 0
    assert do_import(tmp_path, db, "waiver.md", "policy/waiver.md").returncode == 0
    for origin in ("authored", "fresh", "reused"):
        policy = json.loads((tmp_path / "policy.json").read_text())
        policy["plan"]["origin"] = origin
        (tmp_path / "origin.json").write_text(json.dumps(policy))
        result = ask(tmp_path, db, "origin.json")
        output = json.loads(result.stdout)
        if origin == "authored":
            assert result.returncode == 0 and output["status"] == "decided"
        else:
            assert result.returncode == 3 and output["status"] == "deferred"
            assert output["outcome"] is None
            assert "plan_coverage_unestablished" in output["reasons"]
