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
