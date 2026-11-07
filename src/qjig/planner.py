"""Fresh model-generated plans: bounded, validated, bound to request, corpus and model, never trusted."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .budgets import BudgetLedger
from .contracts import Request
from .plans import Plan, PlanError, parse_plan
from .providers import ProviderRequest, Transport, call_typed

CAVEATS = ("completeness_not_established", "model_generated_untrusted")
PLANNER_MAX_TOKENS = 1500


def corpus_manifest_sha256(revision_ids: Iterable[str]) -> str:
    """Order-independent identity of the set of source revisions a plan was made against."""
    return hashlib.sha256("\n".join(sorted(set(revision_ids))).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlanBinding:
    request_id: str
    corpus_manifest_sha256: str
    provider: str
    model: str
    prompt_sha256: str
    call_id: str
    raw_sha256: str


@dataclass(frozen=True)
class PlannerOutcome:
    ok: bool
    plan: Plan | None
    binding: PlanBinding | None
    failure: str | None
    caveats: tuple[str, ...]


def _planner_prompt(request: Request, corpus_sha: str) -> str:
    return (
        "Break the question into 1 to 6 yes/no predicates and one expression over them using only "
        'and/or/not. Return ONLY JSON {"predicates":[{"id","question","depends_on"?,"exact_operator"?}],'
        '"expression":{"op":"and|or|not","args":[...]} | {"ref":"id"}}. Do not include code, origin or comments.\n'
        f"Question: {request.question}\nRole: {request.role} v{request.role_version}\nScope: {request.scope}\n"
        f"Corpus manifest: {corpus_sha}"
    )


def _plan_validator(text: str) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None, "malformed_output"
    if not isinstance(data, dict):
        return None, "malformed_output"
    if "origin" in data:
        return None, "plan_invalid:model_supplied_origin"
    try:
        parse_plan({**data, "origin": "fresh"})
    except PlanError as exc:
        return None, f"plan_invalid:{exc.code}"
    return data, None


def request_fresh_plan(
    ledger: BudgetLedger, transport: Transport, request: Request, *, corpus_revision_ids: Iterable[str], provider: str, model: str
) -> PlannerOutcome:
    corpus_sha = corpus_manifest_sha256(corpus_revision_ids)
    pr = ProviderRequest("planner", provider, model, _planner_prompt(request, corpus_sha), PLANNER_MAX_TOKENS)
    call = call_typed(ledger, transport, pr, _plan_validator)
    if not call.ok:
        return PlannerOutcome(False, None, None, call.failure, CAVEATS)
    plan = parse_plan({**call.value, "origin": "fresh"})
    binding = PlanBinding(request.request_id, corpus_sha, provider, model, pr.input_sha256(), call.call_id, call.raw_sha256)
    return PlannerOutcome(True, plan, binding, None, CAVEATS)
