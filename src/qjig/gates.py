"""Fail-closed inventory of completion gates; queue claims are not proof."""
from __future__ import annotations

import hashlib
import json
import re

from .contracts import ContractError


def build_gate_inventory(queue_bytes: bytes, goal_bytes: bytes) -> dict:
    """Map required identifiers to queue assertions without verifying outcomes.

    This initial inventory never marks a gate complete and stores no invented
    commands, exit codes, counts, or evidence receipts.
    """
    if not isinstance(queue_bytes, bytes) or not isinstance(goal_bytes, bytes) or not goal_bytes:
        raise ContractError('queue and goal bytes are required')
    try:
        tasks = json.loads(queue_bytes)['tasks']
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise ContractError('task queue is invalid') from None
    if not isinstance(tasks, list):
        raise ContractError('task queue is invalid')
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise ContractError('task record is invalid')
        ident = task.get('id')
        if not isinstance(ident, str) or not ident or ident in by_id or task.get('status') not in ('pending', 'complete'):
            raise ContractError('task identity or status is invalid')
        by_id[ident] = task
    required = [f'T{i:03d}' for i in range(49, 75)]
    if any(ident not in by_id for ident in required):
        raise ContractError('required task missing')
    repairs = sorted(ident for ident in by_id if re.fullmatch(r'R\d\d[A-Z]*', ident))
    gates = []
    for number in range(1, 10):
        ident = f'F{number:02d}'
        matches = [rid for rid in repairs if rid.startswith(f'R{number:02d}') or by_id[rid].get('finding') == ident]
        gates.append({'id': ident, 'status': 'unverified', 'task_ids': matches, 'evidence': []})
    for ident in repairs + required:
        task = by_id[ident]
        gates.append({'id': ident, 'status': 'unverified', 'task_ids': [ident], 'evidence': [],
                      'queue_status': task['status'], 'queue_command': task.get('command'),
                      'queue_evidence_assertion': task.get('evidence')})
    return {'schema': 'qjig.gate-inventory.v1', 'goal_sha256': hashlib.sha256(goal_bytes).hexdigest(),
            'queue_sha256': hashlib.sha256(queue_bytes).hexdigest(), 'gates': gates,
            'assurance': 'queue_assertions_not_verified', 'complete': False}


def inspect_gate_inventory(inventory: object, queue_bytes: bytes, goal_bytes: bytes) -> str:
    """Return an explicit stale/invalid result; never certify gate completion."""
    try:
        expected = build_gate_inventory(queue_bytes, goal_bytes)
        actual_json = json.dumps(inventory, sort_keys=True, separators=(',', ':'), allow_nan=False)
        expected_json = json.dumps(expected, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ContractError, TypeError, ValueError):
        return 'stale_or_invalid'
    return 'current_unverified' if actual_json == expected_json else 'stale_or_invalid'
