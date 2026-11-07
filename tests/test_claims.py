"""Synthetic source and two actual local clients; interpretations are not sources."""
import threading
import pytest
from qjig.agents import ClientError, RoleClient
from qjig.roles import RoleDefinition
from qjig.service import create_server


def test_clients_share_interpretation_without_turning_it_into_source(tmp_path):
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        builder = RoleClient(server.server_address[1], RoleDefinition('builder', '1', 'Implement'))
        reviewer = RoleClient(server.server_address[1], RoleDefinition('reviewer', '2', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nRefunds are accepted within 14 days.\n', 'scope': 'project',
                  'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        imported = builder.import_source(source)
        detail = builder.get_source(imported['revision_id'])
        start = source['text'].index('Refunds')
        end = start + len('Refunds are accepted within 14 days.')
        claim = builder.add_interpretation('The limit may exclude late requests.',
                                          {'revision_id': imported['revision_id'], 'text_sha256': detail['text_sha256'], 'start': start, 'end': end})
        assert claim['kind'] == 'agent_interpretation' and claim['role_id'] == 'builder'
        assert claim['evidence']['text'] == source['text'][start:end]
        assert reviewer.list_interpretations() == [claim]
        assert builder.add_interpretation('The limit may exclude late requests.',
                                          {'revision_id': imported['revision_id'], 'text_sha256': detail['text_sha256'], 'start': start, 'end': end})['claim_id'] == claim['claim_id']
        assert len(reviewer.list_sources()) == 1
        assert reviewer.get_source(imported['revision_id'])['text'] == source['text']
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Late requests?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'late requests', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'phrase_present', 'pattern': 'late requests'}}}}
        result = reviewer.ask('claim-is-not-source', 'Late requests?', 'project', policy)['result']
        assert result['status'] == 'deferred' and result['records'][0]['evidence'] == []
        with pytest.raises(ClientError):
            builder.add_interpretation('Bad span', {'revision_id': imported['revision_id'], 'text_sha256': detail['text_sha256'], 'start': -1, 'end': end})
        with pytest.raises(ClientError):
            builder.add_interpretation('Bad hash', {'revision_id': imported['revision_id'], 'text_sha256': '0'*64, 'start': start, 'end': end})
        assert reviewer.list_interpretations() == [claim]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    restarted = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=restarted.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(restarted.server_address[1], RoleDefinition('reviewer', '2', 'Review'))
        assert client.list_interpretations() == [claim]
        assert len(client.list_sources()) == 1
    finally:
        restarted.shutdown()
        restarted.server_close()
        thread.join(timeout=5)


def test_concurrent_identical_interpretations_do_not_duplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        clients = [RoleClient(server.server_address[1], RoleDefinition('builder', '1', 'Implement')) for _ in range(2)]
        source = {'source_id': 'rule.md', 'text': 'Evidence text.', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        revision_id = clients[0].import_source(source)['revision_id']
        detail = clients[0].get_source(revision_id)
        evidence = {'revision_id': revision_id, 'text_sha256': detail['text_sha256'], 'start': 0, 'end': len(source['text'])}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda client: client.add_interpretation('Proposed finding.', evidence), clients))
        assert results[0] == results[1] and clients[1].list_interpretations() == [results[0]]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
