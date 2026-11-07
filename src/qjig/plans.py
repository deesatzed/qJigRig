"""Bounded decision plans: at most six predicates and a small AND/OR/NOT expression over them.

Plans are data. They hold no executable code and a valid plan is not known to be complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ContractError

MAX_PREDICATES = 6
MAX_DEPTH = 12  # the leaf counts as depth 1
ORIGINS = ("authored", "fresh", "reused")
EXACT_OPERATORS = ("eq", "ne", "lt", "lte", "gt", "gte")
_ID = re.compile(r"[a-z][a-z0-9_]{0,31}")


class PlanError(ContractError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Predicate:
    id: str
    question: str
    depends_on: tuple[str, ...] = ()
    exact_operator: str | None = None


@dataclass(frozen=True)
class Plan:
    predicates: tuple[Predicate, ...]
    expression: Mapping[str, Any]
    origin: str


def _walk(node: Any, ids: set[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        raise PlanError("too_deep", f"expression deeper than {MAX_DEPTH}")
    if not isinstance(node, dict):
        raise PlanError("bad_node", repr(node))
    keys = set(node)
    if keys == {"ref"}:
        if node["ref"] not in ids:
            raise PlanError("dangling_ref", str(node["ref"]))
        return
    if keys != {"op", "args"}:
        raise PlanError("extra_node_key" if "op" in keys or "ref" in keys else "bad_node", str(sorted(keys)))
    op, args = node["op"], node["args"]
    if op not in ("and", "or", "not"):
        raise PlanError("unknown_operator", str(op))
    if not isinstance(args, list):
        raise PlanError("bad_node", "args must be a list")
    if (op == "not" and len(args) != 1) or (op in ("and", "or") and len(args) < 2):
        raise PlanError("not_arity" if op == "not" else "and_arity", f"{op} with {len(args)} args")
    for a in args:
        _walk(a, ids, depth + 1)


def _check_dependencies(preds: list[Predicate]) -> None:
    ids = {p.id for p in preds}
    graph = {p.id: p.depends_on for p in preds}
    for pid, deps in graph.items():
        for d in deps:
            if d == pid:
                raise PlanError("self_dependency", pid)
            if d not in ids:
                raise PlanError("dangling_dependency", d)
    state: dict[str, int] = {}

    def visit(n: str) -> None:
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise PlanError("dependency_cycle", n)
        state[n] = 1
        for d in graph[n]:
            visit(d)
        state[n] = 2

    for pid in graph:
        visit(pid)


def parse_plan(data: Mapping[str, Any]) -> Plan:
    if not isinstance(data, Mapping) or set(data) != {"origin", "predicates", "expression"}:
        extra = sorted(set(data) - {"origin", "predicates", "expression"}) if isinstance(data, Mapping) else []
        raise PlanError("executable_code_field" if extra else "bad_plan", f"unexpected keys {extra}")
    if data["origin"] not in ORIGINS:
        raise PlanError("bad_origin", str(data["origin"]))
    raw = data["predicates"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PREDICATES:
        raise PlanError("no_predicates" if not raw else "too_many_predicates", f"{len(raw) if isinstance(raw, list) else raw!r}")
    preds: list[Predicate] = []
    for r in raw:
        if not isinstance(r, dict) or not {"id", "question"} <= set(r) <= {"id", "question", "depends_on", "exact_operator"}:
            raise PlanError("bad_predicate", repr(r))
        if not isinstance(r["id"], str) or not _ID.fullmatch(r["id"]):
            raise PlanError("bad_id", repr(r["id"]))
        if not isinstance(r["question"], str) or not r["question"].strip():
            raise PlanError("bad_predicate", "question")
        op = r.get("exact_operator")
        if op is not None and op not in EXACT_OPERATORS:
            raise PlanError("unknown_exact_operator", str(op))
        deps = r.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise PlanError("bad_predicate", "depends_on")
        preds.append(Predicate(r["id"], r["question"], tuple(deps), op))
    ids = [p.id for p in preds]
    if len(set(ids)) != len(ids):
        raise PlanError("duplicate_predicate", str([i for i in ids if ids.count(i) > 1][0]))
    _check_dependencies(preds)
    _walk(data["expression"], set(ids), 1)
    return Plan(tuple(preds), data["expression"], data["origin"])
