"""T046 opt-in LIVE smoke: one real planner call and one paired real judge call, with receipts.

Run by hand only; never part of the offline suite. The corpus below is a SYNTHETIC authored sample used as input.
It proves the provider path works (or how it fails); it is not evidence about decision quality.
Usage: python scripts/smoke_t046.py ENV_FILE OUT_JSON
"""
from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
from pathlib import Path

from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.judge import judge_predicate
from qjig.packets import build_packet
from qjig.planner import request_fresh_plan
from qjig.providers import OpenRouterTransport
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source

PRIMARY = "tencent/hy4"
CAP = 6000  # owner-approved raise for Hy4, which spends tokens on hidden reasoning
FALLBACK = "deepseek/deepseek-v4.1-flash-1017"
TEXT = b"# Refunds\nRefunds are accepted within 14 days of purchase.\n\n# Exceptions\nDefective items may be refunded within 30 days.\n"
QUESTION = "Is a purchase made 20 days ago inside the standard 14 day refund window?"


def main(env_file: str, out: str) -> int:
    transport = OpenRouterTransport(Path(env_file))
    rev = SourceRevision.create("sample/refunds.md", "synthetic", decode_source(TEXT, encoding="utf-8"))
    packet = build_packet(bm25_candidates(index_entries(rev), "refund days"), max_bytes=3000)
    request = Request("t046-smoke", "Can customer 42 get a refund 20 days after purchase?", "reviewer", "1", "project")
    results = {"label": transport.label, "corpus": "SYNTHETIC authored sample", "stages": []}
    with tempfile.TemporaryDirectory() as d:
        journal = Journal.open(Path(d) / "j.sqlite")
        ledger = BudgetLedger(Budget(12, 80000, 5.0), journal, request.request_id)
        with journal:
            for stage, run in (
                ("planner", lambda m: request_fresh_plan(ledger, transport, request, corpus_revision_ids=[rev.revision_id], provider="openrouter", model=m, max_tokens=CAP)),
                ("judge", lambda m: judge_predicate(ledger, transport, QUESTION, packet, provider="openrouter", model=m, max_tokens=CAP)),
            ):
                for model in (PRIMARY, FALLBACK):
                    try:
                        r = run(model)
                        ok = r.ok if stage == "planner" else not any(s.failure for s in (r.positive, r.negative))
                        summary = dataclasses.asdict(r) if dataclasses.is_dataclass(r) else str(r)
                    except Exception as exc:  # recorded, never hidden
                        ok, summary = False, {"exception": type(exc).__name__, "detail": str(exc)}
                    results["stages"].append({"stage": stage, "model": model, "ok": ok, "result": summary})
                    if ok:
                        break
            results["events"] = [
                {"call_id": e.call_id, "kind": e.kind, "stage": e.stage, "model": e.model, "payload": e.payload}
                for e in journal.events(request.request_id)
            ]
            results["used_calls"] = ledger.used_calls()
            results["known_cost_usd"] = ledger.known_cost_usd()
            results["cost_status"] = ledger.cost_status()
    Path(out).write_text(json.dumps(results, indent=1, default=str))
    for s in results["stages"]:
        print(s["stage"], s["model"], "ok" if s["ok"] else "FAILED")
    print("calls", results["used_calls"], "cost", results["known_cost_usd"], results["cost_status"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
