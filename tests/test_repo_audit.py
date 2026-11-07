"""Repository queue audit uses temporary authored task records, never external services."""
import copy

from scripts.verify_repo import audit_tasks


def fixture(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_example():\n    pass\n")
    (tmp_path / "module.py").write_text("x = 1\n")
    return [{"id": "T001", "status": "complete", "depends_on": [], "files": ["module.py"],
             "test_file": "tests/test_sample.py", "test_name": "test_example", "command": "python -m pytest tests/test_sample.py::test_example -q", "evidence": "focused test passed"},
            {"id": "T002", "status": "pending", "depends_on": ["T001"], "files": ["future.py"],
             "test_file": "tests/test_future.py", "test_name": "test_future"}]


def test_completed_and_pending_tasks_are_valid(tmp_path):
    tasks = fixture(tmp_path)
    assert audit_tasks(tasks, tmp_path) == []
    for change in (lambda x: x[0].update(evidence=""),
                   lambda x: x[0].update(depends_on=["T002"]),
                   lambda x: x[1].update(depends_on=["MISSING"]),
                   lambda x: x[0].update(test_name="test_missing"),
                   lambda x: x[0].update(files=["missing.py"]),
                   lambda x: x[1].update(id="T001")):
        broken = copy.deepcopy(tasks)
        change(broken)
        assert audit_tasks(broken, tmp_path), broken


def test_audit_rejects_wrong_test_command_and_non_collectable_test(tmp_path):
    tasks = fixture(tmp_path)
    for command in ("", "python -m pytest tests/test_sample.py::test_other -q",
                    "python -m pytest tests/test_sample.py::test_example -q; false"):
        altered = copy.deepcopy(tasks)
        altered[0]["command"] = command
        assert audit_tasks(altered, tmp_path)
    (tmp_path / "tests" / "test_sample.py").write_text(
        "def helper():\n    def test_example():\n        pass\n")
    assert audit_tasks(tasks, tmp_path)
