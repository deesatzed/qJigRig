"""Synthetic local files only; no actual evaluation labels or provider calls."""
import hashlib
import os
import pytest
from qjig.contracts import ContractError


def test_allowlisted_evaluation_sources_exclude_reference_artifacts(tmp_path):
    from qjig.evaluation import load_isolated_sources
    (tmp_path / 'sources').mkdir()
    (tmp_path / 'private').mkdir()
    code = b'def check(x):\n    return x > 0\n'
    gold = b'{"fixture_label": "do-not-send"}'
    mapping = b'{"fixture_arm": "hidden-map"}'
    (tmp_path / 'sources' / 'code.py').write_bytes(code)
    (tmp_path / 'private' / 'labels.json').write_bytes(gold)
    (tmp_path / 'private' / 'arms.json').write_bytes(mapping)
    item = lambda path, data: {'path': path, 'sha256': hashlib.sha256(data).hexdigest()}
    sources = [item('sources/code.py', code)]
    protected = [item('private/labels.json', gold), item('private/arms.json', mapping)]
    loaded = load_isolated_sources(tmp_path, sources, protected)
    assert [(entry.path, entry.raw) for entry in loaded] == [('sources/code.py', code)]
    assert all(gold not in entry.raw and mapping not in entry.raw for entry in loaded)
    from qjig.indexing import index_entries
    from qjig.retrieval import bm25_candidates
    from qjig.sources import SourceRevision, decode_source
    entries = []
    for source in loaded:
        revision = SourceRevision.create(source.path, 'fixture', decode_source(source.raw, encoding='utf-8'))
        entries.extend(index_entries(revision))
    assert bm25_candidates(entries, 'do-not-send hidden-map') == []
    (tmp_path / 'sources' / 'code.py').write_bytes(code + b'# changed')
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, sources, protected)
    embedded = code + b'\n# ' + gold
    (tmp_path / 'sources' / 'code.py').write_bytes(embedded)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('sources/code.py', embedded)], protected)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('private/labels.json', gold)], protected)
    os.link(tmp_path / 'private' / 'labels.json', tmp_path / 'sources' / 'alias.json')
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('sources/alias.json', gold)], protected)
    (tmp_path / 'sources' / 'link').symlink_to(tmp_path / 'private', target_is_directory=True)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('sources/link/arms.json', mapping)], protected)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('../private/arms.json', mapping)], protected)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, [item('.', b'')], protected)
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, sources, [])
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, sources + sources, protected)
    (tmp_path / 'private' / 'labels.json').write_bytes(b'modified')
    with pytest.raises(ContractError):
        load_isolated_sources(tmp_path, sources, protected)


def _sample_design():
    categories = ['supported_yes', 'supported_no', 'genuine_unknown', 'wrong_entity',
                  'wrong_date', 'conflicting_versions', 'enabling_exception',
                  'restricting_exception', 'missing_decisive', 'changed_decisive',
                  'irrelevant_change']
    families = [{'id': f'{partition}{i}', 'partition': partition,
                 'source_hashes': [hashlib.sha256(f'{partition}{i}'.encode()).hexdigest()]}
                for partition in ('development', 'pilot', 'holdout') for i in range(2)]
    cases = [dict(id='dev', family='development0', categories=categories[:-3],
                  evidence_requirements=['identify decisive source'], parent=None),
             dict(id='dev-change', family='development0', categories=categories[-3:],
                  evidence_requirements=['inspect intervention'], parent='dev')]
    for partition in ('pilot', 'holdout'):
        cases.extend([dict(id=partition, family=partition+'0', categories=['supported_yes'],
                           evidence_requirements=['identify decisive source'], parent=None),
                      dict(id=partition+'-changed', family=partition+'0', categories=['changed_decisive'],
                           evidence_requirements=['inspect changed source'], parent=partition)])
    design = {'families': families, 'related_families': [['development0', 'development1']],
              'cases': cases,
              'arms': ['direct_full_evidence', 'direct_retrieval', 'retrieval_only',
                       'decomposition_only', 'combined'],
              'separate_results': ['authored_reuse', 'escalation'],
              'repeats': {'development': 1, 'pilot': 1, 'holdout': 2},
              'metrics': ['outcome_support', 'decisive_evidence_validity', 'source_coverage',
                          'resource_completeness', 'latency', 'calls', 'input_tokens',
                          'output_tokens', 'cost', 'variation'],
              'outcomes': ['timeout', 'malformed', 'unsupported', 'justified_deferral',
                           'unjustified_deferral', 'unknown_review'],
              'criteria': {key: {'metric': 'outcome_support', 'operator': op, 'threshold': value}
                           for key, op, value in [('retain', '>=', 0.8), ('revise', '>=', 0.5),
                                                  ('remove', '<', 0.5)]},
              'evaluation_provenance': 'synthetic fixture only'}
    return design


def test_evaluation_design_checks_splits_and_requirements():
    import copy
    from qjig.evaluation import validate_evaluation_design
    design = _sample_design()
    digest = validate_evaluation_design(design)
    assert len(digest) == 64
    assert validate_evaluation_design(design, expected_digest=digest) == digest
    invalid = []
    d = copy.deepcopy(design); d['families'][1]['partition'] = 'holdout'; invalid.append(d)
    d = copy.deepcopy(design); d['families'][2]['source_hashes'] = d['families'][0]['source_hashes']; invalid.append(d)
    d = copy.deepcopy(design); d['cases'][-1]['parent'] = 'pilot'; invalid.append(d)
    d = copy.deepcopy(design); d['cases'][0]['categories'].remove('wrong_date'); invalid.append(d)
    d = copy.deepcopy(design); d['repeats']['holdout'] = 1; invalid.append(d)
    d = copy.deepcopy(design); d['cases'][-1]['parent'] = 'missing'; invalid.append(d)
    d = copy.deepcopy(design); d['cases'][-2]['parent'] = d['cases'][-1]['id']; invalid.append(d)
    d = copy.deepcopy(design); d['arms'].remove('combined'); invalid.append(d)
    d = copy.deepcopy(design); d['criteria']['retain']['threshold'] = float('nan'); invalid.append(d)
    for item in invalid:
        with pytest.raises(ContractError):
            validate_evaluation_design(item)
    changed = copy.deepcopy(design); changed['evaluation_provenance'] = 'changed'
    with pytest.raises(ContractError):
        validate_evaluation_design(changed, expected_digest=digest)


def test_every_declared_assignment_and_unknown_resource_is_reported():
    from qjig.evaluation import summarize_evaluation_assignments, validate_evaluation_design
    design = _sample_design()
    digest = validate_evaluation_design(design)
    base = {'status': 'timeout', 'provenance': 'synthetic',
            'resources': {'calls': 1, 'input_tokens': 12, 'output_tokens': None, 'cost_usd': None, 'latency_ms': 10}}
    result = {**base, 'case_id': 'holdout', 'arm': 'combined', 'repeat': 1}
    summary = summarize_evaluation_assignments(design, [result], expected_digest=digest)
    assert summary['assigned'] == 40 and summary['recorded'] == 1 and len(summary['missing']) == 39
    assert summary['status_counts'] == {'timeout': 1}
    assert summary['assignments_complete'] is False and summary['resources_complete'] is False
    assert summary['resources']['calls'] is None and summary['resources']['known_calls'] == 1
    assert summary['resources']['cost_usd'] is None and summary['resources']['known_cost_usd'] == 0
    assert summary['resources']['unknown_cost_usd_records'] == 1
    with pytest.raises(ContractError):
        summarize_evaluation_assignments(design, [result, result], expected_digest=digest)
    with pytest.raises(ContractError):
        summarize_evaluation_assignments(design, [{**result, 'repeat': 3}], expected_digest=digest)
    with pytest.raises(ContractError):
        summarize_evaluation_assignments(design, [result], expected_digest='0'*64)
    with pytest.raises(ContractError):
        summarize_evaluation_assignments(design, [{**result, 'resources': {**base['resources'], 'cost_usd': float('nan')}}], expected_digest=digest)
    missing = summary['missing']
    filled = [result] + [{**base, **item, 'status': 'unknown_review',
                          'resources': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0, 'latency_ms': 0}}
                         for item in missing]
    complete = summarize_evaluation_assignments(design, filled, expected_digest=digest)
    assert complete['assignments_complete'] is True and complete['resources_complete'] is False
    assert complete['status_counts']['unknown_review'] == 39
    assert complete['resources']['cost_usd'] is None
    filled[0] = {**filled[0], 'resources': {'calls': 1, 'input_tokens': 12, 'output_tokens': 3, 'cost_usd': 0.2, 'latency_ms': 10}}
    complete = summarize_evaluation_assignments(design, filled, expected_digest=digest)
    assert complete['resources_complete'] is True and complete['resources']['cost_usd'] == 0.2
    assert complete['resources']['calls'] == 1 and complete['resources']['input_tokens'] == 12
    with pytest.raises(ContractError):
        summarize_evaluation_assignments(design, [{**result, 'status': 'invented'}], expected_digest=digest)
    import copy
    huge = copy.deepcopy(design); huge['repeats']['holdout'] = 1000000
    with pytest.raises(ContractError, match='exceeds limit'):
        summarize_evaluation_assignments(huge, [], expected_digest=validate_evaluation_design(huge))


def test_direct_retrieval_uses_isolated_sources_and_bounded_followup(tmp_path):
    from qjig.evaluation import DirectRetrieval
    from qjig.packets import serialize_packet
    (tmp_path / 'code').mkdir(); (tmp_path / 'private').mkdir()
    sources = {'code/rule.py': b'def validate(x):\n    return x > 0\n',
               'code/exception.py': b'def exception(x):\n    return x == -1\n'}
    secret = b'PRIVATE_REFERENCE_ANSWER'
    (tmp_path / 'private/labels').write_bytes(secret)
    for path, data in sources.items():
        (tmp_path / path).write_bytes(data)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item(path, raw) for path, raw in sources.items()],
                             [item('private/labels', secret)], want=1, max_bytes=3000, followups=1)
    first = search.search('validate')
    assert first['round'] == 1 and first['matches'] >= 1
    assert b'def validate' in serialize_packet(first['packet'])
    assert secret not in serialize_packet(first['packet'])
    second = search.search('exception')
    assert second['round'] == 2 and b'def exception' in serialize_packet(second['packet'])
    assert len(search.trace) == 2 and search.trace[0]['query'] == 'validate'
    with pytest.raises(ContractError):
        search.search('another followup')
    absent = DirectRetrieval(tmp_path, [item(path, raw) for path, raw in sources.items()],
                             [item('private/labels', secret)], want=1, max_bytes=3000, followups=0).search('nonexistentxyz')
    assert absent['matches'] == 0 and absent['packet'].items == ()
    assert absent['interpretation'] == 'no_hits_not_evidence_of_absence'
    top = DirectRetrieval(tmp_path, [item(path, raw) for path, raw in sources.items()],
                          [item('private/labels', secret)], want=1, max_bytes=3000, followups=0).search('def')
    assert top['matches'] == 2 and top['top_k_omitted'] == 1
    (tmp_path / 'code/rule.py').write_bytes(b'changed')
    with pytest.raises(ContractError):
        DirectRetrieval(tmp_path, [item(path, raw) for path, raw in sources.items()],
                        [item('private/labels', secret)], want=1, max_bytes=3000, followups=0)


def test_direct_agent_searches_and_answers_with_auditable_synthetic_calls(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code = b'# Base\nChecks pass.\n\n# Exception\nAn admin can bypass checks.\n'
    secret = b'PRIVATE_REFERENCE_ANSWER'
    (tmp_path / 'rule.md').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('rule.md', code)], [item('label', secret)],
                             want=2, max_bytes=3000, followups=1)
    request = Request('r', 'Can admin bypass checks?', 'reviewer', '1', 'project')
    probe = search.search('checks')
    ident = probe['packet'].items[0].entry_id
    # A new session ensures the tested pipeline performs both searches itself.
    search = DirectRetrieval(tmp_path, [item('rule.md', code)], [item('label', secret)],
                             want=2, max_bytes=3000, followups=1)
    usage = {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01}
    responses = [RawResponse(200, json.dumps({'action': 'search', 'query': 'admin', 'answer': None, 'citations': []}), usage),
                 RawResponse(200, json.dumps({'action': 'answer', 'query': None, 'answer': 'yes',
                                              'citations': [{'entry_id': ident, 'quote': 'Checks pass.'}]}), usage)]
    with Journal.open(tmp_path / 'journal.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        ledger = BudgetLedger(Budget(2, 10000, 1), journal, 'r')
        result = run_direct(search, request, ledger, StandInTransport(responses), archive=archive,
                            provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=['admin'])
        assert result['status'] == 'recorded_unvalidated' and result['answer'] == 'yes'
        assert len(result['searches']) == 2 and result['searches'][1]['query'] == 'admin'
        assert len(result['call_ids']) == 2 and [e.kind for e in journal.events('r')] == ['intent', 'receipt'] * 2
        requests = [e['data'] for e in archive.events() if e['kind'] == 'request']
        assert len([e for e in archive.events() if e['kind'] == 'trace']) == 2
        assert archive.events()[-1]['data'] == result and len(archive.revision_ids()) == 1
        assert len(requests) == 2 and all(secret.decode() not in e['prompt'] for e in requests)
        assert all('untrusted' in e['prompt'].lower() for e in requests)
        assert all('2026-11-07' in e['prompt'] and 'admin' in e['prompt'] for e in requests)
        from qjig.evaluation_replay import verify_direct_archive
        assert verify_direct_archive(archive, journal)['status'] == 'unanchored'


@pytest.mark.parametrize('mode', ['malformed', 'unsupported', 'timeout', 'budget'])
def test_direct_agent_preserves_failures_without_inventing_an_answer(tmp_path, mode):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Checks must pass.', b'PRIVATE_REFERENCE_ANSWER'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=1)
    body = 'not json' if mode == 'malformed' else json.dumps({'action': 'answer', 'query': None, 'answer': 'yes',
                                                               'citations': [{'entry_id': 'made-up', 'quote': 'Checks'}]})
    response = TimeoutError('synthetic timeout') if mode == 'timeout' else RawResponse(200, body, {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        ledger = BudgetLedger(Budget(0 if mode == 'budget' else 2, 10000, 1), journal, 'r')
        transport = StandInTransport([response])
        result = run_direct(search, Request('r', 'Checks?', 'reviewer', '1', 'project'), ledger, transport,
                            archive=archive, provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=['admin'])
        assert result['status'] == 'unavailable' and result['answer'] is None
        assert result['failure'] == {'malformed': 'malformed_output', 'unsupported': 'unsupported_citation',
                                     'timeout': 'UncertainOutcome', 'budget': 'BudgetExceeded'}[mode]
        assert len(result['call_ids']) == (0 if mode == 'budget' else 1)
        assert archive.events()[-1]['data'] == result
        assert bool(journal.pending('r')) == (mode == 'timeout')
        from qjig.evaluation_replay import verify_direct_archive
        assert verify_direct_archive(archive, journal)['status'] == 'incomplete'


def test_direct_replay_checks_search_and_source_tampering(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Checks must pass.', b'PRIVATE_REFERENCE_ANSWER'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=1)
    ident = search._entries[0].entry_id
    body = json.dumps({'action': 'answer', 'query': None, 'answer': 'yes',
                       'citations': [{'entry_id': ident, 'quote': 'Checks must pass.'}]})
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        ledger = BudgetLedger(Budget(2, 10000, 1), journal, 'r')
        run_direct(search, Request('r', 'Checks?', 'reviewer', '1', 'project'), ledger,
                   StandInTransport([RawResponse(200, body, {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})]),
                   archive=archive, provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=[])
        report = verify_direct_archive(archive, journal)
        assert report['status'] == 'unanchored' and report['semantic_assurance'] == 'not_assessed'
        assert verify_direct_archive(archive, journal, expected_digest=report['sha256'])['status'] == 'structurally_verified'
        original_trace = archive._con.execute("SELECT data FROM events WHERE kind='trace'").fetchone()[0]
        altered = json.loads(original_trace); altered['query'] = 'different'
        archive._con.execute('DROP TRIGGER event_no_update')
        archive._con.execute("UPDATE events SET data=? WHERE kind='trace'", (json.dumps(altered),))
        assert verify_direct_archive(archive, journal)['status'] == 'invalid'
        archive._con.execute("UPDATE events SET data=? WHERE kind='trace'", (original_trace,))
        original_receipt = journal._con.execute("SELECT payload FROM events WHERE kind='receipt'").fetchone()[0]
        changed_receipt = json.loads(original_receipt); changed_receipt['usage']['cost_usd'] = 0
        journal._con.execute('DROP TRIGGER events_no_update')
        journal._con.execute("UPDATE events SET payload=? WHERE kind='receipt'", (json.dumps(changed_receipt),))
        assert verify_direct_archive(archive, journal)['status'] == 'invalid'
        journal._con.execute("UPDATE events SET payload=? WHERE kind='receipt'", (original_receipt,))
        archive._con.execute('DROP TRIGGER revision_no_update')
        archive._con.execute("UPDATE revisions SET raw=?", (b'Checks can fail.',))
        assert verify_direct_archive(archive, journal, expected_digest=report['sha256'])['status'] == 'invalid'


def test_direct_provider_prompt_excludes_internal_assignment_identity(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Tests pass.', b'private labels'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=0)
    response = RawResponse(200, json.dumps({'action': 'answer', 'query': None, 'answer': 'unknown', 'citations': []}),
                           {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        request = Request('PRIVATE_ARM_MAPPING_COMBINED', 'Do tests pass?', 'reviewer', '1', 'project')
        run_direct(search, request, BudgetLedger(Budget(2, 10000, 1), journal, request.request_id),
                   StandInTransport([response]), archive=archive, provider='stand-in', model='test', max_tokens=100,
                   as_of='2026-11-07', entities=[])
        prompt = next(e['data']['prompt'] for e in archive.events() if e['kind'] == 'request')
        assert request.request_id not in prompt and 'request_id' not in prompt
        assert 'Do tests pass?' in prompt
        assert archive.context()['request']['request_id'] == request.request_id


def test_legacy_direct_prompt_archive_remains_replayable(tmp_path, monkeypatch):
    import json
    import qjig.evaluation_direct as direct
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Tests pass.', b'private labels'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=0)
    response = RawResponse(200, json.dumps({'action': 'answer', 'query': None, 'answer': 'unknown', 'citations': []}),
                           {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})
    original = direct._prompt
    monkeypatch.setattr(direct, '_prompt', lambda *args: original(*args, legacy_request_id=True))
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        request = Request('legacy-id', 'Do tests pass?', 'reviewer', '1', 'project')
        direct.run_direct(search, request, BudgetLedger(Budget(2, 10000, 1), journal, request.request_id),
                          StandInTransport([response]), archive=archive, provider='stand-in', model='test', max_tokens=100,
                          as_of='2026-11-07', entities=[])
        context = archive.context(); context['schema'] = 'qjig.direct-evaluation.v1'
        encoded = json.dumps(context, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        archive._con.execute('DROP TRIGGER context_no_update')
        archive._con.execute('UPDATE run_context SET data=?,sha256=? WHERE id=1', (encoded, hashlib.sha256(encoded.encode()).hexdigest()))
        assert verify_direct_archive(archive, journal)['status'] == 'unanchored'


def test_direct_score_binds_private_reference_and_required_source_quotes(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import reference_digest, score_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Tests must pass.', b'private labels'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=0)
    revision, ident = search._revisions[0].revision_id, search._entries[0].entry_id
    response = RawResponse(200, json.dumps({'action': 'answer', 'query': None, 'answer': 'yes',
                                           'citations': [{'entry_id': ident, 'quote': 'Tests must pass.'}]}),
                           {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        request = Request('run-1', 'Do tests pass?', 'reviewer', '1', 'project')
        run_direct(search, request, BudgetLedger(Budget(2, 10000, 1), journal, request.request_id),
                   StandInTransport([response]), archive=archive, provider='stand-in', model='test', max_tokens=100,
                   as_of='2026-11-07', entities=[])
        run_hash = verify_direct_archive(archive, journal)['sha256']
        ref = {'case_id': 'case-1', 'question': request.question, 'role': request.role, 'role_version': request.role_version,
               'scope': request.scope, 'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'source_revisions': [revision], 'expected_answer': 'yes', 'provenance': 'authored_unvalidated',
               'evidence': [{'revision_id': revision, 'quote': 'must pass'}]}
        digest = reference_digest(ref)
        scored = score_direct_archive(archive, journal, ref, expected_run_sha256=run_hash, expected_reference_sha256=digest)
        assert scored['classification'] == 'matches_reference' and scored['reference_provenance'] == 'authored_unvalidated'
        assert scored['required_evidence_covered'] is True and scored['semantic_assurance'] == 'not_assessed'
        changed = dict(ref, question='A different question?')
        with pytest.raises(ContractError):
            score_direct_archive(archive, journal, changed, expected_run_sha256=run_hash, expected_reference_sha256=reference_digest(changed))
        with pytest.raises(ContractError):
            score_direct_archive(archive, journal, ref, expected_run_sha256=run_hash, expected_reference_sha256='0'*64)
        ref2 = dict(ref, evidence=[{'revision_id': revision, 'quote': 'Tests'}])
        assert score_direct_archive(archive, journal, ref2, expected_run_sha256=run_hash,
                                    expected_reference_sha256=reference_digest(ref2))['required_evidence_covered'] is True
        ref3 = dict(ref, evidence=[{'revision_id': revision, 'quote': 'not in source'}])
        with pytest.raises(ContractError):
            score_direct_archive(archive, journal, ref3, expected_run_sha256=run_hash, expected_reference_sha256=reference_digest(ref3))


@pytest.mark.parametrize(('answer', 'expected', 'quote', 'classification'), [
    ('yes', 'no', 'Tests must pass.', 'differs_from_reference'),
    ('unknown', 'yes', 'Tests must pass.', 'unjustified_deferral'),
    ('unknown', 'unknown', 'Tests must pass.', 'justified_deferral'),
    ('yes', 'yes', 'Tests', 'unknown_review'),
])
def test_direct_score_reports_reference_mismatch_and_incomplete_evidence(tmp_path, answer, expected, quote, classification):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import reference_digest, score_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, secret = b'Tests must pass.', b'private labels'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=0)
    revision, ident = search._revisions[0].revision_id, search._entries[0].entry_id
    body = json.dumps({'action': 'answer', 'query': None, 'answer': answer,
                       'citations': [{'entry_id': ident, 'quote': quote}]})
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        request = Request('run-1', 'Do tests pass?', 'reviewer', '1', 'project')
        run_direct(search, request, BudgetLedger(Budget(2, 10000, 1), journal, request.request_id),
                   StandInTransport([RawResponse(200, body, {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01})]),
                   archive=archive, provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=[])
        ref = {'case_id': 'c', 'question': request.question, 'role': request.role, 'role_version': '1', 'scope': 'project',
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False, 'source_revisions': [revision],
               'expected_answer': expected, 'provenance': 'ai_reviewed_unvalidated',
               'evidence': [{'revision_id': revision, 'quote': 'must pass'}]}
        score = score_direct_archive(archive, journal, ref, expected_run_sha256=verify_direct_archive(archive, journal)['sha256'],
                                     expected_reference_sha256=reference_digest(ref))
        assert score['classification'] == classification
        assert score['reference_provenance'] == 'ai_reviewed_unvalidated'


def test_private_reference_binds_allowlisted_source_snapshots(tmp_path):
    from qjig.contracts import Request
    from qjig.evaluation import load_isolated_sources
    from qjig.evaluation_scoring import make_reference, reference_digest
    from qjig.sources import SourceRevision, decode_source
    code, gold = b'Tests must pass.', b'private label'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(gold)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    sources = load_isolated_sources(tmp_path, [item('code', code)], [item('label', gold)])
    request = Request('assignment-1', 'Do tests pass?', 'reviewer', '1', 'project')
    ref = make_reference(case_id='c', request=request, sources=sources, as_of='2026-11-07', entities=[],
                         historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                         evidence=[{'path': 'code', 'quote': 'must pass'}])
    revision = SourceRevision.create('code', 'evaluation_allowlist', decode_source(code, encoding='utf-8'))
    assert ref['source_revisions'] == [revision.revision_id]
    assert ref['evidence'] == [{'revision_id': revision.revision_id, 'quote': 'must pass'}]
    assert len(reference_digest(ref)) == 64 and 'assignment-1' not in repr(ref)
    with pytest.raises(ContractError):
        make_reference(case_id='c', request=request, sources=sources, as_of='2026-11-07', entities=[],
                       historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                       evidence=[{'path': 'code', 'quote': 'not in source'}])
    with pytest.raises(ContractError):
        make_reference(case_id='c', request=request, sources=sources, as_of='2026-11-07', entities=[],
                       historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                       evidence=[{'path': 'label', 'quote': 'private label'}])
    from qjig.evaluation import EvaluationSource
    forged = (EvaluationSource('code', b'other', sources[0].sha256),)
    with pytest.raises(ContractError):
        make_reference(case_id='c', request=request, sources=forged, as_of='2026-11-07', entities=[],
                       historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                       evidence=[{'path': 'code', 'quote': 'other'}])
