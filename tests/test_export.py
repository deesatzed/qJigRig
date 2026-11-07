"""Synthetic deterministic exports; verification makes no provider calls."""
import copy
import hashlib
import json
import pytest
from qjig.contracts import ContractError
import threading
from qjig.agents import RoleClient
from qjig.export import export_authored, verify_authored_export
from qjig.roles import RoleDefinition
from qjig.service import create_server
from qjig.store import Catalog


def test_authored_export_verifies_bound_source_spans_after_change(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '2', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds are accepted within 14 days.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        rev = client.import_source(source)['revision_id']
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds days', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        response = client.ask('r', 'Refund?', 'project', policy)
        with Catalog.open(path) as catalog:
            bundle = export_authored(catalog, response['result'], policy, response['source_state_after'])
        assert bundle['payload']['result']['request']['role_version'] == '2'
        assert bundle['payload']['sources'][rev]['source_id'] == 'policy.md'
        assert verify_authored_export(bundle)['status'] == 'unanchored'
        digest = bundle['sha256']
        detail = client.get_source(rev)
        offset = detail['text'].index('14')
        client.intervene(rev, detail['text_sha256'], offset, offset + 2, '30')
        report = verify_authored_export(bundle, expected_digest=digest)
        assert report['status'] == 'structurally_verified' and report['semantic_assurance'] == 'not_assessed'
        altered = copy.deepcopy(bundle)
        altered['payload']['result']['records'][0]['evidence'][0]['text'] = 'fabricated'
        assert verify_authored_export(altered, expected_digest=digest)['status'] == 'invalid'
        altered['sha256'] = hashlib.sha256(json.dumps(altered['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        assert verify_authored_export(altered)['status'] == 'invalid'
        with Catalog.open(path) as catalog, pytest.raises(ContractError, match='changed'):
            export_authored(catalog, response['result'], policy, response['source_state_after'])
        assert bundle['payload']['resources']['cost_usd'] is None

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_authored_export_preserves_deferred_result_and_missing_evidence(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '2', 'Review'))
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Exception?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'kind': 'exception', 'query': 'no matching source', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'phrase_present', 'pattern': 'exception'}}}}
        response = client.ask('r', 'Exception?', 'project', policy)
        assert response['result']['status'] == 'deferred'
        with Catalog.open(path) as catalog:
            bundle = export_authored(catalog, response['result'], policy, response['source_state_after'])
        assert bundle['payload']['result']['outcome'] is None and bundle['payload']['sources'] == {}
        assert bundle['payload']['resources']['cost_usd'] is None
        assert verify_authored_export(bundle, expected_digest=bundle['sha256'])['status'] == 'structurally_verified'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_service_reopens_original_authored_run_after_source_change(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '2', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds are accepted within 14 days.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        rev = client.import_source(source)['revision_id']
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds days', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        response = client.ask('original', 'Refund?', 'project', policy)
        assert response['result']['outcome'] is False and response['run_id']
        run_id = response['run_id']
        original = client.get_run(run_id)
        assert original['verification']['status'] == 'unanchored'
        assert original['bundle']['payload']['result'] == response['result']
        detail = client.get_source(rev)
        offset = detail['text'].index('14')
        client.intervene(rev, detail['text_sha256'], offset, offset + 2, '30')
        assert client.ask('changed', 'Refund?', 'project', policy)['result']['outcome'] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    restarted = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=restarted.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(restarted.server_address[1], RoleDefinition('builder', '1', 'Build'))
        reopened = client.get_run(run_id)
        assert reopened == original
        assert any(x['run_id'] == run_id for x in client.list_runs())
        assert reopened['bundle']['payload']['result']['request']['role_version'] == '2'
        assert reopened['bundle']['payload']['result']['outcome'] is False
    finally:
        restarted.shutdown()
        restarted.server_close()
        thread.join(timeout=5)


def test_catalog_change_between_export_and_storage_defers_without_record(tmp_path, monkeypatch):
    import qjig.service as service
    path = tmp_path / 'catalog.sqlite'
    servers = [create_server(path, host='127.0.0.1', port=0) for _ in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    try:
        a, b = [RoleClient(s.server_address[1], RoleDefinition('reviewer', '1', 'Review')) for s in servers]
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds apply.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        a.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Refunds?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'phrase_present', 'pattern': 'Refunds apply'}}}}
        original = service.export_authored
        def change_after_export(*args, **kwargs):
            bundle = original(*args, **kwargs)
            b.import_source({**source, 'source_id': 'other.md', 'text': '# Other\nOther text.\n'})
            return bundle
        monkeypatch.setattr(service, 'export_authored', change_after_export)
        response = a.ask('r', 'Refunds?', 'project', policy)
        assert response['result']['status'] == 'deferred' and response['result']['outcome'] is None
        assert 'catalog_changed_during_run' in response['result']['reasons'] and response['run_id'] is None
        assert a.list_runs() == []
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


def test_stored_run_with_changed_payload_is_refused(tmp_path):
    import sqlite3
    from qjig.agents import ClientError
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Anything?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'nothing', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'phrase_present', 'pattern': 'anything'}}}}
        run_id = client.ask('r', 'Anything?', 'project', policy)['run_id']
        with sqlite3.connect(path) as con:
            con.execute('DROP TRIGGER authored_runs_no_update')
            con.execute('UPDATE authored_runs SET bundle=? WHERE run_id=?', ('{}', run_id))
        with pytest.raises(ClientError):
            client.get_run(run_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_authored_export_rejects_rehashed_inconsistent_outcome(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds are accepted within 14 days.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        client.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds days', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        response = client.ask('r', 'Refund?', 'project', policy)
        bundle = client.get_run(response['run_id'])['bundle']
        assert bundle['payload']['result']['outcome'] is False
        for change in ('outcome', 'observation'):
            altered = copy.deepcopy(bundle)
            result = altered['payload']['result']
            if change == 'outcome':
                result['outcome'] = True
            else:
                result['observations']['p']['outcome'] = 'true'
            altered['sha256'] = hashlib.sha256(json.dumps(altered['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            assert verify_authored_export(altered)['status'] == 'invalid'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_authored_export_rechecks_skipped_obligation_witness(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'rule.md', 'text': '# Rule\nRefunds apply.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        client.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Refunds?'}, {'id': 'q', 'question': 'Waiver?'}],
                           'expression': {'op': 'or', 'args': [{'ref': 'p'}, {'ref': 'q'}]}},
                  'needs': {'p': {'query': 'refunds', 'want': 1, 'max_bytes': 4000, 'evaluator': {'kind': 'phrase_present', 'pattern': 'Refunds apply'}},
                            'q': {'kind': 'exception', 'query': 'waiver', 'want': 1, 'max_bytes': 4000, 'evaluator': {'kind': 'phrase_present', 'pattern': 'waiver'}}}}
        response = client.ask('r', 'Refunds?', 'project', policy)
        assert response['result']['status'] == 'decided'
        bundle = client.get_run(response['run_id'])['bundle']
        assert verify_authored_export(bundle)['status'] == 'unanchored'
        altered = copy.deepcopy(bundle)
        altered['payload']['result']['skipped'][0]['witnesses'] = ['q']
        altered['sha256'] = hashlib.sha256(json.dumps(altered['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        assert verify_authored_export(altered)['status'] == 'invalid'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_authored_export_rechecks_deterministic_evaluator(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds are accepted within 14 days.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        client.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds days', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        response = client.ask('r', 'Refund?', 'project', policy)
        bundle = client.get_run(response['run_id'])['bundle']
        assert bundle['payload']['result']['outcome'] is False
        assert verify_authored_export(bundle)['evaluator_assurance'] == 'checked_conclusive_observations'
        legacy = copy.deepcopy(bundle)
        legacy['payload']['schema'] = 'qjig.authored-export.v1'
        for source_record in legacy['payload']['sources'].values():
            del source_record['metadata']
        legacy['sha256'] = hashlib.sha256(json.dumps(legacy['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        assert verify_authored_export(legacy)['evaluator_assurance'] == 'not_assessed'
        forged = copy.deepcopy(bundle)
        result = forged['payload']['result']
        result['outcome'] = True
        result['observations']['p']['outcome'] = 'true'
        result['records'][0]['observation']['outcome'] = 'true'
        forged['sha256'] = hashlib.sha256(json.dumps(forged['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        assert verify_authored_export(forged)['status'] == 'invalid'
        wrong_scope = copy.deepcopy(bundle)
        next(iter(wrong_scope['payload']['sources'].values()))['metadata'][1] = 'another-project'
        wrong_scope['sha256'] = hashlib.sha256(json.dumps(wrong_scope['payload'], sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        assert verify_authored_export(wrong_scope)['status'] == 'invalid'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_evaluator_timeout_is_incomplete_not_verified(tmp_path, monkeypatch):
    import subprocess
    import qjig.export as export_module
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'rule.md', 'text': '# Rule\nRefunds apply.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        client.import_source(source)
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Refunds?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds', 'want': 1, 'max_bytes': 4000, 'evaluator': {'kind': 'phrase_present', 'pattern': 'Refunds apply'}}}}
        response = client.ask('r', 'Refunds?', 'project', policy)
        bundle = client.get_run(response['run_id'])['bundle']
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired('evaluator', 3)
        monkeypatch.setattr(export_module.subprocess, 'run', timeout)
        report = verify_authored_export(bundle, expected_digest=bundle['sha256'])
        assert report['status'] == 'incomplete' and report['evaluator_assurance'] == 'incomplete'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
