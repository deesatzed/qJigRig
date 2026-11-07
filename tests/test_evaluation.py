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
    for partition in ('development', 'pilot', 'holdout'):
        cases.append(dict(id=partition+'-independent', family=partition+'1', categories=['supported_yes'],
                          evidence_requirements=['inspect independent source'], parent=None))
    design = {'families': families, 'related_families': [],
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
    assert summary['assigned'] == 60 and summary['recorded'] == 1 and len(summary['missing']) == 59
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
    assert complete['status_counts']['unknown_review'] == 59
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


@pytest.mark.parametrize('mode', ['malformed', 'unsupported', 'timeout', 'unavailable', 'budget'])
def test_direct_agent_preserves_failures_without_inventing_an_answer(tmp_path, mode):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import DirectRetrieval
    from qjig.evaluation_direct import run_direct
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport, ProviderUnavailable
    from qjig.run_archive import RunArchive
    code, secret = b'Checks must pass.', b'PRIVATE_REFERENCE_ANSWER'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=1)
    body = 'not json' if mode == 'malformed' else json.dumps({'action': 'answer', 'query': None, 'answer': 'yes',
                                                               'citations': [{'entry_id': 'made-up', 'quote': 'Checks'}]})
    response = (TimeoutError('synthetic timeout') if mode == 'timeout' else ProviderUnavailable('synthetic') if mode == 'unavailable'
                else RawResponse(200, body, {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01}))
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        ledger = BudgetLedger(Budget(0 if mode == 'budget' else 2, 10000, 1), journal, 'r')
        transport = StandInTransport([response])
        result = run_direct(search, Request('r', 'Checks?', 'reviewer', '1', 'project'), ledger, transport,
                            archive=archive, provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=['admin'])
        assert result['status'] == 'unavailable' and result['answer'] is None
        assert result['failure'] == {'malformed': 'malformed_output', 'unsupported': 'unsupported_citation',
                                     'timeout': 'UncertainOutcome', 'unavailable': 'ProviderUnavailable', 'budget': 'BudgetExceeded'}[mode]
        assert len(result['call_ids']) == (0 if mode == 'budget' else 1)
        assert archive.events()[-1]['data'] == result
        assert bool(journal.pending('r')) == (mode == 'timeout')
        from qjig.evaluation_replay import verify_direct_archive
        from qjig.evaluation_scoring import reference_digest, score_direct_archive
        report = verify_direct_archive(archive, journal)
        assert report['status'] == 'incomplete'
        ref = {'case_id': 'case-1', 'question': 'Checks?', 'role': 'reviewer', 'role_version': '1', 'scope': 'project',
               'as_of': '2026-11-07', 'entities': ['admin'], 'historical_as_known': False,
               'source_revisions': [archive.revision_ids()[0]], 'expected_answer': 'yes',
               'provenance': 'authored_unvalidated', 'evidence': [{'revision_id': archive.revision_ids()[0], 'quote': 'Checks'}]}
        score = score_direct_archive(archive, journal, ref, expected_run_sha256=report['sha256'],
                                     expected_reference_sha256=reference_digest(ref))
        assert score['classification'] == {'malformed': 'malformed', 'unsupported': 'unsupported',
                                           'timeout': 'uncertain_outcome', 'unavailable': 'provider_failure', 'budget': 'unknown_review'}[mode]
        assert score['answer_matches_reference'] is None and score['required_evidence_covered'] is None
        assert score['reconciliation_required'] is (mode == 'timeout')


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
        assert scored['recorded_answer'] == 'yes' and scored['reference_expected_answer'] == 'yes'
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


def test_failed_followup_remains_assigned_and_tampering_is_rejected(tmp_path):
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
    code, secret = b'Checks must pass.', b'private labels'
    (tmp_path / 'code').write_bytes(code); (tmp_path / 'label').write_bytes(secret)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    search = DirectRetrieval(tmp_path, [item('code', code)], [item('label', secret)], want=1, max_bytes=3000, followups=1)
    usage = {'prompt_tokens': 5, 'completion_tokens': 3, 'cost_usd': 0.01}
    first = RawResponse(200, json.dumps({'action': 'search', 'query': 'Checks', 'answer': None, 'citations': []}), usage)
    with Journal.open(tmp_path / 'j.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        request = Request('r', 'Checks?', 'reviewer', '1', 'project')
        result = run_direct(search, request, BudgetLedger(Budget(2, 10000, 1), journal, 'r'),
                            StandInTransport([first, RawResponse(200, 'not json', usage)]), archive=archive,
                            provider='stand-in', model='test', max_tokens=100, as_of='2026-11-07', entities=[])
        report = verify_direct_archive(archive, journal)
        assert report['status'] == 'incomplete' and report['failure_verified'] and report['classification'] == 'malformed'
        assert len(result['call_ids']) == 2 and len(result['searches']) == 2
        rev = archive.revision_ids()[0]
        ref = {'case_id':'c','question':'Checks?','role':'reviewer','role_version':'1','scope':'project',
               'as_of':'2026-11-07','entities':[],'historical_as_known':False,'source_revisions':[rev],
               'expected_answer':'yes','provenance':'authored_unvalidated','evidence':[{'revision_id':rev,'quote':'Checks'}]}
        assert score_direct_archive(archive, journal, ref, expected_run_sha256=report['sha256'],
                                    expected_reference_sha256=reference_digest(ref))['classification'] == 'malformed'
        original = archive._con.execute("SELECT data FROM events WHERE kind='run_result'").fetchone()[0]
        altered = json.loads(original); altered['failure'] = 'unsupported_citation'
        archive._con.execute('DROP TRIGGER event_no_update')
        archive._con.execute("UPDATE events SET data=? WHERE kind='run_result'", (json.dumps(altered),))
        assert verify_direct_archive(archive, journal)['status'] == 'invalid'


def test_paired_interventions_keep_missing_and_evidence_gaps_visible():
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_scoring import summarize_intervention_pairs
    design = _sample_design(); digest = validate_evaluation_design(design)
    def score(case, run, ref, actual, expected, evidence):
        return {'case_id': case, 'run_sha256': run*64, 'reference_sha256': ref*64,
                'reference_provenance': 'authored_unvalidated', 'recorded_answer': actual,
                'reference_expected_answer': expected, 'required_evidence_covered': evidence,
                'classification': 'matches_reference' if evidence else 'unknown_review',
                'answer_matches_reference': actual == expected, 'semantic_assurance': 'not_assessed'}
    records = [{'arm':'combined','repeat':1,'score':score('pilot','a','c','no','no',True)},
               {'arm':'combined','repeat':1,'score':score('pilot-changed','b','d','yes','yes',True)}]
    result = summarize_intervention_pairs(design, records, expected_design_sha256=digest)
    assert len(result['pairs']) == 20 and result['complete_pairs'] == 1
    selected = next(p for p in result['pairs'] if p['parent_case']=='pilot' and p['arm']=='combined')
    assert selected['comparison'] == 'matches_reference' and selected['observed_change'] is True
    assert selected['expected_change'] is True and selected['evidence_covered'] is True
    assert sum(p['comparison']=='unknown_review' for p in result['pairs']) == 19
    with pytest.raises(ContractError):
        summarize_intervention_pairs(design, records + [records[0]], expected_design_sha256=digest)
    reused = {**records[1], 'score': {**records[1]['score'], 'run_sha256': records[0]['score']['run_sha256']}}
    with pytest.raises(ContractError):
        summarize_intervention_pairs(design, [records[0], reused], expected_design_sha256=digest)
    inconsistent = {'arm': 'direct_retrieval', 'repeat': 1, 'score': {**records[0]['score'], 'run_sha256': 'f'*64, 'reference_sha256': 'e'*64}}
    with pytest.raises(ContractError):
        summarize_intervention_pairs(design, records + [inconsistent], expected_design_sha256=digest)
    changed = [records[0], {**records[1], 'score': {**records[1]['score'], 'required_evidence_covered': False}}]
    altered = summarize_intervention_pairs(design, changed, expected_design_sha256=digest)
    assert next(p for p in altered['pairs'] if p['parent_case']=='pilot' and p['arm']=='combined')['comparison'] == 'unknown_review'


def test_case_lock_binds_question_sources_and_private_reference(tmp_path):
    import copy
    from qjig.contracts import Request
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest, prepare_evaluation_case
    from qjig.evaluation_scoring import make_reference, reference_digest
    code, gold = b'Tests must pass.', b'private gold label'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    sources, protected = [item('code', code)], [item('label', gold)]
    design = _sample_design(); design['families'][0]['source_hashes'] = [sources[0]['sha256']]
    d = validate_evaluation_design(design)
    ref = make_reference(case_id='dev', request=Request('hidden-arm', 'Do tests pass?', 'reviewer', '1', 'project'),
                         sources=load_isolated_sources(tmp_path,sources,protected), as_of='2026-11-07', entities=[],
                         historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                         evidence=[{'path':'code','quote':'must pass'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,
            'question':'Do tests pass?','role':'reviewer','role_version':'1','scope':'project',
            'as_of':'2026-11-07','entities':[],'historical_as_known':False,'sources':sources,
            'reference_sha256':reference_digest(ref)}
    digest = case_lock_digest(lock)
    prepared = prepare_evaluation_case(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=digest)
    assert prepared.question == 'Do tests pass?' and [x.raw for x in prepared.sources] == [code]
    assert 'private gold label' not in repr(prepared) and 'expected_answer' not in repr(prepared)
    changed = copy.deepcopy(lock); changed['question'] = 'Different question?'
    with pytest.raises(ContractError):
        prepare_evaluation_case(tmp_path,design,changed,ref,protected,expected_design_sha256=d,expected_case_sha256=digest)
    other = b'A different family source.'
    (tmp_path/'other').write_bytes(other)
    foreign = copy.deepcopy(lock); foreign['sources'] = [item('other', other)]
    with pytest.raises(ContractError, match='family'):
        prepare_evaluation_case(tmp_path,design,foreign,ref,protected,expected_design_sha256=d,expected_case_sha256=case_lock_digest(foreign))
    bad_ref = dict(ref, expected_answer='no')
    with pytest.raises(ContractError):
        prepare_evaluation_case(tmp_path,design,lock,bad_ref,protected,expected_design_sha256=d,expected_case_sha256=digest)
    (tmp_path/'code').write_bytes(b'changed')
    with pytest.raises(ContractError):
        prepare_evaluation_case(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=digest)


def test_locked_direct_run_binds_case_without_exposing_reference(tmp_path):
    import copy
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_direct import run_locked_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import make_reference, reference_digest, score_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    code, gold = b'Tests must pass.', b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda path, raw: {'path': path, 'sha256': hashlib.sha256(raw).hexdigest()}
    sources, protected = [item('code', code)], [item('label', gold)]
    design = _sample_design(); design['families'][0]['source_hashes'] = [sources[0]['sha256']]
    design_hash = validate_evaluation_design(design)
    ref = make_reference(case_id='dev', request=Request('hidden', 'Do tests pass?', 'reviewer', '1', 'project'),
                         sources=load_isolated_sources(tmp_path,sources,protected), as_of='2026-11-07', entities=[],
                         historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
                         evidence=[{'path':'code','quote':'must pass'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':design_hash,
            'question':'Do tests pass?','role':'reviewer','role_version':'1','scope':'project',
            'as_of':'2026-11-07','entities':[],'historical_as_known':False,'sources':sources,
            'reference_sha256':reference_digest(ref)}
    lock_hash = case_lock_digest(lock)
    response = RawResponse(200, json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}),
                           {'prompt_tokens':5,'completion_tokens':3,'cost_usd':0.01})
    with Journal.open(tmp_path/'j.sqlite') as journal, RunArchive.open(tmp_path/'archive') as archive:
        ledger = BudgetLedger(Budget(2,10000,1),journal,'PRIVATE_ARM_ID')
        altered = copy.deepcopy(lock); altered['question'] = 'Different question?'
        with pytest.raises(ContractError):
            run_locked_direct(tmp_path,design,altered,ref,protected,expected_design_sha256=design_hash,
                              expected_case_sha256=lock_hash,ledger=ledger,transport=StandInTransport([response]),
                              archive=archive,provider='stand-in',model='test',max_tokens=100,want=1,max_bytes=3000,followups=0)
        assert journal.events('PRIVATE_ARM_ID') == [] and archive.events() == []
        result = run_locked_direct(tmp_path,design,lock,ref,protected,expected_design_sha256=design_hash,
                                   expected_case_sha256=lock_hash,ledger=ledger,transport=StandInTransport([response]),
                                   archive=archive,provider='stand-in',model='test',max_tokens=100,want=1,max_bytes=3000,followups=0)
        assert result['answer'] == 'unknown'
        binding = archive.context()['case_binding']
        assert binding == {'case_id':'dev','design_sha256':design_hash,'case_sha256':lock_hash,'reference_sha256':reference_digest(ref)}
        prompt = next(e['data']['prompt'] for e in archive.events() if e['kind']=='request')
        assert 'PRIVATE_ARM_ID' not in prompt and reference_digest(ref) not in prompt and gold.decode() not in prompt
        replay = verify_direct_archive(archive,journal); assert replay['status']=='unanchored'
        score = score_direct_archive(archive,journal,ref,expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
        assert score['classification']=='unknown_review'
        swapped = dict(ref, case_id='another-case')
        with pytest.raises(ContractError, match='case binding'):
            score_direct_archive(archive,journal,swapped,expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(swapped))


@pytest.mark.parametrize(('reference_quote', 'comparison', 'covered'), [('Tests must pass.', 'matches_reference', True), ('# Checks', 'unknown_review', False)])
def test_locked_fresh_run_uses_only_checked_sources_and_hides_reference(tmp_path, reference_quote, comparison, covered):
    import json
    from qjig.applicability import ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_fresh import run_locked_fresh
    from qjig.evaluation_scoring import make_reference, reference_digest
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.replay import verify_archive
    from qjig.run_archive import RunArchive
    code, gold = b'# Checks\nTests must pass.', b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda path, raw: {'path':path,'sha256':hashlib.sha256(raw).hexdigest()}
    sources, protected = [item('code',code)], [item('label',gold)]
    design = _sample_design(); design['families'][0]['source_hashes'] = [sources[0]['sha256']]
    d = validate_evaluation_design(design)
    ref = make_reference(case_id='dev',request=Request('hidden','Do tests pass?','reviewer','1','project'),
                         sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],
                         historical_as_known=False,expected_answer='yes',provenance='authored_unvalidated',
                         evidence=[{'path':'code','quote':reference_quote}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,'question':'Do tests pass?',
            'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
            'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    lock_hash = case_lock_digest(lock); rev = ref['source_revisions'][0]
    inputs = ApplicabilityInputs(Collection((MemberMetadata(rev,'project',Interval('2020-01-01',OPEN)),)),
                                 frozenset(),'2026-11-07',False)
    usage = {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}
    def raw(data): return RawResponse(200,json.dumps(data),usage)
    responses = [raw({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                 raw({'supported':True,'quote':'Tests must pass.','reason':'synthetic'}),
                 raw({'supported':False,'quote':'','reason':'synthetic'}),
                 raw({'assessment':'uncertain','reason':'synthetic'})]
    with Journal.open(tmp_path/'j.sqlite') as journal, RunArchive.open(tmp_path/'archive') as archive:
        ledger = BudgetLedger(Budget(8,50000,1),journal,'PRIVATE_ARM_MAPPING')
        bad_inputs = ApplicabilityInputs(Collection(()),frozenset(),'2026-11-07',False)
        with pytest.raises(ContractError):
            run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=lock_hash,
                             applicability_inputs=bad_inputs,ledger=ledger,transport=StandInTransport(responses),archive=archive,
                             planner=('stand-in','planner'),judge=('stand-in','judge'),reviewer=('stand-in','reviewer'))
        assert journal.events('PRIVATE_ARM_MAPPING') == [] and archive.events() == []
        from qjig.goal_budget import GoalBudget
        with GoalBudget.open(tmp_path/'fresh-goal.sqlite', total=Budget(8,50000,1), per_request=Budget(8,50000,1),
                             allocations={'development':Budget(8,50000,1)}) as goal:
            guarded = BudgetLedger(Budget(8,50000,1),journal,'PRIVATE_ARM_MAPPING',goal_budget=goal,partition='development')
            guarded_transport = StandInTransport(responses)
            with pytest.raises(ContractError):
                run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=lock_hash,
                                 applicability_inputs=inputs,ledger=guarded,transport=guarded_transport,archive=archive,
                                 planner=('stand-in','planner'),judge=('stand-in','judge'))
            assert guarded_transport.calls_made == 0 and journal.events('PRIVATE_ARM_MAPPING') == [] and archive.events() == []
        transport = StandInTransport(responses)
        result = run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=lock_hash,
                                  applicability_inputs=inputs,ledger=ledger,transport=transport,archive=archive,
                                  planner=('stand-in','planner'),judge=('stand-in','judge'),reviewer=('stand-in','reviewer'))
        assert result.status=='deferred' and 'plan_coverage_unestablished' in result.reasons
        assert result.review.status=='recorded' and transport.calls_made==4
        assert archive.revision_ids()==(rev,)
        assert archive.context()['evaluation_case_binding']['case_sha256']==lock_hash
        prompts = [e['data']['prompt'] for e in archive.events() if e['kind']=='request']
        assert all('PRIVATE_ARM_MAPPING' not in p and gold.decode() not in p and reference_digest(ref) not in p for p in prompts)
        replay = verify_archive(archive)
        assert replay.status=='unanchored'
        from qjig.evaluation_scoring import score_fresh_archive
        score = score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        assert score['request_status']=='deferred' and score['request_answer'] is None
        assert score['conditional_answer']=='yes' and score['conditional_comparison']==comparison
        assert score['reference_expected_answer']=='yes' and score['request_answer'] is None
        assert score['required_evidence_covered'] is covered and score['semantic_assurance']=='not_assessed'
        recorded = journal._con.execute("SELECT payload FROM events WHERE kind='receipt' LIMIT 1").fetchone()[0]
        corrupted = json.loads(recorded); corrupted['usage']['cost_usd'] = 0
        journal._con.execute('DROP TRIGGER events_no_update')
        journal._con.execute("UPDATE events SET payload=? WHERE kind='receipt' AND request_seq=2", (json.dumps(corrupted),))
        with pytest.raises(ContractError, match='journal'):
            score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))


@pytest.mark.parametrize(('mode','expected'), [('malformed','malformed'),('http_error','provider_failure'),('unavailable','provider_failure'),
                                              ('timeout','uncertain_outcome'),('budget','unknown_review'),('judge_malformed','malformed'),('judge_http','provider_failure'),
                                              ('judge_unavailable','provider_failure'),('judge_timeout','uncertain_outcome'),
                                              ('review_malformed','malformed'),('review_http','provider_failure'),
                                              ('review_unavailable','provider_failure'),('review_timeout','uncertain_outcome'),
                                              ('judge_mixed','provider_failure')])
def test_fresh_planner_failure_scoring_retains_uncertainty(tmp_path, mode, expected):
    import json
    from qjig.applicability import ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_fresh import run_locked_fresh
    from qjig.evaluation_scoring import make_reference, reference_digest, score_fresh_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport, ProviderUnavailable
    from qjig.replay import verify_archive
    from qjig.run_archive import RunArchive
    code, gold = b'Tests must pass.', b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda p, raw: {'path':p,'sha256':hashlib.sha256(raw).hexdigest()}
    sources, protected = [item('code',code)], [item('label',gold)]
    design = _sample_design(); design['families'][0]['source_hashes'] = [sources[0]['sha256']]
    d = validate_evaluation_design(design)
    ref = make_reference(case_id='dev',request=Request('hidden','Do tests pass?','reviewer','1','project'),
                         sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],
                         historical_as_known=False,expected_answer='yes',provenance='authored_unvalidated',
                         evidence=[{'path':'code','quote':'Tests must pass.'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,'question':'Do tests pass?',
            'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
            'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    inputs = ApplicabilityInputs(Collection((MemberMetadata(ref['source_revisions'][0],'project',Interval('2020-01-01',OPEN)),)),
                                 frozenset(),'2026-11-07',False)
    response = {'malformed':RawResponse(200,'not json',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'http_error':RawResponse(502,'upstream error',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'unavailable':ProviderUnavailable('synthetic'), 'timeout':TimeoutError('synthetic'), 'budget':None,
                'judge_malformed':RawResponse(200,'not json',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'judge_mixed':RawResponse(200,'not json',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'judge_http':RawResponse(502,'unavailable',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'judge_unavailable':ProviderUnavailable('synthetic'), 'judge_timeout':TimeoutError('synthetic'),
                'review_malformed':RawResponse(200,'not json',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'review_http':RawResponse(502,'unavailable',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                'review_unavailable':ProviderUnavailable('synthetic'), 'review_timeout':TimeoutError('synthetic')}[mode]
    responses = ([RawResponse(200,json.dumps({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                              {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}), response,
                  RawResponse(200,json.dumps({'supported':False,'quote':'','reason':'synthetic'}),
                              {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01})] if mode.startswith('judge_') else [response])
    if mode == 'judge_mixed':
        responses[2] = RawResponse(502,'unavailable',{'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01})
    if mode.startswith('review_'):
        responses = [RawResponse(200,json.dumps({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                                 {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                     RawResponse(200,json.dumps({'supported':True,'quote':'Tests must pass.','reason':'synthetic'}),
                                 {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}),
                     RawResponse(200,json.dumps({'supported':False,'quote':'','reason':'synthetic'}),
                                 {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}), response]
    with Journal.open(tmp_path/'j.sqlite') as journal, RunArchive.open(tmp_path/'archive') as archive:
        result = run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=d,expected_case_sha256=case_lock_digest(lock),
                                  applicability_inputs=inputs,ledger=BudgetLedger(Budget(0 if mode=='budget' else 8,50000,1),journal,'r'),
                                  transport=StandInTransport(responses),archive=archive,planner=('stand-in','planner'),judge=('stand-in','judge'),
                                  reviewer=('stand-in','reviewer') if mode.startswith('review_') else None)
        replay=verify_archive(archive); assert replay.status=='incomplete'
        score=score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        assert score['classification']==expected and score['request_status']=='deferred' and score['request_answer'] is None
        assert score['conditional_answer'] is None and score['required_evidence_covered'] is None
        assert score['reconciliation_required'] is (mode in ('timeout','judge_timeout','review_timeout'))
        assert score['failure_verified'] is (mode!='budget')
        if mode == 'judge_mixed':
            assert [f['classification'] for f in score['failures']] == ['malformed','provider_failure']
        if mode in ('timeout','judge_timeout','review_timeout'):
            journal.reconcile(journal.pending('r')[0].call_id, resolution='not_executed', detail='synthetic verification')
            with pytest.raises(ContractError, match='reconciliation'):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        if mode in ('malformed', 'judge_malformed', 'judge_http'):
            saved = journal._con.execute("SELECT payload FROM events WHERE kind='receipt'").fetchone()[0]
            tampered = json.loads(saved); tampered['usage']['cost_usd']=0
            journal._con.execute('DROP TRIGGER events_no_update')
            journal._con.execute("UPDATE events SET payload=? WHERE kind='receipt'",(json.dumps(tampered),))
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))


def test_fresh_paired_report_keeps_request_deferrals_separate_from_conditional_graphs():
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_scoring import summarize_fresh_intervention_pairs
    design = _sample_design(); digest = validate_evaluation_design(design)
    def score(case, run, ref, answer, expected):
        return {'case_id':case,'run_sha256':run*64,'reference_sha256':ref*64,
                'reference_provenance':'authored_unvalidated','request_status':'deferred','request_answer':None,
                'conditional_answer':answer,'reference_expected_answer':expected,
                'required_evidence_covered':True,'semantic_assurance':'not_assessed'}
    records = [{'arm':'combined','repeat':1,'score':score('pilot','a','c','no','no')},
               {'arm':'combined','repeat':1,'score':score('pilot-changed','b','d','yes','yes')}]
    report = summarize_fresh_intervention_pairs(design,records,expected_design_sha256=digest)
    pair = next(p for p in report['pairs'] if p['parent_case']=='pilot' and p['arm']=='combined')
    assert report['comparison_scope']=='conditional_graph_only' and report['complete_pairs']==1
    assert pair['comparison']=='matches_reference' and pair['observed_change'] is True
    assert pair['parent_request_status']=='deferred' and pair['intervention_request_status']=='deferred'
    assert pair['parent_request_answer'] is None and pair['intervention_request_answer'] is None
    wrong = [records[0], {**records[1], 'score':{**records[1]['score'],'conditional_answer':'no'}}]
    wrong_pair = next(p for p in summarize_fresh_intervention_pairs(design,wrong,expected_design_sha256=digest)['pairs']
                      if p['parent_case']=='pilot' and p['arm']=='combined')
    assert wrong_pair['comparison']=='differs_from_reference' and wrong_pair['intervention_request_answer'] is None
    incomplete = [records[0], {**records[1], 'score':{**records[1]['score'],'conditional_answer':None,'required_evidence_covered':None}}]
    incomplete_pair = next(p for p in summarize_fresh_intervention_pairs(design,incomplete,expected_design_sha256=digest)['pairs']
                           if p['parent_case']=='pilot' and p['arm']=='combined')
    assert incomplete_pair['comparison']=='unknown_review' and incomplete_pair['intervention_request_status']=='deferred'
    missing_status = dict(records[1]['score']); del missing_status['request_answer']
    with pytest.raises(ContractError):
        summarize_fresh_intervention_pairs(design,[records[0], {**records[1], 'score':missing_status}],expected_design_sha256=digest)
    fabricated = [records[0], {**records[1], 'score':{**records[1]['score'],'request_answer':'yes'}}]
    with pytest.raises(ContractError):
        summarize_fresh_intervention_pairs(design,fabricated,expected_design_sha256=digest)


def test_full_evidence_baseline_sends_every_source_or_refuses(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_direct import run_locked_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import make_reference, reference_digest, score_direct_archive
    from qjig.indexing import make_entry_id
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.run_archive import RunArchive
    a,b,gold=b'Tests must pass.\n',b'An unrelated second file.\n',b'PRIVATE_REFERENCE_LABEL'
    for p,v in [('a',a),('b',b),('label',gold)]: (tmp_path/p).write_bytes(v)
    item=lambda p,v:{'path':p,'sha256':hashlib.sha256(v).hexdigest()}
    sources,protected=[item('a',a),item('b',b)],[item('label',gold)]
    design=_sample_design();design['families'][0]['source_hashes']=[x['sha256'] for x in sources];d=validate_evaluation_design(design)
    ref=make_reference(case_id='dev',request=Request('hidden','Are tests required?','reviewer','1','project'),
                       sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
                       expected_answer='yes',provenance='authored_unvalidated',evidence=[{'path':'a','quote':'Tests must pass.'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,'question':'Are tests required?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
          'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    from qjig.sources import SourceRevision,decode_source
    rev=SourceRevision.create('a','evaluation_allowlist',decode_source(a,encoding='utf-8'))
    eid=make_entry_id(rev.revision_id,'full_source','full_source_v1',0,len(rev.decoded.text))
    response=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'yes',
                                         'citations':[{'entry_id':eid,'quote':'Tests must pass.'}]}),
                         {'prompt_tokens':8,'completion_tokens':3,'cost_usd':0.01})
    with Journal.open(tmp_path/'j.sqlite') as journal,RunArchive.open(tmp_path/'archive') as archive:
        ledger=BudgetLedger(Budget(2,10000,1),journal,'opaque')
        options=dict(expected_design_sha256=d,expected_case_sha256=case_lock_digest(lock),ledger=ledger,
                     archive=archive,provider='stand-in',model='test',max_tokens=100,want=1,followups=0,evidence_mode='full')
        transport=StandInTransport([response])
        with pytest.raises(ContractError):
            run_locked_direct(tmp_path,design,lock,ref,protected,transport=transport,max_bytes=100,**options)
        assert transport.calls_made==0 and journal.events('opaque')==[] and archive.events()==[]
        with pytest.raises(ContractError):
            run_locked_direct(tmp_path,design,lock,ref,protected,transport=transport,max_bytes=3000,
                              **{**options,'followups':1})
        assert transport.calls_made==0 and journal.events('opaque')==[]
        result=run_locked_direct(tmp_path,design,lock,ref,protected,transport=transport,max_bytes=3000,**options)
        assert result['status']=='recorded_unvalidated' and result['searches'][0]['method']=='full_source_v1'
        prompt=next(e['data']['prompt'] for e in archive.events() if e['kind']=='request')
        payload=json.loads(prompt[prompt.index('{\"applicability\"'):])
        texts=[item['text'] for packet in payload['packets'] for item in packet['items']]
        assert a.decode() in texts and b.decode() in texts and gold.decode() not in prompt
        report=verify_direct_archive(archive,journal);assert report['status']=='unanchored'
        score=score_direct_archive(archive,journal,ref,expected_run_sha256=report['sha256'],expected_reference_sha256=reference_digest(ref))
        assert score['classification']=='matches_reference'
        event=next(e for e in archive.events() if e['kind']=='trace')
        altered=event['data']; altered['packet']['items'][0]['text']='tampered'
        archive._con.execute('DROP TRIGGER event_no_update')
        archive._con.execute("UPDATE events SET data=? WHERE seq=?",(json.dumps(altered),event['seq']))
        assert verify_direct_archive(archive,journal)['status']=='invalid'


def test_design_requires_two_case_bearing_unrelated_families_per_partition():
    import copy
    from qjig.evaluation import validate_evaluation_design
    design=_sample_design()
    # Merely declaring a second family, including one declared related, is insufficient.
    unused=copy.deepcopy(design)
    unused['cases']=[case for case in unused['cases'] if not case['family'].endswith('1')]
    unused['related_families']=[['development0','development1']]
    with pytest.raises(ContractError):
        validate_evaluation_design(unused)
    validate_evaluation_design(design)
    related=copy.deepcopy(design); related['related_families']=[['pilot0','pilot1']]
    with pytest.raises(ContractError):
        validate_evaluation_design(related)
    duplicate=copy.deepcopy(design); duplicate['families'][3]['source_hashes']=duplicate['families'][2]['source_hashes']
    with pytest.raises(ContractError):
        validate_evaluation_design(duplicate)
    transitive=copy.deepcopy(design)
    transitive['families'].append({'id':'pilot2','partition':'pilot','source_hashes':[hashlib.sha256(b'pilot2').hexdigest()]})
    transitive['related_families']=[['pilot0','pilot2'],['pilot2','pilot1']]
    with pytest.raises(ContractError):
        validate_evaluation_design(transitive)


def test_complete_evaluation_reservation_is_atomic_and_restart_safe(tmp_path):
    from qjig.contracts import Budget
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_budget import make_evaluation_plan, reserve_evaluation_plan
    from qjig.goal_budget import GoalBudget
    design=_sample_design(); digest=validate_evaluation_design(design)
    families={f['id']:f['partition'] for f in design['families']}
    cases={c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']}
    templates={arm:{'synthetic_call':1} for arm in design['arms']}
    assignments=[]
    for case in design['cases']:
        partition=families[case['family']]
        for arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                rid='opaque-'+str(len(assignments)); work={'work_id':'work-'+rid,'request_id':rid,'partition':partition,
                    'tokens':10,'cost_usd':0.001,'stage':'synthetic_call','provider':'stand-in','model':'fixture',
                    'work_binding_sha256':'a'*64}
                assignments.append({'case_id':case['id'],'arm':arm,'repeat':repeat,'request_id':rid,'work':[work]})
    with pytest.raises(ContractError):
        make_evaluation_plan(design,cases,templates,assignments[:-1],expected_design_sha256=digest)
    broken = list(assignments); broken[0] = {**broken[0], 'work': []}
    with pytest.raises(ContractError):
        make_evaluation_plan(design,cases,templates,broken,expected_design_sha256=digest)
    plan=make_evaluation_plan(design,cases,templates,assignments,expected_design_sha256=digest)
    assert len(plan['manifest']['assignments'])==60
    total=Budget(60,600,1); per=Budget(1,10,0.1)
    allocations={'development':Budget(15,150,0.2),'pilot':Budget(15,150,0.2),'holdout':Budget(30,300,0.2)}
    from qjig.budgets import BudgetExceeded
    short_total=Budget(59,590,1)
    short_alloc={'development':Budget(15,150,0.2),'pilot':Budget(15,150,0.2),'holdout':Budget(29,290,0.2)}
    with GoalBudget.open(tmp_path/'short.sqlite',total=short_total,per_request=per,allocations=short_alloc) as goal:
        with pytest.raises(BudgetExceeded):
            reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])
        assert goal._con.execute('SELECT COUNT(*) FROM run_sets').fetchone()[0]==0
        assert goal._con.execute('SELECT COUNT(*) FROM evaluation_plans').fetchone()[0]==0
        assert goal._con.execute('SELECT COUNT(*) FROM required_work').fetchone()[0]==0
    path=tmp_path/'goal.sqlite'
    with GoalBudget.open(path,total=total,per_request=per,allocations=allocations) as goal:
        receipt=reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])
        assert receipt['assignments']==60 and receipt['work_items']==60
    with GoalBudget.open(path,total=total,per_request=per,allocations=allocations) as goal:
        assert reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])==receipt
        changed=dict(plan,sha256='0'*64)
        with pytest.raises(ContractError):
            reserve_evaluation_plan(goal,'study',changed,expected_plan_sha256=plan['sha256'])
        altered_cases=dict(cases); altered_cases[next(iter(cases))]='f'*64
        replaced=make_evaluation_plan(design,altered_cases,templates,assignments,expected_design_sha256=digest)
        with pytest.raises(ContractError):
            reserve_evaluation_plan(goal,'study',replaced,expected_plan_sha256=replaced['sha256'])
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            goal._con.execute("UPDATE evaluation_plans SET manifest='{}' WHERE plan_id='study'")
        goal._con.execute('DROP TRIGGER evaluation_plans_no_update')
        goal._con.execute("UPDATE evaluation_plans SET manifest='{}' WHERE plan_id='study'")
        first=assignments[0]['work'][0]
        with pytest.raises(ContractError, match='evaluation plan digest'):
            goal.select_required_work('evaluation:study',request_id=first['request_id'],partition=first['partition'],
                                      stage=first['stage'],provider=first['provider'],model=first['model'],
                                      tokens=first['tokens'],cost_usd=first['cost_usd'])


def test_goal_budgeted_case_requires_matching_reserved_assignment(tmp_path):
    import json
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.direct_preflight import direct_run_allocations,direct_slot_reservation
    from qjig.evaluation import load_isolated_sources,validate_evaluation_design
    from qjig.evaluation_budget import make_evaluation_plan,reserve_evaluation_plan
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_direct import run_locked_direct
    from qjig.evaluation_scoring import make_reference,reference_digest
    from qjig.goal_budget import GoalBudget
    from qjig.journal import Journal
    from qjig.providers import RawResponse,StandInTransport
    from qjig.run_archive import RunArchive
    code,gold=b'Tests must pass.',b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(code);(tmp_path/'label').write_bytes(gold)
    item=lambda p,v:{'path':p,'sha256':hashlib.sha256(v).hexdigest()}
    sources,protected=[item('code',code)],[item('label',gold)]
    design=_sample_design();design['families'][0]['source_hashes']=[sources[0]['sha256']];d=validate_evaluation_design(design)
    ref=make_reference(case_id='dev',request=Request('hidden','Do tests pass?','reviewer','1','project'),
                       sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
                       expected_answer='yes',provenance='authored_unvalidated',evidence=[{'path':'code','quote':'must pass'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,'question':'Do tests pass?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
          'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    case_hashes={c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']};case_hashes['dev']=case_lock_digest(lock)
    templates={arm:{'direct_initial':1} for arm in design['arms']}
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3};families={f['id']:f['partition'] for f in design['families']};assignments=[]
    for case in design['cases']:
        partition=families[case['family']]
        for arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                rid='opaque-'+str(len(assignments));work=direct_run_allocations(request_id=rid,partition=partition,provider='stand-in',model=model,
                         input_tokens=100,output_tokens=100,max_price=cap,followups=0)
                assignments.append({'case_id':case['id'],'arm':arm,'repeat':repeat,'request_id':rid,'work':work})
    plan=make_evaluation_plan(design,case_hashes,templates,assignments,expected_design_sha256=d)
    target=next(x for x in assignments if x['case_id']=='dev' and x['arm']=='direct_full_evidence');rid=target['request_id']
    total=Budget(60,12000,1);per=Budget(1,200,0.1);alloc={'development':Budget(15,3000,0.2),'pilot':Budget(15,3000,0.2),'holdout':Budget(30,6000,0.2)}
    response=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}),{'prompt_tokens':10,'completion_tokens':3,'cost_usd':0.0001})
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=alloc) as goal,Journal.open(tmp_path/'j.sqlite') as journal,RunArchive.open(tmp_path/'archive') as archive:
        reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])
        ledger=BudgetLedger(per,journal,rid,goal_budget=goal,partition='development');transport=StandInTransport([response])
        def factory(req):return direct_slot_reservation(goal,'evaluation:study',request_id=rid,partition='development',request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
        options=dict(expected_design_sha256=d,expected_case_sha256=case_lock_digest(lock),ledger=ledger,transport=transport,
                     archive=archive,provider='stand-in',model=model['id'],max_tokens=100,want=1,max_bytes=3000,
                     followups=0,evidence_mode='full',max_price=cap,reservation_factory=factory)
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,**options)
        assert transport.calls_made==0 and journal.events(rid)==[] and archive.events()==[]
        binding={'plan_id':'study','plan_sha256':plan['sha256'],'arm':'direct_full_evidence','repeat':1}
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding={**binding,'arm':'combined'},**options)
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding={**binding,'plan_sha256':'0'*64},**options)
        assert transport.calls_made==0 and journal.events(rid)==[]
        result=run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding=binding,**options)
        assert result['status']=='recorded_unvalidated' and transport.calls_made==1
        assert archive.context()['evaluation_assignment']==binding
        from qjig.evaluation_replay import verify_direct_archive
        replay = verify_direct_archive(archive,journal)
        from qjig.evaluation_scoring import score_reserved_assignment
        scored = score_reserved_assignment(goal,archive,journal,ref,partition='development',
            expected_plan_sha256=plan['sha256'],expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
        assert scored['arm']=='direct_full_evidence' and scored['repeat']==1 and scored['score']['case_id']=='dev'
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='development',expected_plan_sha256='0'*64,
                expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
        prompt=next(e['data']['prompt'] for e in archive.events() if e['kind']=='request')
        assert plan['sha256'] not in prompt and rid not in prompt and 'direct_full_evidence' not in prompt


def test_reserved_combined_assignment_runs_and_replays_without_leaking_mapping(tmp_path):
    import json
    from collections import Counter
    from qjig.applicability import ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget, Request
    from qjig.direct_preflight import direct_run_allocations
    from qjig.evaluation import load_isolated_sources, validate_evaluation_design
    from qjig.evaluation_budget import make_evaluation_plan, reserve_evaluation_plan
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_fresh import run_locked_fresh
    from qjig.evaluation_scoring import make_reference, reference_digest, score_fresh_archive
    from qjig.fresh_preflight import fresh_run_allocations, fresh_slot_reservation
    from qjig.goal_budget import GoalBudget
    from qjig.journal import Journal
    from qjig.providers import RawResponse, StandInTransport
    from qjig.replay import verify_archive
    from qjig.run_archive import RunArchive

    code, gold = b'Tests must pass.', b'PRIVATE_REFERENCE_LABEL'
    (tmp_path/'code').write_bytes(code); (tmp_path/'label').write_bytes(gold)
    item = lambda p, v: {'path':p, 'sha256':hashlib.sha256(v).hexdigest()}
    sources, protected = [item('code',code)], [item('label',gold)]
    design = _sample_design(); design['families'][0]['source_hashes'] = [sources[0]['sha256']]
    digest = validate_evaluation_design(design)
    ref = make_reference(case_id='dev', request=Request('hidden','Do tests pass?','reviewer','1','project'),
        sources=load_isolated_sources(tmp_path,sources,protected), as_of='2026-11-07', entities=[],
        historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
        evidence=[{'path':'code','quote':'Tests must pass.'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':digest,'question':'Do tests pass?',
        'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
        'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    case_hashes = {c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']}
    case_hashes['dev'] = case_lock_digest(lock)
    model = {'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
             'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap = {'prompt':2,'completion':3}
    family_partitions = {f['id']:f['partition'] for f in design['families']}
    assignments, templates = [], {}
    for case in design['cases']:
        partition = family_partitions[case['family']]
        for arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                rid = 'private-'+str(len(assignments))
                if arm == 'combined':
                    work = fresh_run_allocations(request_id=rid,partition=partition,provider='stand-in',
                        planner_model=model,judge_model=model,planner_input=100,planner_output=100,
                        judge_input=100,judge_output=100,planner_price=cap,judge_price=cap)
                else:
                    work = direct_run_allocations(request_id=rid,partition=partition,provider='stand-in',model=model,
                        input_tokens=100,output_tokens=100,max_price=cap,followups=0)
                templates[arm] = dict(Counter(x['stage'] for x in work))
                assignments.append({'case_id':case['id'],'arm':arm,'repeat':repeat,'request_id':rid,'work':work})
    plan = make_evaluation_plan(design,case_hashes,templates,assignments,expected_design_sha256=digest)
    target = next(a for a in assignments if a['case_id']=='dev' and a['arm']=='combined' and a['repeat']==1)
    rid = target['request_id']; per = Budget(30,6000,1)
    allocations = {p:Budget(500,150000,6) for p in ('development','pilot','holdout')}
    total = Budget(1500,450000,18)
    inputs = ApplicabilityInputs(Collection((MemberMetadata(ref['source_revisions'][0],'project',Interval('2020-01-01',OPEN)),)),
                                 frozenset(),'2026-11-07',False)
    usage = {'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw = lambda data: RawResponse(200,json.dumps(data),usage)
    responses = [raw({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                 raw({'supported':True,'quote':'Tests must pass.','reason':'synthetic'}),
                 raw({'supported':False,'quote':'','reason':'synthetic'})]
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=allocations) as goal, \
         Journal.open(tmp_path/'journal.sqlite') as journal, RunArchive.open(tmp_path/'archive') as archive:
        reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])
        ledger = BudgetLedger(per,journal,rid,goal_budget=goal,partition='development')
        def factory(req):
            return fresh_slot_reservation(goal,'evaluation:study',request_id=rid,partition='development',
                request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
        binding = {'plan_id':'study','plan_sha256':plan['sha256'],'arm':'combined','repeat':1}
        transport = StandInTransport(responses)
        result = run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
            expected_case_sha256=case_lock_digest(lock),applicability_inputs=inputs,ledger=ledger,
            transport=transport,archive=archive,planner=('stand-in',model['id']),judge=('stand-in',model['id']),
            planner_max_tokens=100,judge_max_tokens=100,planner_max_price=cap,judge_max_price=cap,
            reservation_factory=factory,assignment_binding=binding)
        assert result.status == 'deferred' and transport.calls_made == 3
        assert archive.context()['evaluation_assignment'] == binding
        prompts = [e['data']['prompt'] for e in archive.events() if e['kind']=='request']
        assert all(rid not in p and plan['sha256'] not in p and gold.decode() not in p for p in prompts)
        replay = verify_archive(archive)
        assert replay.status == 'unanchored'
        score = score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                                    expected_reference_sha256=reference_digest(ref))
        assert score['request_status'] == 'deferred' and score['request_answer'] is None
        from qjig.evaluation_scoring import score_reserved_assignment
        record = score_reserved_assignment(goal,archive,journal,ref,partition='development',
            expected_plan_sha256=plan['sha256'],expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        assert record['arm']=='combined' and record['repeat']==1 and record['score']==score
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='pilot',expected_plan_sha256=plan['sha256'],
                expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        assert goal.audit_journal(journal)['status'] == 'verified'
        # Even if the context and replay are rehashed, another assignment cannot be relabeled.
        changed = archive.context(); changed['evaluation_assignment']['repeat'] = 2
        encoded = json.dumps(changed,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        archive._con.execute('DROP TRIGGER context_no_update')
        archive._con.execute('UPDATE run_context SET data=?,sha256=? WHERE id=1',
                             (encoded,hashlib.sha256(encoded.encode()).hexdigest()))
        tampered = verify_archive(archive)
        assert tampered.status == 'unanchored'
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='development',expected_plan_sha256=plan['sha256'],
                expected_run_sha256=tampered.digest,expected_reference_sha256=reference_digest(ref))
