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
                     reservation_factory=None, review_reservation_factory=None, want: int = 3, max_bytes: int = 3000,
                     assignment_binding=None, evidence_mode: str = 'catalog', planner_prompt_version: str = 'legacy_v1',
                     max_judge_pairs: int | None = None, planner_route: str | None = None,
                     judge_route: str | None = None, reviewer_route: str | None = None):
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
    if evidence_mode not in ('catalog','full'):
        raise ContractError('invalid fresh evidence mode')
    required_set = None
    if ledger._goal_budget is not None:
        from .evaluation_budget import verify_evaluation_assignment
        required_set = verify_evaluation_assignment(ledger._goal_budget, assignment_binding, case_id=lock_copy['case_id'],
            case_sha256=expected_case_sha256, design_sha256=expected_design_sha256,
            request_id=ledger._request_id, partition=ledger._partition)
        if assignment_binding['arm'] != ('combined' if evidence_mode == 'catalog' else 'decomposition_only'):
            raise ContractError('fresh evaluation arm differs')
    elif assignment_binding is not None:
        raise ContractError('evaluation assignment requires a goal ledger')
    checked = ApplicabilityInputs.from_dict(applicability_inputs.to_dict())
    if (checked.as_of != prepared.as_of or checked.request_entities != frozenset(prepared.entities)
            or checked.historical_as_known != prepared.historical_as_known):
        raise ContractError('case applicability context differs')
    revisions = [SourceRevision.create(s.path, 'evaluation_allowlist', decode_source(s.raw, encoding='utf-8')) for s in prepared.sources]
    if {r.revision_id for r in revisions} != {m.revision_id for m in checked.collection.members}:
        raise ContractError('case applicability source set differs')
    if evidence_mode == 'full':
        from .applicability import Applicability,combine_applicability,scope_applicability
        from .evaluation import _full_source_entries,_full_source_packet
        if any(combine_applicability(checked.verdict(r.revision_id),
                scope_applicability(prepared.scope,checked.collection.member(r.revision_id).scope)) is not Applicability.MATCH
                for r in revisions):
            raise ContractError('full source applicability is not established')
        _full_source_packet(_full_source_entries(revisions),max_bytes)
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
        if evidence_mode == 'full':
            entries = _full_source_entries(revisions)
        return run_fresh(request=request, catalog=catalog, entries=entries, ledger=ledger, transport=transport,
                         planner=planner, judge=judge, reviewer=reviewer, archive=archive,
                         revision_applicability=checked.verdict, applicability_inputs=checked,
                         evaluation_case_binding=binding, evaluation_assignment=assignment_binding, required_run_set=required_set,
                         planner_prompt_version=planner_prompt_version,max_judge_pairs=max_judge_pairs,
                         planner_route=planner_route,judge_route=judge_route,reviewer_route=reviewer_route,
                         full_source_evidence=evidence_mode == 'full',
                         planner_max_tokens=planner_max_tokens,
                         judge_max_tokens=judge_max_tokens, reviewer_max_tokens=reviewer_max_tokens,
                         planner_max_price=planner_max_price, judge_max_price=judge_max_price,
                         reviewer_max_price=reviewer_max_price, reservation_factory=reservation_factory,
                         review_reservation_factory=review_reservation_factory,
                         require_complete_reservations=ledger._goal_budget is not None, want=want, max_bytes=max_bytes)
