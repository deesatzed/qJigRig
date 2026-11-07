"""T048 opt-in LIVE run of run_fresh: deepseek plans, Hy4 judges. SYNTHETIC authored corpus; proves the path, not quality.
Usage: python scripts/smoke_t048.py ENV_FILE OUT_JSON [RUNS]"""
import dataclasses, json, sys, tempfile
from pathlib import Path

from qjig.acquisition import run_fresh
from qjig.applicability import Applicability
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import current_entries, index_entries, save_entries
from qjig.journal import Journal
from qjig.providers import OpenRouterTransport
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog

TEXT = b"# Refunds\nRefunds are accepted within 14 days of purchase.\n\n# Exceptions\nDefective items may be refunded within 30 days.\n"
PLANNER, JUDGE, CAP = "deepseek/deepseek-v4.1-flash-1017", "tencent/hy4", 6000


def main(env, out, runs):
    transport = OpenRouterTransport(Path(env))
    rev = SourceRevision.create("sample/refunds.md", "synthetic", decode_source(TEXT, encoding="utf-8"))
    report = {"label": transport.label, "corpus": "SYNTHETIC authored sample", "runs": []}
    for n in range(runs):
        rid = f"t048-{n}"
        request = Request(rid, "Can customer 42 get a refund 20 days after purchase?", "reviewer", "1", "project")
        with tempfile.TemporaryDirectory() as d:
            cat = Catalog.open(Path(d) / "c.sqlite"); cat.add_revision(rev); save_entries(cat, index_entries(rev))
            entries = current_entries(cat, rev.source_id, rev.revision_id)
            j = Journal.open(Path(d) / "j.sqlite"); ledger = BudgetLedger(Budget(20, 120000, 5.0), j, rid)
            with cat, j:
                run = run_fresh(request=request, catalog=cat, entries=entries, ledger=ledger, transport=transport,
                                planner=("openrouter", PLANNER), judge=("openrouter", JUDGE),
                                revision_applicability=lambda r: Applicability.MATCH,
                                planner_max_tokens=CAP, judge_max_tokens=CAP)
                rec = {"status": run.status, "reasons": run.reasons, "plan_failure": run.plan_failure,
                       "predicates": [(p.id, p.question) for p in run.state.plan.predicates] if run.state else None,
                       "expression": run.state.plan.expression if run.state else None,
                       "observations": {k: (v.outcome.value, v.reason) for k, v in run.state.observations.items()} if run.state else None,
                       "quote_refs": {k: [dataclasses.asdict(r) for r in v] for k, v in run.quote_refs.items()},
                       "coverage_candidates": run.coverage_candidates,
                       "calls": ledger.used_calls(), "cost_usd": ledger.known_cost_usd(), "cost_status": ledger.cost_status()}
                report["runs"].append(rec)
                print(n, run.status, run.reasons, rec["observations"], rec["calls"], rec["cost_usd"])
    Path(out).write_text(json.dumps(report, indent=1, default=str))


main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1)
