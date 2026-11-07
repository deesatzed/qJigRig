"""Synthetic controlled changes through the actual local service."""
import threading
import pytest
from qjig.agents import ClientError, RoleClient
from qjig.roles import RoleDefinition
from qjig.service import create_server


def test_controlled_changes_preserve_parent_and_affect_authored_decision(tmp_path):
    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Refund limit\nRefunds are accepted within 14 days.\n# Note\nColor: blue.\n',
                  'scope': 'project', 'entities': [], 'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        parent = client.import_source(source)['revision_id']
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot', 'facts': {'days': 20},
                  'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Within limit?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refund days limit', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'numeric_threshold', 'field': 'days', 'pattern': r'within (\d+) days', 'operator': 'lte'}}}}
        before = client.ask('before', 'Refund after 20 days?', 'project', policy)['result']
        assert before['outcome'] is False
        detail = client.get_source(parent)
        start = detail['text'].index('blue')
        irrelevant = client.intervene(parent, detail['text_sha256'], start, start + 4, 'green')
        assert irrelevant['parent_revision_id'] == parent
        assert client.intervene(parent, detail['text_sha256'], start, start + 4, 'green') == irrelevant
        unchanged = client.ask('irrelevant', 'Refund after 20 days?', 'project', policy)['result']
        assert unchanged['outcome'] is False
        child = irrelevant['child_revision_id']
        current = client.get_source(child)
        start = current['text'].index('14')
        decisive = client.intervene(child, current['text_sha256'], start, start + 2, '30')
        assert decisive['parent_revision_id'] == child
        after = client.ask('after', 'Refund after 20 days?', 'project', policy)['result']
        assert after['outcome'] is True
        assert client.intervene(parent, detail['text_sha256'], detail['text'].index('blue'), detail['text'].index('blue') + 4, 'green') == irrelevant
        assert client.ask('after-retry', 'Refund after 20 days?', 'project', policy)['result']['outcome'] is True
        assert client.get_source(parent)['text'] == source['text']
        assert [x['intervention_id'] for x in client.list_interventions()] == sorted([irrelevant['intervention_id'], decisive['intervention_id']])
        with pytest.raises(ClientError):
            client.intervene(parent, detail['text_sha256'], 0, 1, 'X')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_intervention_link_failure_rolls_back_source_revision(tmp_path):
    import sqlite3
    from qjig.indexing import load_live_entries
    from qjig.store import Catalog

    path = tmp_path / 'catalog.sqlite'
    server = create_server(path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = RoleClient(server.server_address[1], RoleDefinition('reviewer', '1', 'Review'))
        source = {'source_id': 'policy.md', 'text': '# Rule\nLimit 14 days.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        parent = client.import_source(source)['revision_id']
        detail = client.get_source(parent)
        with sqlite3.connect(path) as con:
            con.execute("CREATE TRIGGER reject_link BEFORE INSERT ON interventions BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        start = source['text'].index('14')
        with pytest.raises(ClientError):
            client.intervene(parent, detail['text_sha256'], start, start + 2, '30')
        with Catalog.open(path) as catalog:
            assert catalog.revision_ids() == [parent]
            assert {entry.revision_id for entry in load_live_entries(catalog)} == {parent}
            assert catalog.intervention_rows() == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_concurrent_interventions_cannot_both_replace_same_parent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'catalog.sqlite'
    servers = [create_server(path, host='127.0.0.1', port=0) for _ in range(2)]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads:
        thread.start()
    try:
        clients = [RoleClient(s.server_address[1], RoleDefinition('reviewer', '1', 'Review')) for s in servers]
        source = {'source_id': 'policy.md', 'text': '# Rule\nLimit 14 days.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        parent = clients[0].import_source(source)['revision_id']
        detail = clients[0].get_source(parent)
        start = source['text'].index('14')
        def attempt(item):
            client, replacement = item
            try:
                return client.intervene(parent, detail['text_sha256'], start, start + 2, replacement)
            except ClientError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, zip(clients, ('21', '30'))))
        assert sum(x is not None for x in results) == 1
        assert len(clients[0].list_interventions()) == 1
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
