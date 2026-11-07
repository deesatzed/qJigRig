"""Fresh evaluation over one checked source snapshot; no hosted authorization."""
from __future__ import annotations

import json

from .acquisition import run_fresh
from .applicability import ApplicabilityInputs
from .budgets import BudgetLedger
from .cli import _member_row
from .contracts import ContractError, Request
from .evaluation_cases import prepare_evaluation_case
from .indexing import index_entries, save_entries
from .run_archive import RunArchive
from .sources import SourceRevision, decode_source
from .store import Catalog


def run_locked_fresh(root, design: dict, lock: dict, reference: dict, protected: list[dict], *,
                     expected_design_sha256: str, expected_case_sha256: str, applicability_inputs: ApplicabilityInputs,
                     ledger: BudgetLedger, transport, archive: RunArchive, planner: tuple[str, str], judge: tuple[str, str],
                     reviewer: tuple[str, str] | None = None, planner_max_tokens: int | None = None,
                     judge_max_tokens: int | None = None, reviewer_max_tokens: int = 800,
                     planner_max_price=None, judge_max_price=None, reviewer_max_price=None,
                     reservation_factory=None, review_reservation_factory=None, want: int = 3, max_bytes: int = 3000):
    """Run one checked case in an isolated catalog with explicit source metadata.

    Metadata and protected-manifest completeness are caller assertions. This
    does not authenticate sources or authorize hosted dispatch.
    """
    try:
        lock_copy = json.loads(json.dumps(lock, ensure_ascii=False, allow_nan=False))
        reference_copy = json.loads(json.dumps(reference, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('invalid private case data') from exc
    prepared = prepare_evaluation_case(root, design, lock_copy, reference_copy, protected,
                                       expected_design_sha256=expected_design_sha256,
                                       expected_case_sha256=expected_case_sha256)
    if not isinstance(applicability_inputs, ApplicabilityInputs) or not isinstance(ledger, BudgetLedger) or not isinstance(archive, RunArchive):
        raise ContractError('explicit applicability, ledger and archive are required')
    checked = ApplicabilityInputs.from_dict(applicability_inputs.to_dict())
    if (checked.as_of != prepared.as_of or checked.request_entities != frozenset(prepared.entities)
            or checked.historical_as_known != prepared.historical_as_known):
        raise ContractError('case applicability context differs')
    revisions = [SourceRevision.create(s.path, 'evaluation_allowlist', decode_source(s.raw, encoding='utf-8')) for s in prepared.sources]
    if {r.revision_id for r in revisions} != {m.revision_id for m in checked.collection.members}:
        raise ContractError('case applicability source set differs')
    binding = {'case_id':lock_copy['case_id'], 'design_sha256':expected_design_sha256,
               'case_sha256':expected_case_sha256, 'reference_sha256':lock_copy['reference_sha256']}
    request = Request(ledger._request_id, prepared.question, prepared.role, prepared.role_version, prepared.scope)
    with Catalog.open(':memory:') as catalog:
        entries = []
        for revision in revisions:
            catalog.add_revision(revision)
            catalog.put_metadata_row(_member_row(revision.revision_id, checked.collection.member(revision.revision_id)))
            indexed = index_entries(revision)
            save_entries(catalog, indexed)
            entries.extend(indexed)
        return run_fresh(request=request, catalog=catalog, entries=entries, ledger=ledger, transport=transport,
                         planner=planner, judge=judge, reviewer=reviewer, archive=archive,
                         revision_applicability=checked.verdict, applicability_inputs=checked,
                         evaluation_case_binding=binding, planner_max_tokens=planner_max_tokens,
                         judge_max_tokens=judge_max_tokens, reviewer_max_tokens=reviewer_max_tokens,
                         planner_max_price=planner_max_price, judge_max_price=judge_max_price,
                         reviewer_max_price=reviewer_max_price, reservation_factory=reservation_factory,
                         review_reservation_factory=review_reservation_factory,
                         require_complete_reservations=ledger._goal_budget is not None, want=want, max_bytes=max_bytes)
