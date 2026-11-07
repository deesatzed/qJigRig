"""Gate inventory is not a completion or evidence-verification claim."""
import json
import pytest

from qjig.contracts import ContractError
from qjig.gates import build_gate_inventory, inspect_gate_inventory, inspect_check_receipt


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


def test_inventory_binds_receipt_catalog_without_promoting_gates():
    tasks = [{'id': f'T{i:03d}', 'status': 'pending'} for i in range(49, 75)]
    queue = json.dumps({'tasks': tasks}).encode()
    catalog = b'{"schema":"qjig.check-receipts.v1","receipts":[]}'
    inventory = build_gate_inventory(queue, b'goal', receipt_catalog_bytes=catalog)
    assert inventory['receipt_catalog_sha256'] is not None
    assert inspect_gate_inventory(inventory, queue, b'goal', receipt_catalog_bytes=catalog) == 'current_unverified'
    assert inspect_gate_inventory(inventory, queue, b'goal', receipt_catalog_bytes=b'changed') == 'stale_or_invalid'
    assert all(gate['status'] == 'unverified' for gate in inventory['gates'])


def test_inventory_rejects_missing_duplicate_and_malformed_task_records():
    tasks = [{'id': f'T{i:03d}', 'status': 'pending'} for i in range(49, 75)]
    for changed in (tasks[:-1], tasks + [tasks[0]], tasks + [{'id': 'R01', 'status': 'unknown'}]):
        with pytest.raises(ContractError):
            build_gate_inventory(json.dumps({'tasks': changed}).encode(), b'goal')


def test_check_receipt_verifies_artifacts_without_claiming_gate_completion(tmp_path):
    import hashlib
    source = tmp_path / 'test.py'; source.write_text('test source')
    output = tmp_path / 'output.txt'; output.write_text('2 passed in 0.1s\n')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {'schema': 'qjig.check-receipt.v1', 'gate_ids': ['F09'],
               'command': ['python', '-m', 'pytest', 'test.py', '-q'], 'exit_code': 0,
               'observed_at_utc': '2026-11-07T12:00:00+00:00',
               'counts': {'passed': 2, 'failed': 0, 'skipped': 0},
               'output': {'path': 'output.txt', 'sha256': digest(output)},
               'inputs': [{'path': 'test.py', 'sha256': digest(source)}],
               'assurance': 'caller_reported_execution'}
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'recorded_success'
    assert inspect_check_receipt(receipt, tmp_path, {'F08'}) == 'invalid'
    receipt['exit_code'] = 1
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'recorded_failure'
    receipt['exit_code'] = 0
    receipt['output']['path'] = '../outside'
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'invalid'
    receipt['output']['path'] = 'output.txt'
    receipt['counts']['passed'] = True
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'invalid'
    receipt['counts']['passed'] = 2
    receipt['counts']['failed'] = 1
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'invalid'
    receipt['counts']['failed'] = 0
    source.write_text('changed')
    assert inspect_check_receipt(receipt, tmp_path, {'F09'}) == 'invalid'
