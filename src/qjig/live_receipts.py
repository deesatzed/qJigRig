"""Read-only structural inspection of a retained evaluation campaign.

This is not provider authentication, semantic validation, or dispatch authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .contracts import ContractError
from .costs import summarize_resources
from .evaluation_campaign import EvaluationCampaign, applicability_digest, check_archive_config
from .evaluation_scoring import reference_digest, score_reserved_assignment
from .journal import Journal
from .run_archive import RunArchive


def inspect_campaign_receipts(campaign: EvaluationCampaign, journal: Journal, archive_root: Path, *, references: dict,
                              expected_config_sha256: str | None = None, expected_run_sha256: dict | None = None,
                              expected_reference_sha256: dict | None = None, expected_journal_sha256: dict | None = None,
                              case_root: Path | None = None, case_inputs: dict | None = None) -> dict:
    """Inspect assigned work and retained scores without creating archives or calling providers.

    Callers must quiesce the separate stores and supply trusted external plan and
    reference anchors. Recorded transport labels remain caller assertions.
    """
    if not isinstance(campaign, EvaluationCampaign) or not isinstance(journal, Journal) or not isinstance(references, dict):
        raise ContractError('campaign, journal and reference mapping are required')
    manifest, assignments, started, scored = campaign._snapshot()
    issues, invalid = [], []
    if set(assignments) - started:
        issues.append('unstarted_assignments')
    if started - scored:
        issues.append('unfinished_assignments')
    config_row = campaign._goal._con.execute('SELECT value,sha256 FROM evaluation_campaign_config WHERE plan_id=?', (campaign._plan_id,)).fetchone()
    frozen = None
    if config_row is None:
        issues.append('campaign_configuration_unavailable')
    else:
        frozen = json.loads(config_row[0])
    if expected_config_sha256 is None:
        issues.append('configuration_anchor_unavailable')
    elif (not isinstance(expected_config_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_config_sha256)
          or config_row is None or expected_config_sha256 != config_row[1]):
        invalid.append('configuration_anchor_invalid')
    if expected_run_sha256 is None:
        expected_run_sha256 = {}
    if (not isinstance(expected_run_sha256, dict) or any(key not in assignments for key in expected_run_sha256)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in expected_run_sha256.values())):
        raise ContractError('invalid external run anchors')
    if scored - set(expected_run_sha256):
        issues.append('run_anchor_unavailable')
    if expected_reference_sha256 is None:
        expected_reference_sha256 = {}
    case_ids = {case['id'] for case in manifest['design']['cases']}
    if (not isinstance(expected_reference_sha256, dict) or any(key not in case_ids for key in expected_reference_sha256)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in expected_reference_sha256.values())):
        raise ContractError('invalid external reference anchors')
    if {assignments[rid]['case_id'] for rid in scored} - set(expected_reference_sha256):
        issues.append('reference_anchor_unavailable')
    if expected_journal_sha256 is None:
        expected_journal_sha256 = {}
    if (not isinstance(expected_journal_sha256, dict) or any(key not in assignments for key in expected_journal_sha256)
            or any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in expected_journal_sha256.values())):
        raise ContractError('invalid external journal anchors')
    checked_cases = 0
    if case_root is None or case_inputs is None:
        issues.append('case_inputs_unavailable')
    elif not isinstance(case_inputs, dict) or set(case_inputs) != case_ids:
        invalid.append('case_set_invalid')
    else:
        from .applicability import ApplicabilityInputs
        from .evaluation_cases import prepare_evaluation_case
        from .sources import SourceRevision, decode_source
        for case_id in sorted(case_ids):
            try:
                data = case_inputs[case_id]
                if not isinstance(data, dict) or set(data) != {'lock', 'reference', 'protected', 'applicability_inputs'}:
                    raise ContractError('invalid case inputs')
                if case_id not in references or case_id not in expected_reference_sha256:
                    issues.append('case_reference_anchor_unavailable')
                    continue
                if (data['reference'] != references[case_id]
                        or reference_digest(data['reference']) != expected_reference_sha256[case_id]):
                    raise ContractError('external case reference differs')
                prepared = prepare_evaluation_case(case_root, manifest['design'], data['lock'], data['reference'], data['protected'],
                    expected_design_sha256=manifest['design_sha256'], expected_case_sha256=manifest['case_hashes'][case_id])
                inputs = data['applicability_inputs']
                if not isinstance(inputs, ApplicabilityInputs):
                    raise ContractError('case applicability unavailable')
                if frozen is None:
                    issues.append('case_configuration_unavailable')
                    continue
                revisions = {SourceRevision.create(source.path, 'evaluation_allowlist', decode_source(source.raw, encoding='utf-8')).revision_id
                             for source in prepared.sources}
                if (applicability_digest(inputs) != frozen['case_applicability'][case_id]
                        or inputs.as_of != prepared.as_of or inputs.request_entities != frozenset(prepared.entities)
                        or inputs.historical_as_known != prepared.historical_as_known
                        or revisions != {member.revision_id for member in inputs.collection.members}):
                    raise ContractError('case applicability differs')
                checked_cases += 1
            except (OSError, ContractError, ValueError, TypeError, KeyError, IndexError):
                invalid.append('case_inputs_invalid')
    audit = campaign._goal.audit_journal(journal)
    if audit['status'] == 'invalid':
        invalid.append('goal_journal_invalid')
    elif audit['status'] != 'verified':
        issues.append('goal_journal_incomplete')
    resources = summarize_resources(journal)['total']
    if resources['unknown_usage_calls']:
        issues.append('usage_unknown')
    if not resources['calls']:
        issues.append('no_recorded_calls')
    for event in journal.all_events():
        if event.kind == 'receipt' and event.payload.get('transport') != 'LIVE: openrouter, real model call':
            issues.append('provider_attribution_not_live')
            break
    base = Path(archive_root)
    if base.is_symlink():
        raise ContractError('campaign archive root must not be a symlink')
    checked = 0
    for request_id in sorted(scored):
        if not re.fullmatch(r'qj-[0-9a-f]{64}', request_id):
            invalid.append('unsafe_request_identity')
            continue
        assignment = assignments[request_id]
        reference = references.get(assignment['case_id'])
        if reference is None:
            issues.append('reference_unavailable')
            continue
        directory, db = base / request_id, base / request_id / 'run.sqlite'
        if directory.is_symlink() or db.is_symlink() or not directory.is_dir() or not db.is_file():
            issues.append('archive_unavailable')
            continue
        row = campaign._goal._con.execute("SELECT payload FROM evaluation_campaign_events WHERE plan_id=? AND request_id=? AND kind='scored'", (campaign._plan_id, request_id)).fetchone()
        try:
            receipt = json.loads(row[0])
            if request_id in expected_run_sha256 and receipt['run_sha256'] != expected_run_sha256[request_id]:
                raise ContractError('external run anchor differs')
            case_id = assignment['case_id']
            if case_id in expected_reference_sha256 and receipt['reference_sha256'] != expected_reference_sha256[case_id]:
                raise ContractError('external reference anchor differs')
            if receipt['journal_sha256'] is not None:
                if request_id not in expected_journal_sha256:
                    issues.append('journal_anchor_unavailable')
                elif receipt['journal_sha256'] != expected_journal_sha256[request_id]:
                    raise ContractError('external journal anchor differs')
            if reference_digest(reference) != receipt['reference_sha256']:
                raise ContractError('reference digest differs')
            con = sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None)
            with RunArchive(con) as archive:
                if frozen is not None:
                    check_archive_config(frozen, archive.context(), assignment)
                score = score_reserved_assignment(campaign._goal, archive, journal, reference,
                    partition=assignment['work'][0]['partition'], expected_plan_sha256=campaign._digest,
                    expected_run_sha256=receipt['run_sha256'], expected_reference_sha256=receipt['reference_sha256'],
                    expected_journal_sha256=receipt['journal_sha256'])
            encoded = json.dumps(score, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
            if hashlib.sha256(encoded).hexdigest() != receipt['score_sha256']:
                raise ContractError('score digest differs')
            checked += 1
        except (OSError, sqlite3.Error, ContractError, ValueError, TypeError, KeyError, IndexError):
            invalid.append('scored_receipt_invalid')
    return {'status': 'invalid' if invalid else 'incomplete' if issues else 'structurally_complete',
            'assigned': len(assignments), 'scored': len(scored), 'checked': checked, 'checked_cases': checked_cases,
            'issues': sorted(set(invalid + issues)), 'resources': resources,
            'provider_authenticity': 'not_established', 'semantic_assurance': 'not_assessed',
            'label_isolation': 'declared_exact_artifacts_only'}
