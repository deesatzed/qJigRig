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


def test_role_estimates_order_ties_without_cross_role_leakage(tmp_path):
    from qjig.indexing import index_entries
    from qjig.sources import SourceRevision, decode_source

    server = create_server(tmp_path / 'catalog.sqlite', host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        builder = RoleClient(port, RoleDefinition('builder', '1', 'Implement'))
        reviewer = RoleClient(port, RoleDefinition('reviewer', '2', 'Review'))
        base = {'text': '# Refunds\nRefunds are permitted.\n', 'scope': 'project', 'entities': [],
                'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        revisions, entries = [], []
        for source_id in ('a.md', 'b.md'):
            revisions.append(builder.import_source({**base, 'source_id': source_id})['revision_id'])
            rev = SourceRevision.create(source_id, f'api:{source_id}', decode_source(base['text'].encode(), encoding='utf-8'))
            entries.append(index_entries(rev)[0].entry_id)
        estimates = [
            {'role_id': 'builder', 'role_version': '1', 'entry_id': entries[0], 'revision_id': revisions[0], 'estimated_usefulness': 1.0, 'method': 'manual', 'receipt': 'builder proposal'},
            {'role_id': 'reviewer', 'role_version': '2', 'entry_id': entries[1], 'revision_id': revisions[1], 'estimated_usefulness': 1.0, 'method': 'manual', 'receipt': 'reviewer proposal'},
            {'role_id': 'reviewer', 'role_version': 'old', 'entry_id': entries[0], 'revision_id': revisions[0], 'estimated_usefulness': 1.0, 'method': 'manual', 'receipt': 'stale proposal'},
        ]
        policy = {'label': 'AUTHORED CONTROL', 'entities': [], 'as_of': '2026-11-15', 'mode': 'snapshot',
                  'role_estimates': estimates, 'plan': {'origin': 'authored', 'predicates': [{'id': 'p', 'question': 'Refunds?'}], 'expression': {'ref': 'p'}},
                  'needs': {'p': {'query': 'refunds', 'want': 1, 'max_bytes': 4000,
                                  'evaluator': {'kind': 'phrase_present', 'pattern': 'Refunds are permitted'}}}}
        a = builder.ask('b', 'Refunds?', 'project', policy)['result']
        b = reviewer.ask('r', 'Refunds?', 'project', policy)['result']
        assert a['records'][0]['evidence'][0]['revision_id'] == revisions[0]
        assert b['records'][0]['evidence'][0]['revision_id'] == revisions[1]
        assert a['role_prior_provenance']['applied'][0]['receipt'] == 'builder proposal'
        assert b['role_prior_provenance']['applied'][0]['receipt'] == 'reviewer proposal'
        assert any(x['reason'] == 'role_or_version_mismatch' for x in b['role_prior_provenance']['ignored'])
        assert a['obligations'][0]['material'] and b['obligations'][0]['material']
        import pytest
        from qjig.agents import ClientError
        invalid = [{**estimates[0], 'estimated_usefulness': 1.1}]
        with pytest.raises(ClientError):
            builder.ask('invalid', 'Refunds?', 'project', {**policy, 'role_estimates': invalid})
        stale = {**estimates[0], 'revision_id': 'rev1:' + '0' * 64}
        stale_result = builder.ask('stale', 'Refunds?', 'project', {**policy, 'role_estimates': [stale]})['result']
        assert stale_result['role_prior_provenance']['ignored'][0]['reason'] == 'entry_or_revision_not_live'
        waiver = {'source_id': 'waiver.md', 'text': '# Exceptions\nWaivers apply.\n', 'scope': 'project', 'entities': [],
                  'effective_from': '2026-01-01', 'effective_to': 'open', 'observed_at': None, 'authority': None}
        waiver_id = builder.import_source(waiver)['revision_id']
        waiver_rev = SourceRevision.create('waiver.md', 'api:waiver.md', decode_source(waiver['text'].encode(), encoding='utf-8'))
        low = {'role_id': 'builder', 'role_version': '1', 'entry_id': index_entries(waiver_rev)[0].entry_id,
               'revision_id': waiver_id, 'estimated_usefulness': 0.0, 'method': 'manual', 'receipt': 'low'}
        exception_policy = {**policy, 'role_estimates': [low],
            'plan': {'origin': 'authored', 'predicates': [{'id': 'ordinary', 'question': 'Ordinary?'}, {'id': 'exception', 'question': 'Exception?'}],
                     'expression': {'op': 'or', 'args': [{'ref': 'ordinary'}, {'ref': 'exception'}]}},
            'needs': {'ordinary': {'query': 'refunds', 'want': 1, 'max_bytes': 4000, 'evaluator': {'kind': 'phrase_present', 'pattern': 'not present'}},
                      'exception': {'kind': 'exception', 'query': 'waivers', 'want': 1, 'max_bytes': 4000, 'evaluator': {'kind': 'phrase_present', 'pattern': 'Waivers apply'}}}}
        checked = builder.ask('exception', 'Exception?', 'project', exception_policy)['result']
        assert checked['observations']['exception']['outcome'] == 'true'
        assert any(x['predicate_id'] == 'exception' and x['material'] for x in checked['obligations'])
        strong = {**base, 'source_id': 'strong.md', 'text': '# Refunds\nRefunds refunds refunds are permitted.\n'}
        strong_id = builder.import_source(strong)['revision_id']
        strong_rev = SourceRevision.create('strong.md', 'api:strong.md', decode_source(strong['text'].encode(), encoding='utf-8'))
        weak_priority = {**estimates[0], 'estimated_usefulness': 1.0}
        strong_priority = {'role_id': 'builder', 'role_version': '1', 'entry_id': index_entries(strong_rev)[0].entry_id,
                           'revision_id': strong_id, 'estimated_usefulness': 0.0, 'method': 'manual', 'receipt': 'low'}
        ordered = builder.ask('lexical', 'Refunds?', 'project', {**policy, 'role_estimates': [weak_priority, strong_priority]})['result']
        assert ordered['records'][0]['evidence'][0]['revision_id'] == strong_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
