"""Deterministic command line: import sources, ask a question against a plan, render the trace.

No provider is ever called from here. Exit codes: 0 decided, 3 deferred, 2 invalid input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .acquisition import Context, EvalResult, NeedSpec, RunState, run_until_done
from .applicability import OPEN, UNKNOWN_BOUND, Applicability, Collection, Interval, MemberMetadata
from .contracts import ContractError, Request
from .exact import FieldValue, NumericRule, PolicyRule, evaluate_dated_numeric
from .finalize import MODES, finalize
from .indexing import index_entries, invalidate_superseded, load_live_entries, save_entries
from .logic import Outcome
from .obligations import Obligation, ObligationLedger
from .plans import parse_plan
from .recovery import applicability_filter
from .sources import SourceRevision, decode_source
from .store import Catalog

PLAN_CAVEAT = (
    "Plan completeness is not established: a valid plan does not show that every relevant "
    "condition or exception is included."
)


# --- metadata persistence helpers -------------------------------------------------------------

def _enc(bound: object) -> str:
    return "open" if bound is OPEN else "unknown" if bound is UNKNOWN_BOUND else str(bound)


def _dec(text: str) -> object:
    return OPEN if text == "open" else UNKNOWN_BOUND if text == "unknown" else text


def _member_row(revision_id: str, m: MemberMetadata) -> tuple:
    return (revision_id, m.scope, m.authority_id, json.dumps(sorted(m.entity_keys)),
            _enc(m.effective.start), _enc(m.effective.end), m.observed_at)


def _member_from_row(row: tuple) -> MemberMetadata:
    rid, scope, authority, entities, start, end, observed = row
    return MemberMetadata(rid, scope, Interval(_dec(start), _dec(end)), authority, frozenset(json.loads(entities)), observed)


# --- commands ----------------------------------------------------------------------------------

def cmd_import(a: argparse.Namespace) -> dict[str, Any]:
    path = Path(a.file)
    raw = path.read_bytes()
    revision = SourceRevision.create(a.source_id, str(path.resolve()), decode_source(raw, encoding=a.encoding))
    member = MemberMetadata(
        revision.revision_id, a.scope, Interval(_dec(a.effective_from), _dec(a.effective_to)), a.authority,
        frozenset(a.entity or ()), a.observed_at,
    )
    with Catalog.open(a.catalog) as cat:
        existing = {r[0]: r for r in cat.metadata_rows()}.get(revision.revision_id)
        row = _member_row(revision.revision_id, member)
        if existing is not None and existing != row:
            raise ContractError("this revision is already imported with different metadata")
        cat.add_revision(revision)
        entries = index_entries(revision)
        save_entries(cat, entries)
        invalidate_superseded(cat, a.source_id, current_revision_id=revision.revision_id)
        cat.put_metadata_row(row)
    return {"source_id": a.source_id, "revision_id": revision.revision_id, "entries": len(entries), "origin": revision.origin}


def _fact(value: Any) -> int | Decimal:
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ContractError(f"fact {value!r} is not a number") from exc
    raise ContractError("facts must be integers or numeric strings")


def _evaluator(spec: dict, members: dict[str, MemberMetadata], facts: dict, entities: frozenset[str], as_of: str, historical: bool):
    kind = spec.get("kind")
    pattern = re.compile(spec["pattern"], re.I)
    if kind == "phrase_present":
        def evaluate(packet, recovery):
            hits = tuple(i.entry_id for i in packet.items if pattern.search(i.span.text))
            # absence of the phrase is never evidence that the condition does not exist
            return EvalResult(Outcome.TRUE, "phrase_found", hits) if hits else EvalResult(Outcome.UNKNOWN, "no_matching_text")
        return evaluate
    if kind == "numeric_threshold":
        field = spec["field"]
        if field not in facts:
            raise ContractError(f"no fact supplied for field {field!r}")
        observation = FieldValue(field, _fact(facts[field]))

        def evaluate_numeric(packet, recovery):
            rules, ids = [], []
            for item in packet.items:
                m = pattern.search(item.span.text)
                member = members.get(item.span.revision_id)
                if m and member:
                    rules.append(PolicyRule(member, NumericRule(field, spec["operator"], Decimal(m.group(1)))))
                    ids.append(item.entry_id)
            if not rules:
                return EvalResult(Outcome.UNKNOWN, "no_threshold_found")
            r = evaluate_dated_numeric(observation, rules, as_of=as_of, request_entities=entities, historical_as_known=historical)
            return EvalResult(r.outcome, r.reason, tuple(ids))
        return evaluate_numeric
    raise ContractError(f"unknown evaluator kind {kind!r}")


def _need(spec: dict, inherited_evaluator: dict | None = None, **ctx: Any) -> NeedSpec:
    """A followup block may omit its evaluator and then reuses its parent's."""
    evaluator = spec.get("evaluator") or inherited_evaluator
    if evaluator is None:
        raise ContractError("every need requires an evaluator")
    follow = _need(spec["followup"], evaluator, **ctx) if "followup" in spec else None
    return NeedSpec(spec["query"], spec["want"], spec["max_bytes"], _evaluator(evaluator, **ctx), follow)


def _origin_lookup(cat: Catalog):
    def lookup(source_id: str) -> str | None:
        active_ids = {entry.revision_id for entry in load_live_entries(cat)
                      if cat.revision_source_id(entry.revision_id) == source_id}
        if len(active_ids) != 1:
            return None
        current = cat.get_revision(next(iter(active_ids)))
        if current.origin == f"api:{source_id}":
            # API imports are catalog-owned snapshots, not paths on disk.
            return current.revision_id
        try:
            raw = Path(current.origin).read_bytes()
            return SourceRevision.create(source_id, current.origin, decode_source(raw, encoding=current.decoded.encoding)).revision_id
        except (OSError, ContractError):
            return None
    return lookup


def cmd_ask(a: argparse.Namespace) -> tuple[dict[str, Any], int]:
    request = Request.from_dict(json.loads(Path(a.request).read_text(encoding="utf-8")))
    policy = json.loads(Path(a.policy).read_text(encoding="utf-8"))
    result, code = run_authored(a.catalog, request, policy)
    if a.trace_out:
        Path(a.trace_out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result, code


def run_authored(catalog: str | Path, request: Request, policy: dict) -> tuple[dict[str, Any], int]:
    """Run an explicit deterministic plan against the shared catalog."""
    if not isinstance(request, Request) or not isinstance(policy, dict):
        raise ContractError("request and policy objects are required")
    mode = policy.get("mode", "snapshot")
    if mode not in MODES:
        raise ContractError(f"unknown mode {mode!r}")
    plan = parse_plan(policy["plan"])
    entities, as_of = frozenset(policy.get("entities", ())), policy["as_of"]
    historical = bool(policy.get("historical_as_known", False))
    with Catalog.open(catalog) as cat:
        members = {r[0]: _member_from_row(r) for r in cat.metadata_rows()}
        specs, ledger = {}, ObligationLedger()
        for p in plan.predicates:
            need = policy["needs"][p.id]
            specs[p.id] = _need(need, members=members, facts=policy.get("facts", {}), entities=entities, as_of=as_of,
                                historical=historical)
            ledger.open(Obligation(f"ob-{p.id}", "exception" if need.get("kind") == "exception" else "predicate_evidence",
                                   p.id, p.question, material=True))
        entity_date_filter = applicability_filter(Collection(tuple(members.values())), entities, as_of, historical_as_known=historical)
        def scoped_filter(candidate):
            member = members.get(candidate.revision_id)
            if member is None or not request.scope or not member.scope:
                return Applicability.UNKNOWN
            if member.scope != request.scope:
                return Applicability.NO_MATCH
            return entity_date_filter(candidate)
        ctx = Context(cat, load_live_entries(cat), scoped_filter, specs)
        state = RunState(request, plan, ledger)
        summary = run_until_done(state, ctx)
        final = finalize(state, ctx, summary, mode=mode, lookup=_origin_lookup(cat))
        st = final.state
        result = {
            "policy_label": policy.get("label", ""),
            "request": request.to_dict(),
            "mode": mode,
            "status": final.status,
            "outcome": final.outcome,
            "reasons": list(final.reasons),
            "plan_origin": plan.origin,
            "plan_caveat": PLAN_CAVEAT,
            "observations": {k: {"outcome": v.outcome.value, "reason": v.reason} for k, v in st.observations.items()},
            "skipped": [{"predicate_id": s.predicate_id, "kind": s.kind, "witnesses": list(s.witnesses), "reason": s.reason} for s in final.summary.skipped],
            "refusals": [{"predicate_id": r.predicate_id, "reason": r.reason} for r in st.refusals],
            "conflicts": list(final.summary.conflicts),
            "origin_updates": [{"source_id": u.source_id, "used_revision_id": u.used_revision_id, "current_revision_id": u.current_revision_id} for u in final.origin_updates],
            "restarts": final.restarts,
            "obligations": [{"id": o.obligation_id, "kind": o.kind, "predicate_id": o.predicate_id, "material": o.material, "status": o.status, "reason": o.reason}
                            for o in (ledger.get(f"ob-{p.id}") for p in plan.predicates)],
            "records": [{
                "sequence": r.sequence, "predicate_id": r.predicate_id, "round": r.round_number, "query": r.query, "hit_count": r.hit_count,
                "retrieval_method": r.retrieval_method,
                "evidence": [{"entry_id": e.entry_id, "revision_id": e.revision_id, "source_id": cat.revision_source_id(e.revision_id),
                              "start": e.start, "end": e.end, "text_sha256": e.text_sha256, "text": e.text, "truncated": e.truncated} for e in r.evidence],
                "exclusions": [{"entry_id": x.entry_id, "reason": x.reason, "detail": x.detail} for x in r.exclusions],
                "observation": {"outcome": r.observation.outcome.value, "reason": r.observation.reason},
            } for r in st.trace],
            "providers_called": 0,
        }
    return result, (0 if final.status == "decided" else 3)


def render_trace(t: dict[str, Any]) -> str:
    lines = [f"Question: {t['request']['question']}"]
    label = f" [{t['policy_label']}]" if t.get("policy_label") else ""
    lines.append(f"Plan origin: {t['plan_origin']}{label}")
    lines.append(f"Plan caveat: {t['plan_caveat']}")
    verdict = "DECIDED" if t["status"] == "decided" else "DEFERRED"
    tail = f" -> {'yes' if t['outcome'] else 'no'}" if t["status"] == "decided" else ""
    lines.append(f"Result: {verdict}{tail}")
    if t["reasons"]:
        lines.append("Why not decided: " + ", ".join(t["reasons"]))
    for r in t["records"]:
        lines.append(f"\nStep {r['sequence']}: {r['predicate_id']} (attempt {r['round']}) searched \"{r['query']}\", {r['hit_count']} candidate(s)")
        for e in r["evidence"]:
            cut = " [truncated]" if e["truncated"] else ""
            lines.append(f"  Used {e['source_id']} chars {e['start']}-{e['end']}{cut}: \"{e['text']}\"")
        for x in r["exclusions"]:
            lines.append(f"  Excluded {x['entry_id'][:10]}: {x['reason']}")
        o = r["observation"]
        lines.append(f"  Finding: {o['outcome']} ({o['reason']})")
    open_items = [o for o in t["obligations"] if o["status"] not in ("satisfied", "skipped")]
    if open_items:
        lines.append("\nStill open:")
        for o in open_items:
            lines.append(f"  {o['predicate_id']}: {o['status']} ({o['reason'] or 'no reason recorded'})")
    for s in t["skipped"]:
        lines.append(f"Skipped {s['predicate_id']}: {s['reason']}")
    for u in t["origin_updates"]:
        lines.append(f"Source changed after import: {u['source_id']}")
    lines.append(f"Provider calls made: {t['providers_called']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qjig")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("import", help="add a source file to the catalog")
    i.add_argument("--catalog", required=True)
    i.add_argument("--source-id", required=True)
    i.add_argument("--file", required=True)
    i.add_argument("--encoding", required=True)
    i.add_argument("--scope", default="")
    i.add_argument("--authority")
    i.add_argument("--entity", action="append")
    i.add_argument("--effective-from", default="unknown")
    i.add_argument("--effective-to", default="unknown")
    i.add_argument("--observed-at")
    q = sub.add_parser("ask", help="run a plan against the catalog")
    q.add_argument("--catalog", required=True)
    q.add_argument("--request", required=True)
    q.add_argument("--policy", required=True)
    q.add_argument("--trace-out")
    server = sub.add_parser("serve", help="start the local catalog service")
    server.add_argument("--catalog", required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8766)
    t = sub.add_parser("trace", help="render a saved trace for a person")
    t.add_argument("--file", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from .service import create_server
            server = create_server(args.catalog, host=args.host, port=args.port)
            try:
                print(json.dumps({"host": server.server_address[0], "port": server.server_address[1]}), flush=True)
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        if args.command == "import":
            print(json.dumps(cmd_import(args)))
            return 0
        if args.command == "ask":
            result, code = cmd_ask(args)
            print(json.dumps(result))
            return code
        print(render_trace(json.loads(Path(args.file).read_text(encoding="utf-8"))))
        return 0
    except (ContractError, OSError, KeyError, ValueError, TypeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
