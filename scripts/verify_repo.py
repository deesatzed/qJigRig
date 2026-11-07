#!/usr/bin/env python3
"""Audit the implementation queue; passing this is not a completion or quality claim."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def audit_tasks(tasks: list[dict], root: Path) -> list[str]:
    errors: list[str] = []
    by_id = {}
    for task in tasks:
        ident = task.get("id")
        if not isinstance(ident, str) or not ident or ident in by_id:
            errors.append(f"invalid or duplicate task id: {ident!r}")
            continue
        by_id[ident] = task
    for ident, task in by_id.items():
        if task.get("status") not in ("complete", "pending"):
            errors.append(f"{ident}: invalid status")
        dependencies = task.get("depends_on")
        if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
            errors.append(f"{ident}: invalid dependencies")
            continue
        for dep in dependencies:
            if dep not in by_id:
                errors.append(f"{ident}: missing dependency {dep}")
            elif task.get("status") == "complete" and by_id[dep].get("status") != "complete":
                errors.append(f"{ident}: incomplete dependency {dep}")
        if task.get("status") != "complete":
            continue
        if not isinstance(task.get("evidence"), str) or not task["evidence"].strip():
            errors.append(f"{ident}: missing evidence")
        for name in task.get("files", []):
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                errors.append(f"{ident}: missing or invalid file {name}")
        test_name, test_file = task.get("test_name"), task.get("test_file")
        try:
            path = (root / test_file).resolve()
            if not path.is_relative_to(root.resolve()):
                raise OSError("outside repository")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name for node in ast.walk(tree)):
                errors.append(f"{ident}: missing test {test_file}::{test_name}")
        except (OSError, SyntaxError, TypeError):
            errors.append(f"{ident}: unreadable test {test_file}")
    visiting, visited = set(), set()
    def visit(ident):
        if ident in visiting:
            errors.append(f"{ident}: dependency cycle")
            return
        if ident in visited:
            return
        visiting.add(ident)
        deps = by_id[ident].get("depends_on")
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, str) and dep in by_id:
                    visit(dep)
        visiting.remove(ident)
        visited.add(ident)
    for ident in by_id:
        visit(ident)
    return errors


def main() -> int:
    try:
        payload = json.loads((ROOT / "plan/tasks.json").read_text(encoding="utf-8"))
        tasks = payload["tasks"]
        errors = audit_tasks(tasks, ROOT)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"queue unreadable: {exc}")
        return 1
    for error in errors:
        print(error)
    if errors:
        print(f"FAILED: {len(errors)} queue issue(s)")
        return 1
    print(f"OK: {len(tasks)} tasks checked; pending tasks are not completion evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
