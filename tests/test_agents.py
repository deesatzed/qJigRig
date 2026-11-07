"""Two local clients against a real loopback service; all evidence is synthetic."""
import threading
from qjig.agents import RoleClient
from qjig.roles import RoleDefinition
from qjig.service import create_server


def test_two_role_clients_share_actual_local_service(tmp_path):
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        builder = RoleClient(port, RoleDefinition('builder', '1', 'Implement the policy'))
        reviewer = RoleClient(port, RoleDefinition('reviewer', '2', 'Review the policy'))
        source = {'source_id': 'policy.md', 'text': '# Refund limit\nRefunds are accepted within 14 days of purchase.\n',
                  'scope': 'project', 'entities': ['customer:42'], 'effective_from': '2026-01-01', 'effective_to': 'open',
                  'observed_at': '2026-01-02', 'authority': 'team:policy'}
        imported = builder.import_source(source)
        assert reviewer.list_sources()[0]['revision_id'] == imported['revision_id']
        assert reviewer.get_source(imported['revision_id'])['text'] == source['text']
        policy = {'label': 'AUTHORED CONTROL', 'entities': ['customer:42'], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'facts': {'refund_days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'within', 'question': 'Within refund limit?'}], 'expression': {'ref': 'within'}},
                  'needs': {'within': {'query': 'refund days limit', 'want': 1, 'max_bytes': 4000,
                                       'evaluator': {'kind': 'numeric_threshold', 'field': 'refund_days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        first = builder.ask('builder-1', 'Refund after 20 days?', 'project', policy)
        second = reviewer.ask('review-1', 'Refund after 20 days?', 'project', policy)
        assert first['result']['request']['role'] == 'builder' and second['result']['request']['role'] == 'reviewer'
        assert second['result']['request']['role_version'] == '2'
        assert first['result']['outcome'] is False and second['result']['outcome'] is False
        left = first['result']['records'][0]['evidence'][0]
        right = second['result']['records'][0]['evidence'][0]
        assert left['revision_id'] == right['revision_id'] == imported['revision_id']
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_client_rejects_invalid_inputs_and_service_errors(tmp_path):
    import pytest
    from qjig.agents import ClientError
    from qjig.contracts import ContractError

    with pytest.raises(ContractError):
        RoleClient(True, RoleDefinition('builder', '1', 'build'))
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'review'))
        with pytest.raises(ContractError):
            client.get_source('../../etc/passwd')
        with pytest.raises(ContractError):
            client.ask('', 'question', 'project', {})
        with pytest.raises(ClientError):
            client.get_source('rev1:' + 'a' * 64)
        with pytest.raises(ClientError):
            client.import_source({'source_id': '../escape'})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
