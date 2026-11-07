"""Gate inventory is not a completion or evidence-verification claim."""
import json
import pytest

from qjig.contracts import ContractError
from qjig.gates import build_gate_inventory, inspect_gate_inventory


def test_inventory_covers_goal_findings_repairs_and_original_tasks_without_claiming_proof():
    tasks = [{'id': 'R01', 'status': 'complete', 'finding': 'F01', 'command': 'test', 'evidence': 'claimed'},
             {'id': 'R08', 'status': 'pending', 'finding': 'F08'}]
    tasks += [{'id': f'T{i:03d}', 'status': 'pending'} for i in range(49, 75)]
    queue = json.dumps({'tasks': tasks}).encode()
    inventory = build_gate_inventory(queue, b'goal')
    entries = {entry['id']: entry for entry in inventory['gates']}
    assert len(entries) == 9 + 2 + 26
    assert entries['F01']['task_ids'] == ['R01']
    assert entries['R01']['queue_status'] == 'complete'
    assert entries['R01']['status'] == 'unverified'
    assert entries['R01']['evidence'] == []
    assert all(entry['status'] == 'unverified' for entry in entries.values())
    assert inspect_gate_inventory(inventory, queue, b'goal') == 'current_unverified'
    assert inspect_gate_inventory(inventory, queue, b'changed') == 'stale_or_invalid'
    entries['R01']['status'] = 'complete'
    assert inspect_gate_inventory(inventory, queue, b'goal') == 'stale_or_invalid'
    entries['R01']['status'] = 'unverified'
    inventory['complete'] = 0  # JSON number is not boolean false
    assert inspect_gate_inventory(inventory, queue, b'goal') == 'stale_or_invalid'


def test_inventory_rejects_missing_duplicate_and_malformed_task_records():
    tasks = [{'id': f'T{i:03d}', 'status': 'pending'} for i in range(49, 75)]
    for changed in (tasks[:-1], tasks + [tasks[0]], tasks + [{'id': 'R01', 'status': 'unknown'}]):
        with pytest.raises(ContractError):
            build_gate_inventory(json.dumps({'tasks': changed}).encode(), b'goal')
