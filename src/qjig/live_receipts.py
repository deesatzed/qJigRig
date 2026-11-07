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
from .evaluation_campaign import EvaluationCampaign, check_archive_config
from .evaluation_scoring import reference_digest, score_reserved_assignment
from .journal import Journal
from .run_archive import RunArchive


def inspect_campaign_receipts(campaign: EvaluationCampaign, journal: Journal, archive_root: Path, *, references: dict,
                              expected_config_sha256: str | None = None, expected_run_sha256: dict | None = None) -> dict:
    """Inspect assigned work and retained scores without creating archives or calling providers.

    Callers must quiesce the separate stores and supply trusted external plan and
    reference anchors. Recorded transport labels remain caller assertions.
    """
    if not isinstance(campaign, EvaluationCampaign) or not isinstance(journal, Journal) or not isinstance(references, dict):
        raise ContractError('campaign, journal and reference mapping are required')
    _, assignments, started, scored = campaign._snapshot()
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
            'assigned': len(assignments), 'scored': len(scored), 'checked': checked,
            'issues': sorted(set(invalid + issues)), 'resources': resources,
            'provider_authenticity': 'not_established', 'semantic_assurance': 'not_assessed'}
