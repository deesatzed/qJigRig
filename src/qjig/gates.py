"""Fail-closed inventory of completion gates; queue claims are not proof."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from .contracts import ContractError


def build_gate_inventory(queue_bytes: bytes, goal_bytes: bytes, *, receipt_catalog_bytes: bytes | None = None) -> dict:
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
    result = {'schema': 'qjig.gate-inventory.v1', 'goal_sha256': hashlib.sha256(goal_bytes).hexdigest(),
              'queue_sha256': hashlib.sha256(queue_bytes).hexdigest(), 'gates': gates,
              'assurance': 'queue_assertions_not_verified', 'complete': False}
    if receipt_catalog_bytes is not None:
        try:
            if not isinstance(receipt_catalog_bytes, bytes):
                raise ValueError('invalid catalog')
            catalog = json.loads(receipt_catalog_bytes)
            if (not isinstance(catalog, dict) or set(catalog) != {'schema', 'receipts'}
                    or catalog['schema'] != 'qjig.check-receipts.v1' or not isinstance(catalog['receipts'], list)):
                raise ValueError('invalid catalog')
        except (ValueError, UnicodeDecodeError):
            raise ContractError('receipt catalog is invalid') from None
        result['receipt_catalog_sha256'] = hashlib.sha256(receipt_catalog_bytes).hexdigest()
    return result


def inspect_gate_inventory(inventory: object, queue_bytes: bytes, goal_bytes: bytes, *, receipt_catalog_bytes: bytes | None = None) -> str:
    """Return an explicit stale/invalid result; never certify gate completion."""
    try:
        expected = build_gate_inventory(queue_bytes, goal_bytes, receipt_catalog_bytes=receipt_catalog_bytes)
        actual_json = json.dumps(inventory, sort_keys=True, separators=(',', ':'), allow_nan=False)
        expected_json = json.dumps(expected, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ContractError, TypeError, ValueError):
        return 'stale_or_invalid'
    return 'current_unverified' if actual_json == expected_json else 'stale_or_invalid'


def inspect_check_receipt(receipt: object, root: Path, known_gates: set[str]) -> str:
    """Check a caller-reported command record and its local artifact hashes.

    Matching hashes do not authenticate who ran a command, its output, or its
    relevance to an entire gate. No command is executed by this function.
    """
    try:
        keys = {'schema', 'gate_ids', 'command', 'exit_code', 'counts', 'output', 'inputs', 'assurance', 'observed_at_utc'}
        if (not isinstance(receipt, dict) or set(receipt) != keys or receipt['schema'] != 'qjig.check-receipt.v1'
                or receipt['assurance'] != 'caller_reported_execution' or not isinstance(known_gates, set)):
            return 'invalid'
        gates, command, code, counts = (receipt[k] for k in ('gate_ids', 'command', 'exit_code', 'counts'))
        observed = datetime.fromisoformat(receipt['observed_at_utc'])
        if observed.utcoffset() != timedelta(0):
            return 'invalid'
        if (not isinstance(gates, list) or not gates or any(not isinstance(x, str) or x not in known_gates for x in gates)
                or len(gates) != len(set(gates)) or not isinstance(command, list) or not command
                or any(not isinstance(x, str) or not x or '\x00' in x for x in command)
                or type(code) is not int or not -255 <= code <= 255 or not isinstance(counts, dict)
                or set(counts) != {'passed', 'failed', 'skipped'}
                or any(type(value) is not int or value < 0 for value in counts.values())
                or (code == 0 and counts['failed'] != 0)):
            return 'invalid'
        inputs = receipt['inputs']
        if not isinstance(inputs, list) or not inputs:
            return 'invalid'
        base = Path(root).resolve()
        for artifact in [receipt['output'], *inputs]:
            if (not isinstance(artifact, dict) or set(artifact) != {'path', 'sha256'}
                    or not isinstance(artifact['path'], str) or not artifact['path']
                    or not isinstance(artifact['sha256'], str)
                    or not re.fullmatch(r'[0-9a-f]{64}', artifact['sha256'])):
                return 'invalid'
            relative = Path(artifact['path'])
            if relative.is_absolute() or '..' in relative.parts:
                return 'invalid'
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > 10_000_000:
                return 'invalid'
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                return 'invalid'
    except (OSError, ValueError, TypeError, RuntimeError):
        return 'invalid'
    return 'recorded_success' if code == 0 else 'recorded_failure'
