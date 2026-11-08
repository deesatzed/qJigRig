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
        from qjig.evaluation_scoring import fresh_journal_digest
        from qjig.evaluation_semantic_review import review_fresh_semantics
        journal_hash=fresh_journal_digest(journal,ledger._request_id)
        with RunArchive.open(tmp_path/'semantic-review') as semantic_archive:
            with pytest.raises(ContractError):
                review_fresh_semantics(archive,journal,ledger,StandInTransport([]),reference=ref,
                    expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                    expected_journal_sha256='0'*64,review_archive=semantic_archive,
                    provider='stand-in',model='reviewer',max_tokens=100)
            assert not semantic_archive.events()
            semantic=review_fresh_semantics(archive,journal,ledger,StandInTransport([raw({'assessment':'supported','reason':'source supports conditional graph'})]),
                    reference=ref,expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                    expected_journal_sha256=journal_hash,review_archive=semantic_archive,
                    provider='stand-in',model='reviewer',max_tokens=100)
            assert semantic['request_status']=='deferred' and semantic['request_answer'] is None
            assert semantic['conditional_answer']=='yes' and semantic['assurance']=='synthetic_unvalidated'
            review_prompt=next(e['data']['prompt'] for e in semantic_archive.events() if e['kind']=='request')
            assert gold.decode() not in review_prompt and ledger._request_id not in review_prompt
            assert 'conditional_answer' in review_prompt and 'deferred' in review_prompt
            from qjig.evaluation_semantic_review import verify_fresh_semantic_review
            checked=verify_fresh_semantic_review(archive,journal,semantic_archive,reference=ref,
                expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                expected_journal_sha256=journal_hash)
            assert checked['status']=='unanchored' and checked['assessment']=='supported'
            assert verify_fresh_semantic_review(archive,journal,semantic_archive,reference=ref,
                expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                expected_journal_sha256=journal_hash,expected_review_sha256=checked['sha256'])['status']=='structurally_verified'
            assert verify_fresh_semantic_review(archive,journal,semantic_archive,reference=ref,
                expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                expected_journal_sha256=journal_hash,expected_review_sha256='0'*64)['status']=='invalid'
            replayed_score=score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash,original_run_only=True)
            assert replayed_score['journal_scope']=='original_run_prefix'
            assert replayed_score['request_status']=='deferred' and replayed_score['conditional_answer']=='yes'
            assert ledger.used_calls()==5
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),original_run_only=True)
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash)
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256='0'*64,original_run_only=True)
            semantic_archive._con.execute('DROP TRIGGER event_no_update')
            seq,encoded=semantic_archive._con.execute("SELECT seq,data FROM events WHERE kind='review_record'").fetchone()
            changed=json.loads(encoded); changed['conditional_answer']='no'
            semantic_archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),seq))
            assert verify_fresh_semantic_review(archive,journal,semantic_archive,reference=ref,
                expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,
                expected_journal_sha256=journal_hash)['status']=='invalid'
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
                                              ('judge_mixed','provider_failure'),('review_empty_packet','unknown_review')])
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
    question = 'Unmatched zyzzword?' if mode=='review_empty_packet' else 'Do tests pass?'
    ref = make_reference(case_id='dev',request=Request('hidden',question,'reviewer','1','project'),
                         sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],
                         historical_as_known=False,expected_answer='yes',provenance='authored_unvalidated',
                         evidence=[{'path':'code','quote':'Tests must pass.'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':d,'question':question,
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
                'review_unavailable':ProviderUnavailable('synthetic'), 'review_timeout':TimeoutError('synthetic'),
                'review_empty_packet':None}[mode]
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
        assert score['failure_verified'] is (mode not in ('budget','review_empty_packet'))
        if mode=='review_empty_packet':
            assert result.review.status=='unavailable' and result.review.failure=='review_context_or_storage_error'
            assert score['review_status']=='unavailable' and score['review_failure']=='review_context_or_storage_error'
        if mode == 'judge_mixed':
            assert [f['classification'] for f in score['failures']] == ['malformed','provider_failure']
        if mode in ('timeout','judge_timeout','review_timeout'):
            resolution = 'not_executed' if mode == 'judge_timeout' else 'executed'
            journal.reconcile(journal.pending('r')[0].call_id, resolution=resolution, detail='synthetic verification')
            with pytest.raises(ContractError, match='reconciliation'):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
            from qjig.evaluation_scoring import fresh_journal_digest
            anchor = fresh_journal_digest(journal,'r')
            recovered = score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                expected_reference_sha256=reference_digest(ref),expected_journal_sha256=anchor)
            assert recovered['classification']=='uncertain_outcome' and recovered['reconciliation_required'] is False
            assert recovered['reconciliations'][0]['resolution']==resolution
            assert recovered['request_answer'] is None and recovered['conditional_answer'] is None
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256='0'*64)
            journal._con.execute('DROP TRIGGER events_no_update')
            journal._con.execute("UPDATE events SET payload=? WHERE kind='reconciled'",
                                 (json.dumps({'resolution':'executed','detail':'altered'}),))
            with pytest.raises(ContractError):
                score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256=anchor)
        if mode in ('malformed', 'judge_malformed', 'judge_http', 'review_empty_packet'):
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


@pytest.mark.parametrize(('mode','arm'), [('full','direct_full_evidence'),('catalog','retrieval_only')])
def test_goal_budgeted_case_requires_matching_reserved_assignment(tmp_path,mode,arm):
    import json
    from qjig.applicability import ApplicabilityInputs,Collection,Interval,MemberMetadata,OPEN
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
    design=_sample_design();design['families'][4]['source_hashes']=[sources[0]['sha256']];d=validate_evaluation_design(design)
    ref=make_reference(case_id='holdout',request=Request('hidden','Do tests pass?','reviewer','1','project'),
                       sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
                       expected_answer='yes',provenance='authored_unvalidated',evidence=[{'path':'code','quote':'must pass'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'holdout','design_sha256':d,'question':'Do tests pass?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
          'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    case_hashes={c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']};case_hashes['holdout']=case_lock_digest(lock)
    templates={arm:{'direct_initial':1,'semantic_review':1} for arm in design['arms']}
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3};spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':cap}
    from qjig.semantic_preflight import semantic_review_allocation,semantic_review_reservation
    families={f['id']:f['partition'] for f in design['families']};assignments=[]
    for case in design['cases']:
        partition=families[case['family']]
        for assigned_arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                rid='opaque-'+str(len(assignments));work=direct_run_allocations(request_id=rid,partition=partition,provider='stand-in',model=model,
                         input_tokens=100,output_tokens=100,max_price=cap,followups=0)
                work.append(semantic_review_allocation(request_id=rid,partition=partition,spec=spec))
                assignments.append({'case_id':case['id'],'arm':assigned_arm,'repeat':repeat,'request_id':rid,'work':work})
    plan=make_evaluation_plan(design,case_hashes,templates,assignments,expected_design_sha256=d)
    inputs=ApplicabilityInputs(Collection(tuple(MemberMetadata(rev,'project',Interval('2020-01-01',OPEN))
                                               for rev in ref['source_revisions'])),frozenset(),'2026-11-07',False)
    target=next(x for x in assignments if x['case_id']=='holdout' and x['arm']==arm);rid=target['request_id']
    total=Budget(120,24000,1);per=Budget(2,400,0.1);alloc={'development':Budget(30,6000,0.2),'pilot':Budget(30,6000,0.2),'holdout':Budget(60,12000,0.2)}
    response=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}),{'prompt_tokens':10,'completion_tokens':3,'cost_usd':0.0001})
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=alloc) as goal,Journal.open(tmp_path/'j.sqlite') as journal,RunArchive.open(tmp_path/'archive') as archive:
        reserve_evaluation_plan(goal,'study',plan,expected_plan_sha256=plan['sha256'])
        ledger=BudgetLedger(per,journal,rid,goal_budget=goal,partition='holdout');transport=StandInTransport([response])
        def factory(req):return direct_slot_reservation(goal,'evaluation:study',request_id=rid,partition='holdout',request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
        options=dict(expected_design_sha256=d,expected_case_sha256=case_lock_digest(lock),ledger=ledger,transport=transport,
                     archive=archive,provider='stand-in',model=model['id'],max_tokens=100,want=1,max_bytes=3000,
                     followups=0,evidence_mode=mode,applicability_inputs=inputs,max_price=cap,reservation_factory=factory)
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,**options)
        assert transport.calls_made==0 and journal.events(rid)==[] and archive.events()==[]
        binding={'plan_id':'study','plan_sha256':plan['sha256'],'arm':arm,'repeat':1}
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding={**binding,'arm':'combined'},**options)
        with pytest.raises(ContractError):run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding={**binding,'plan_sha256':'0'*64},**options)
        assert transport.calls_made==0 and journal.events(rid)==[]
        result=run_locked_direct(tmp_path,design,lock,ref,protected,assignment_binding=binding,**options)
        assert result['status']=='recorded_unvalidated' and transport.calls_made==1
        assert archive.context()['evaluation_assignment']==binding
        from qjig.evaluation_replay import verify_direct_archive
        replay = verify_direct_archive(archive,journal)
        from qjig.evaluation_scoring import score_reserved_assignment
        scored = score_reserved_assignment(goal,archive,journal,ref,partition='holdout',
            expected_plan_sha256=plan['sha256'],expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
        assert scored['arm']==arm and scored['repeat']==1 and scored['score']['case_id']=='holdout'
        assert scored['score']['resources']['total']['calls']==1
        assert scored['score']['resources']['total']['input_tokens']==10
        from qjig.evaluation_scoring import build_reserved_holdout_comparison
        entry={'archive':archive,'journal':journal,'reference':ref,'run_sha256':replay['sha256'],
               'reference_sha256':reference_digest(ref),'journal_sha256':None}
        report=build_reserved_holdout_comparison(goal,design,[entry],plan_id='study',expected_plan_sha256=plan['sha256'],
            expected_design_sha256=d,baseline_arm=arm,candidate_arm='combined')
        assert report['assigned_pairs']==6 and report['recorded_pairs']==0 and report['missing_pairs']==6
        assert any(p['case_id']=='holdout' and p['repeat']==1 and p['baseline_status']=='unknown' for p in report['pairs'])
        assert report['scored_assignments'][0]['score']['resources']['total']['calls']==1
        with pytest.raises(ContractError):
            build_reserved_holdout_comparison(goal,design,[entry,entry],plan_id='study',expected_plan_sha256=plan['sha256'],
                expected_design_sha256=d,baseline_arm=arm,candidate_arm='combined')
        with pytest.raises(ContractError):
            build_reserved_holdout_comparison(goal,design,[{**entry,'reference_sha256':'0'*64}],plan_id='study',
                expected_plan_sha256=plan['sha256'],expected_design_sha256=d,baseline_arm=arm,candidate_arm='combined')
        with pytest.raises(ContractError):
            build_reserved_holdout_comparison(goal,design,[entry],plan_id='study',expected_plan_sha256='0'*64,
                expected_design_sha256=d,baseline_arm=arm,candidate_arm='combined')
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='holdout',expected_plan_sha256='0'*64,
                expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
        from qjig.evaluation_semantic_review import review_direct_semantics
        opinion=RawResponse(200,json.dumps({'assessment':'uncertain','reason':'synthetic'}),
                            {'prompt_tokens':10,'completion_tokens':3,'cost_usd':0.0001})
        with RunArchive.open(tmp_path/'review') as review_archive:
            def review_factory(req):
                return semantic_review_reservation(goal,'evaluation:study',request_id=rid,partition='holdout',request=req,spec=spec)
            review_direct_semantics(archive,journal,ledger,StandInTransport([opinion]),review_archive=review_archive,
                expected_run_sha256=replay['sha256'],provider='stand-in',model=model['id'],max_tokens=100,
                max_price=cap,reservation_factory=review_factory)
            with pytest.raises(ContractError):
                score_reserved_assignment(goal,archive,journal,ref,partition='holdout',expected_plan_sha256=plan['sha256'],
                    expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref))
            reviewed=score_reserved_assignment(goal,archive,journal,ref,partition='holdout',expected_plan_sha256=plan['sha256'],
                expected_run_sha256=replay['sha256'],expected_reference_sha256=reference_digest(ref),original_run_only=True)
            assert reviewed['score']['journal_scope']=='original_run_prefix'
            assert reviewed['score']['resources']['total']['calls']==2
            from qjig.evaluation_semantic_review import verify_direct_semantic_review
            from qjig.evaluation_scoring import score_reviewed_reserved_assignment
            review_hash=verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=replay['sha256'])['sha256']
            kwargs=dict(partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=replay['sha256'],
                        expected_reference_sha256=reference_digest(ref),expected_review_sha256=review_hash,reviewer_spec=spec)
            bound=score_reviewed_reserved_assignment(goal,archive,journal,ref,review_archive,**kwargs)
            assert bound['review']['assessment']=='uncertain' and bound['review']['assurance']=='synthetic_unvalidated'
            assert bound['review']['sha256']==review_hash and bound['score']['resources']['total']['calls']==2
            for changed in ({'expected_review_sha256':'0'*64}, {'reviewer_spec':{**spec,'output_tokens':99}}):
                with pytest.raises(ContractError):
                    score_reviewed_reserved_assignment(goal,archive,journal,ref,review_archive,**{**kwargs,**changed})
        prompt=next(e['data']['prompt'] for e in archive.events() if e['kind']=='request')
        assert plan['sha256'] not in prompt and rid not in prompt and arm not in prompt


@pytest.mark.parametrize(('mode','target_arm'), [('catalog','combined'),('full','decomposition_only')])
def test_reserved_combined_assignment_runs_and_replays_without_leaking_mapping(tmp_path,mode,target_arm):
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
    design = _sample_design(); design['families'][4]['source_hashes'] = [sources[0]['sha256']]
    digest = validate_evaluation_design(design)
    ref = make_reference(case_id='holdout', request=Request('hidden','Do tests pass?','reviewer','1','project'),
        sources=load_isolated_sources(tmp_path,sources,protected), as_of='2026-11-07', entities=[],
        historical_as_known=False, expected_answer='yes', provenance='authored_unvalidated',
        evidence=[{'path':'code','quote':'Tests must pass.'}])
    lock = {'schema':'qjig.evaluation-case.v1','case_id':'holdout','design_sha256':digest,'question':'Do tests pass?',
        'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
        'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    case_hashes = {c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']}
    case_hashes['holdout'] = case_lock_digest(lock)
    model = {'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
             'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap = {'prompt':2,'completion':3}
    spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':cap}
    from qjig.semantic_preflight import semantic_review_allocation,semantic_review_reservation
    family_partitions = {f['id']:f['partition'] for f in design['families']}
    assignments, templates = [], {}
    for case in design['cases']:
        partition = family_partitions[case['family']]
        for arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                rid = 'private-'+str(len(assignments))
                if arm in ('combined','decomposition_only'):
                    work = fresh_run_allocations(request_id=rid,partition=partition,provider='stand-in',
                        planner_model=model,judge_model=model,planner_input=100,planner_output=100,
                        judge_input=100,judge_output=100,planner_price=cap,judge_price=cap)
                else:
                    work = direct_run_allocations(request_id=rid,partition=partition,provider='stand-in',model=model,
                        input_tokens=100,output_tokens=100,max_price=cap,followups=0)
                work.append(semantic_review_allocation(request_id=rid,partition=partition,spec=spec))
                templates[arm] = dict(Counter(x['stage'] for x in work))
                assignments.append({'case_id':case['id'],'arm':arm,'repeat':repeat,'request_id':rid,'work':work})
    plan = make_evaluation_plan(design,case_hashes,templates,assignments,expected_design_sha256=digest)
    target = next(a for a in assignments if a['case_id']=='holdout' and a['arm']==target_arm and a['repeat']==1)
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
        ledger = BudgetLedger(per,journal,rid,goal_budget=goal,partition='holdout')
        def factory(req):
            return fresh_slot_reservation(goal,'evaluation:study',request_id=rid,partition='holdout',
                request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
        binding = {'plan_id':'study','plan_sha256':plan['sha256'],'arm':target_arm,'repeat':1}
        transport = StandInTransport(responses)
        with pytest.raises(ContractError):
            run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
                expected_case_sha256=case_lock_digest(lock),applicability_inputs=inputs,ledger=ledger,
                transport=transport,archive=archive,planner=('stand-in',model['id']),judge=('stand-in',model['id']),
                assignment_binding=binding,evidence_mode='full' if mode=='catalog' else 'catalog')
        assert transport.calls_made==0 and journal.events(rid)==[] and archive.events()==[]
        result = run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
            expected_case_sha256=case_lock_digest(lock),applicability_inputs=inputs,ledger=ledger,
            transport=transport,archive=archive,planner=('stand-in',model['id']),judge=('stand-in',model['id']),
            planner_max_tokens=100,judge_max_tokens=100,planner_max_price=cap,judge_max_price=cap,
            reservation_factory=factory,assignment_binding=binding,evidence_mode=mode)
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
        from qjig.evaluation_scoring import fresh_journal_digest
        journal_anchor = fresh_journal_digest(journal,rid)
        for invalid_anchor in (None,'0'*64):
            with pytest.raises(ContractError):
                score_reserved_assignment(goal,archive,journal,ref,partition='holdout',
                    expected_plan_sha256=plan['sha256'],expected_run_sha256=replay.digest,
                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256=invalid_anchor)
        record = score_reserved_assignment(goal,archive,journal,ref,partition='holdout',
            expected_plan_sha256=plan['sha256'],expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref),
            expected_journal_sha256=journal_anchor)
        assert record['arm']==target_arm and record['repeat']==1
        assert {k:v for k,v in record['score'].items() if k != 'resources'} == score
        resource = record['score']['resources']['total']
        assert resource['calls']==3 and resource['input_tokens']==30 and resource['output_tokens']==15
        assert resource['cost_usd']==pytest.approx(0.0003) and resource['latency_seconds'] is not None
        from qjig.evaluation_scoring import build_reserved_holdout_comparison
        entry={'archive':archive,'journal':journal,'reference':ref,'run_sha256':replay.digest,
               'reference_sha256':reference_digest(ref),'journal_sha256':journal_anchor}
        report=build_reserved_holdout_comparison(goal,design,[entry],plan_id='study',expected_plan_sha256=plan['sha256'],
            expected_design_sha256=digest,baseline_arm='direct_full_evidence',candidate_arm=target_arm)
        assert report['candidate_unknown']==1 and report['missing_pairs']==6
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='pilot',expected_plan_sha256=plan['sha256'],
                expected_run_sha256=replay.digest,expected_reference_sha256=reference_digest(ref))
        assert goal.audit_journal(journal)['status'] == 'verified'
        from qjig.evaluation_semantic_review import review_fresh_semantics,verify_fresh_semantic_review
        from qjig.evaluation_scoring import score_reviewed_reserved_assignment
        with RunArchive.open(tmp_path/'review') as review_archive:
            def review_factory(req):
                return semantic_review_reservation(goal,'evaluation:study',request_id=rid,partition='holdout',request=req,spec=spec)
            review_fresh_semantics(archive,journal,ledger,StandInTransport([raw({'assessment':'supported','reason':'synthetic'})]),
                review_archive=review_archive,reference=ref,expected_reference_sha256=reference_digest(ref),
                expected_run_sha256=replay.digest,expected_journal_sha256=journal_anchor,provider='stand-in',
                model=model['id'],max_tokens=100,max_price=cap,reservation_factory=review_factory)
            review=verify_fresh_semantic_review(archive,journal,review_archive,reference=ref,
                expected_reference_sha256=reference_digest(ref),expected_run_sha256=replay.digest,expected_journal_sha256=journal_anchor)
            kwargs=dict(partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=replay.digest,
                expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_anchor,
                expected_review_sha256=review['sha256'],reviewer_spec=spec)
            scored_review=score_reviewed_reserved_assignment(goal,archive,journal,ref,review_archive,**kwargs)
            assert scored_review['review']['assessment']=='supported' and scored_review['score']['request_status']=='deferred'
            assert scored_review['score']['request_answer'] is None and scored_review['score']['resources']['total']['calls']==4
            with pytest.raises(ContractError):
                score_reviewed_reserved_assignment(goal,archive,journal,ref,review_archive,**{**kwargs,'expected_journal_sha256':'0'*64})
        # Even if the context and replay are rehashed, another assignment cannot be relabeled.
        changed = archive.context(); changed['evaluation_assignment']['repeat'] = 2
        encoded = json.dumps(changed,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        archive._con.execute('DROP TRIGGER context_no_update')
        archive._con.execute('UPDATE run_context SET data=?,sha256=? WHERE id=1',
                             (encoded,hashlib.sha256(encoded.encode()).hexdigest()))
        tampered = verify_archive(archive)
        assert tampered.status == 'unanchored'
        with pytest.raises(ContractError):
            score_reserved_assignment(goal,archive,journal,ref,partition='holdout',expected_plan_sha256=plan['sha256'],
                expected_run_sha256=tampered.digest,expected_reference_sha256=reference_digest(ref))


def test_decision_criteria_partition_and_incomplete_evidence():
    import copy
    from qjig.evaluation import validate_decision_criteria, decide_from_criteria, validate_evaluation_design
    design = _sample_design()
    # The historical >= thresholds overlap and must not qualify as frozen criteria.
    with pytest.raises(ContractError):
        validate_decision_criteria(design,expected_design_sha256=validate_evaluation_design(design))
    design['criteria'] = {
        'remove':{'metric':'outcome_support','operator':'<','threshold':0.5},
        'revise':{'metric':'outcome_support','operator':'range','threshold':[0.5,0.8]},
        'retain':{'metric':'outcome_support','operator':'>=','threshold':0.8}}
    digest = validate_evaluation_design(design)
    validate_decision_criteria(design,expected_design_sha256=digest)
    with pytest.raises(ContractError):
        validate_decision_criteria(design,expected_design_sha256=None)
    for value, expected in [(0,'remove'),(0.499,'remove'),(0.5,'revise'),(0.799,'revise'),(0.8,'retain'),(1,'retain')]:
        assert decide_from_criteria(design,value,expected_design_sha256=digest,assignments_complete=True,resources_complete=True)==expected
    assert decide_from_criteria(design,None,expected_design_sha256=digest,assignments_complete=True,resources_complete=True)=='inconclusive'
    assert decide_from_criteria(design,0.9,expected_design_sha256=digest,assignments_complete=False,resources_complete=True)=='inconclusive'
    for bad in (float('nan'),-0.1,1.1,True):
        with pytest.raises(ContractError):
            decide_from_criteria(design,bad,expected_design_sha256=digest,assignments_complete=True,resources_complete=True)
    for rule in ({'metric':'outcome_support','operator':'>=','threshold':0.5},
                 {'metric':'outcome_support','operator':'range','threshold':[0.6,0.8]},
                 {'metric':'outcome_support','operator':'range','threshold':[0.4,0.8]},
                 {'metric':'source_coverage','operator':'range','threshold':[0.5,0.8]}):
        changed = copy.deepcopy(design); changed['criteria']['revise'] = rule
        with pytest.raises(ContractError):
            validate_decision_criteria(changed,expected_design_sha256=validate_evaluation_design(changed))


def test_holdout_comparison_keeps_deferrals_and_missing_pairs_unknown():
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_scoring import summarize_holdout_comparison
    design = _sample_design(); digest = validate_evaluation_design(design)
    cases = [c['id'] for c in design['cases'] if c['family'].startswith('holdout')]
    records = []
    for case in cases:
        for repeat in (1,2):
            for arm in ('direct_retrieval','combined'):
                score = {'case_id':case,'run_sha256':hashlib.sha256(f'{case}-{repeat}-{arm}'.encode()).hexdigest(),
                         'reference_sha256':hashlib.sha256(case.encode()).hexdigest(),
                         'reference_provenance':'authored_unvalidated','reference_expected_answer':'yes',
                         'semantic_assurance':'not_assessed'}
                if arm == 'combined':
                    score.update(request_status='deferred',request_answer=None,conditional_answer='yes',
                                 required_evidence_covered=True)
                else:
                    score.update(recorded_answer='yes',answer_matches_reference=True,required_evidence_covered=True)
                records.append({'arm':arm,'repeat':repeat,'score':score})
    report = summarize_holdout_comparison(design,records,expected_design_sha256=digest,
                                          baseline_arm='direct_retrieval',candidate_arm='combined')
    assert report['assigned_pairs']==6 and report['recorded_pairs']==6
    assert report['baseline_reference_matches']==6 and report['candidate_unknown']==6
    assert report['candidate_mechanical_match_rate'] is None and report['paired_mechanical_difference'] is None
    assert report['outcome_support'] is None and report['semantic_assurance']=='not_assessed'
    assert all(p['baseline_status']=='reference_match' for p in report['pairs'])
    assert all(p['candidate_status']=='unknown' for p in report['pairs'])
    direct_records = []
    for record in records:
        copy = dict(record,score=dict(record['score']))
        if copy['arm']=='combined':
            copy['arm']='direct_full_evidence'
            copy['score'].update(recorded_answer='no',answer_matches_reference=False)
        direct_records.append(copy)
    complete = summarize_holdout_comparison(design,direct_records,expected_design_sha256=digest,
                                            baseline_arm='direct_retrieval',candidate_arm='direct_full_evidence')
    assert complete['baseline_mechanical_match_rate']==1 and complete['candidate_mechanical_match_rate']==0
    assert complete['paired_mechanical_difference']==-1
    partial = summarize_holdout_comparison(design,records[:-1],expected_design_sha256=digest,
                                           baseline_arm='direct_retrieval',candidate_arm='combined')
    assert partial['recorded_pairs']==5 and partial['missing_pairs']==1 and partial['candidate_mechanical_match_rate'] is None
    bad = [*records, records[0]]
    with pytest.raises(ContractError):
        summarize_holdout_comparison(design,bad,expected_design_sha256=digest,baseline_arm='direct_retrieval',candidate_arm='combined')
    changed = [dict(r,score=dict(r['score'])) for r in records]
    changed[1]['score']['reference_sha256']='0'*64
    with pytest.raises(ContractError):
        summarize_holdout_comparison(design,changed,expected_design_sha256=digest,baseline_arm='direct_retrieval',candidate_arm='combined')


def test_catalog_retrieval_includes_mandatory_channels_and_excludes_scope(tmp_path):
    from qjig.applicability import ApplicabilityInputs, Collection, Interval, MemberMetadata, OPEN
    from qjig.evaluation import CatalogRetrieval
    from qjig.sources import SourceRevision, decode_source
    texts = {'primary':b'Deployment requires approval.',
             'exception':b'Exception waiver allows deployment without approval.',
             'conflict':b'Conflicting revision says deployment does not require approval.',
             'other':b'Deployment approval exception is never required.'}
    sources = []
    revisions = {}
    for name, raw in texts.items():
        (tmp_path/name).write_bytes(raw)
        sources.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest()})
        revisions[name] = SourceRevision.create(name,'evaluation_allowlist',decode_source(raw,encoding='utf-8'))
    (tmp_path/'label').write_bytes(b'PRIVATE_REFERENCE_LABEL')
    protected = [{'path':'label','sha256':hashlib.sha256(b'PRIVATE_REFERENCE_LABEL').hexdigest()}]
    inputs = ApplicabilityInputs(Collection(tuple(MemberMetadata(r.revision_id,'other' if name=='other' else 'project',
                                         Interval('2020-01-01',OPEN)) for name,r in revisions.items())),
                                 frozenset(),'2026-11-07',False)
    search = CatalogRetrieval(tmp_path,sources,protected,want=3,max_bytes=5000,followups=1,
                              applicability_inputs=inputs,scope='project')
    result = search.search('deployment approval')
    texts_sent = [item.span.text for item in result['packet'].items]
    assert any('Exception waiver' in text for text in texts_sent)
    assert any('Conflicting revision' in text for text in texts_sent)
    assert all('never required' not in text for text in texts_sent)
    assert result['method']=='qjig_catalog_v1' and result['channels']['channel_hits']['exception'] > 0
    assert any(item['reason']=='inapplicable' for item in result['channels']['excluded'])
    assert all('PRIVATE_REFERENCE_LABEL' not in text for text in texts_sent)
    restricted = CatalogRetrieval(tmp_path,sources,protected,want=1,max_bytes=5000,followups=0,
                                  applicability_inputs=inputs,scope='project').search('deployment approval')
    assert restricted['channels']['channel_omitted']
    search.search('waiver')
    with pytest.raises(ContractError): search.search('third query')


def test_retrieval_only_checked_run_replays_and_refuses_omissions(tmp_path):
    import json
    from qjig.applicability import ApplicabilityInputs,Collection,Interval,MemberMetadata,OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget,Request
    from qjig.evaluation import load_isolated_sources,validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_direct import run_locked_direct
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import make_reference,reference_digest,score_direct_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse,StandInTransport
    from qjig.run_archive import RunArchive
    source_data={'primary':b'Deployment requires approval.',
                 'exception':b'Exception waiver allows deployment without approval.',
                 'conflict':b'Conflicting revision says deployment does not require approval.'}
    sources=[]
    for name,raw in source_data.items():
        (tmp_path/name).write_bytes(raw);sources.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest()})
    (tmp_path/'label').write_bytes(b'PRIVATE_REFERENCE_LABEL')
    protected=[{'path':'label','sha256':hashlib.sha256(b'PRIVATE_REFERENCE_LABEL').hexdigest()}]
    design=_sample_design();design['families'][0]['source_hashes']=[x['sha256'] for x in sources]
    digest=validate_evaluation_design(design)
    ref=make_reference(case_id='dev',request=Request('hidden','Does deployment require approval?','reviewer','1','project'),
        sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
        expected_answer='unknown',provenance='authored_unvalidated',evidence=[{'path':'primary','quote':'requires approval'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':digest,
          'question':'Does deployment require approval?','role':'reviewer','role_version':'1','scope':'project',
          'as_of':'2026-11-07','entities':[],'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    inputs=ApplicabilityInputs(Collection(tuple(MemberMetadata(rev,'project',Interval('2020-01-01',OPEN))
                                               for rev in ref['source_revisions'])),frozenset(),'2026-11-07',False)
    response=RawResponse(200,json.dumps({'action':'answer','query':None,'answer':'unknown','citations':[]}),
                         {'prompt_tokens':10,'completion_tokens':3,'cost_usd':0.001})
    for want, expected in [(3,'recorded_unvalidated'),(1,'unavailable')]:
        with Journal.open(tmp_path/f'j{want}.sqlite') as journal, RunArchive.open(tmp_path/f'a{want}') as archive:
            transport=StandInTransport([response]);ledger=BudgetLedger(Budget(2,10000,1),journal,'r')
            result=run_locked_direct(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
                expected_case_sha256=case_lock_digest(lock),ledger=ledger,transport=transport,archive=archive,
                provider='stand-in',model='synthetic',max_tokens=100,want=want,max_bytes=5000,followups=0,
                evidence_mode='catalog',applicability_inputs=inputs)
            assert result['status']==expected
            if want==1:
                assert result['failure']=='catalog_evidence_incomplete' and transport.calls_made==0
            else:
                assert transport.calls_made==1 and result['searches'][0]['method']=='qjig_catalog_v1'
                prompt=next(e['data']['prompt'] for e in archive.events() if e['kind']=='request')
                assert 'PRIVATE_REFERENCE_LABEL' not in prompt and 'Exception waiver' in prompt and 'Conflicting revision' in prompt
            replay=verify_direct_archive(archive,journal)
            assert replay['status']==('unanchored' if want==3 else 'incomplete')
            score=score_direct_archive(archive,journal,ref,expected_run_sha256=replay['sha256'],
                                       expected_reference_sha256=reference_digest(ref))
            assert score['semantic_assurance']=='not_assessed'
            if want==1: assert score['classification']=='retrieval_failure' and score['recorded_answer'] is None
            if want==3:
                trace=next(e for e in archive.events() if e['kind']=='trace')
                changed=trace['data'];changed['channels']['channel_hits']['exception']+=1
                archive._con.execute('DROP TRIGGER event_no_update')
                archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(changed),trace['seq']))
                assert verify_direct_archive(archive,journal)['status']=='invalid'


def test_decomposition_only_uses_all_applicable_sources_and_replays(tmp_path):
    import json
    from qjig.applicability import ApplicabilityInputs,Collection,Interval,MemberMetadata,OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget,Request
    from qjig.evaluation import load_isolated_sources,validate_evaluation_design
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_fresh import run_locked_fresh
    from qjig.evaluation_scoring import make_reference,reference_digest,score_fresh_archive
    from qjig.journal import Journal
    from qjig.providers import RawResponse,StandInTransport
    from qjig.replay import verify_archive
    from qjig.run_archive import RunArchive
    texts={'first':b'Checks must pass.','second':b'Unrelated details are also present.'}
    sources=[]
    for name,raw in texts.items():
        (tmp_path/name).write_bytes(raw);sources.append({'path':name,'sha256':hashlib.sha256(raw).hexdigest()})
    (tmp_path/'label').write_bytes(b'PRIVATE_LABEL')
    protected=[{'path':'label','sha256':hashlib.sha256(b'PRIVATE_LABEL').hexdigest()}]
    design=_sample_design();design['families'][0]['source_hashes']=[s['sha256'] for s in sources]
    digest=validate_evaluation_design(design)
    ref=make_reference(case_id='dev',request=Request('hidden','Do checks pass?','reviewer','1','project'),
        sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
        expected_answer='yes',provenance='authored_unvalidated',evidence=[{'path':'first','quote':'Checks must pass.'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'dev','design_sha256':digest,'question':'Do checks pass?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
          'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    inputs=ApplicabilityInputs(Collection(tuple(MemberMetadata(r,'project',Interval('2020-01-01',OPEN))
                                              for r in ref['source_revisions'])),frozenset(),'2026-11-07',False)
    usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.01}
    raw=lambda data:RawResponse(200,json.dumps(data),usage)
    responses=[raw({'predicates':[{'id':'p','question':'Unmatched zyzzword?'}],'expression':{'ref':'p'}}),
               raw({'supported':True,'quote':'Checks must pass.','reason':'synthetic'}),
               raw({'supported':False,'quote':'','reason':'synthetic'})]
    for limit in (5000,100):
        with Journal.open(tmp_path/f'j{limit}.sqlite') as journal, RunArchive.open(tmp_path/f'a{limit}') as archive:
            transport=StandInTransport(responses);ledger=BudgetLedger(Budget(8,50000,1),journal,'r')
            kwargs=dict(expected_design_sha256=digest,expected_case_sha256=case_lock_digest(lock),applicability_inputs=inputs,
                        ledger=ledger,transport=transport,archive=archive,planner=('stand-in','planner'),judge=('stand-in','judge'),
                        want=1,max_bytes=limit,evidence_mode='full')
            if limit==100:
                with pytest.raises(ContractError):run_locked_fresh(tmp_path,design,lock,ref,protected,**kwargs)
                assert transport.calls_made==0 and journal.events('r')==[] and archive.events()==[]
                continue
            result=run_locked_fresh(tmp_path,design,lock,ref,protected,**kwargs)
            assert result.status=='deferred' and transport.calls_made==3
            prompts=[e['data']['prompt'] for e in archive.events() if e['kind']=='request']
            assert all(all(raw.decode() in prompt for raw in texts.values()) and 'PRIVATE_LABEL' not in prompt for prompt in prompts)
            assert all(t.retrieval_method=='full_source_v1' and len(t.evidence)==2 for t in result.state.trace)
            replay=verify_archive(archive);assert replay.status=='unanchored'
            score=score_fresh_archive(archive,journal,ref,expected_run_sha256=replay.digest,
                                      expected_reference_sha256=reference_digest(ref))
            assert score['request_status']=='deferred' and score['request_answer'] is None
            trace=next(e for e in archive.events() if e['kind']=='trace')
            altered=trace['data'];altered['evidence'].pop()
            archive._con.execute('DROP TRIGGER event_no_update')
            archive._con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(altered),trace['seq']))
            assert verify_archive(archive).status=='invalid'
    wrong_inputs=ApplicabilityInputs(Collection(tuple(MemberMetadata(r,'other' if i==0 else 'project',Interval('2020-01-01',OPEN))
                                                    for i,r in enumerate(ref['source_revisions']))),frozenset(),'2026-11-07',False)
    with Journal.open(tmp_path/'bad.sqlite') as journal,RunArchive.open(tmp_path/'bad') as archive:
        transport=StandInTransport(responses)
        with pytest.raises(ContractError):
            run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
                expected_case_sha256=case_lock_digest(lock),applicability_inputs=wrong_inputs,
                ledger=BudgetLedger(Budget(8,50000,1),journal,'r'),transport=transport,archive=archive,
                planner=('stand-in','planner'),judge=('stand-in','judge'),evidence_mode='full')
        assert transport.calls_made==0 and journal.events('r')==[] and archive.events()==[]


def test_factorial_allocation_enumerates_real_arm_work_before_reservation(tmp_path):
    from collections import Counter
    from qjig.contracts import Budget
    from qjig.budgets import BudgetExceeded
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_budget import build_factorial_allocation,reserve_evaluation_plan
    from qjig.goal_budget import GoalBudget
    design=_sample_design();digest=validate_evaluation_design(design)
    hashes={case['id']:hashlib.sha256(case['id'].encode()).hexdigest() for case in design['cases']}
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,
          'max_price':{'prompt':2,'completion':3}}
    config={name:dict(spec) for name in ('direct','planner','judge','reviewer')}
    plan=build_factorial_allocation(design,hashes,config,expected_design_sha256=digest,assignment_secret=b'x'*32)
    assert len(plan['manifest']['assignments'])==60
    with_semantic = build_factorial_allocation(design,hashes,{**config,'semantic_reviewer':dict(spec)},
                                               expected_design_sha256=digest,assignment_secret=b'x'*32)
    assert all(a['work'] and sum(w['stage']=='semantic_review' for w in a['work'])==1
               for a in with_semantic['manifest']['assignments'])
    assert all(template['semantic_review']==1 for template in with_semantic['manifest']['stage_templates'].values())
    assert with_semantic['sha256'] != plan['sha256']
    templates=plan['manifest']['stage_templates']
    assert templates['direct_full_evidence']=={'direct_initial':1}
    assert templates['direct_retrieval']==templates['retrieval_only']=={'direct_initial':1,'direct_final':1}
    for arm in ('combined','decomposition_only'):
        assert templates[arm]=={'planner':1,'judge_positive':12,'judge_negative':12,'plan_review':1}
    assert all(Counter(s['stage'] for s in a['work'])==Counter(templates[a['arm']]) for a in plan['manifest']['assignments'])
    assert all(a['case_id'] not in a['request_id'] and a['arm'] not in a['request_id'] for a in plan['manifest']['assignments'])
    assert build_factorial_allocation(design,hashes,config,expected_design_sha256=digest,assignment_secret=b'x'*32)==plan
    assert build_factorial_allocation(design,hashes,config,expected_design_sha256=digest,assignment_secret=b'y'*32)['sha256']!=plan['sha256']
    with pytest.raises(ContractError):
        build_factorial_allocation(design,hashes,{k:v for k,v in config.items() if k!='reviewer'},
                                   expected_design_sha256=digest,assignment_secret=b'x'*32)
    budgets={'development':Budget(200,50000,2),'pilot':Budget(200,50000,2),'holdout':Budget(400,100000,6)}
    with GoalBudget.open(tmp_path/'goal.sqlite',total=Budget(800,200000,10),per_request=Budget(30,6000,1),allocations=budgets) as goal:
        receipt=reserve_evaluation_plan(goal,'factorial',plan,expected_plan_sha256=plan['sha256'])
        assert receipt['assignments']==60 and receipt['work_items']==684
    short={'development':Budget(100,50000,2),'pilot':Budget(200,50000,2),'holdout':Budget(400,100000,6)}
    with GoalBudget.open(tmp_path/'short.sqlite',total=Budget(700,200000,10),per_request=Budget(30,6000,1),allocations=short) as goal:
        with pytest.raises(BudgetExceeded):reserve_evaluation_plan(goal,'factorial',plan,expected_plan_sha256=plan['sha256'])
        assert goal._con.execute('SELECT COUNT(*) FROM evaluation_plans').fetchone()[0]==0


@pytest.mark.parametrize('driver',['manual','runner','runner_v2','runner_semantic'])
def test_factorial_allocation_executes_all_arms_with_reserved_review(tmp_path,driver):
    import json
    from contextlib import ExitStack
    from qjig.applicability import ApplicabilityInputs,Collection,Interval,MemberMetadata,OPEN
    from qjig.budgets import BudgetLedger
    from qjig.contracts import Budget,Request
    from qjig.direct_preflight import direct_slot_reservation
    from qjig.evaluation import load_isolated_sources,validate_evaluation_design
    from qjig.evaluation_budget import build_factorial_allocation,reserve_evaluation_plan
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_campaign import EvaluationCampaign,run_campaign_assignment
    from qjig.evaluation_direct import run_locked_direct
    from qjig.evaluation_fresh import run_locked_fresh
    from qjig.evaluation_replay import verify_direct_archive
    from qjig.evaluation_scoring import make_reference,reference_digest,fresh_journal_digest,build_reserved_holdout_comparison
    from qjig.fresh_preflight import fresh_slot_reservation
    from qjig.goal_budget import GoalBudget
    from qjig.journal import Journal
    from qjig.providers import RawResponse,StandInTransport
    from qjig.replay import verify_archive
    from qjig.run_archive import RunArchive
    code,gold=b'Tests must pass.',b'PRIVATE_FACTORIAL_REFERENCE'
    (tmp_path/'code').write_bytes(code);(tmp_path/'label').write_bytes(gold)
    item=lambda path,raw:{'path':path,'sha256':hashlib.sha256(raw).hexdigest()}
    sources,protected=[item('code',code)],[item('label',gold)]
    design=_sample_design();design['families'][4]['source_hashes']=[sources[0]['sha256']]
    digest=validate_evaluation_design(design)
    ref=make_reference(case_id='holdout',request=Request('hidden','Do tests pass?','reviewer','1','project'),
        sources=load_isolated_sources(tmp_path,sources,protected),as_of='2026-11-07',entities=[],historical_as_known=False,
        expected_answer='yes',provenance='authored_unvalidated',evidence=[{'path':'code','quote':'Tests must pass.'}])
    lock={'schema':'qjig.evaluation-case.v1','case_id':'holdout','design_sha256':digest,'question':'Do tests pass?',
          'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
          'historical_as_known':False,'sources':sources,'reference_sha256':reference_digest(ref)}
    case_hashes={c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']}
    case_hashes['holdout']=case_lock_digest(lock)
    inputs=ApplicabilityInputs(Collection((MemberMetadata(ref['source_revisions'][0],'project',Interval('2020-01-01',OPEN)),)),
                               frozenset(),'2026-11-07',False)
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3};spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':cap}
    stage_names=('direct','planner','judge','reviewer','semantic_reviewer') if driver=='runner_semantic' else ('direct','planner','judge','reviewer')
    plan=build_factorial_allocation(design,case_hashes,{k:dict(spec) for k in stage_names},
                                    expected_design_sha256=digest,assignment_secret=b'synthetic-private-test-secret-32-bytes')
    usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    raw=lambda value:RawResponse(200,json.dumps(value),usage)
    total=Budget(800,200000,10);per=Budget(30,6000,1)
    allocations={'development':Budget(200,50000,2),'pilot':Budget(200,50000,2),'holdout':Budget(400,100000,6)}
    entries={}
    with ExitStack() as stack:
        goal=stack.enter_context(GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=allocations))
        journal=stack.enter_context(Journal.open(tmp_path/'journal.sqlite'))
        reserve_evaluation_plan(goal,'factorial',plan,expected_plan_sha256=plan['sha256'])
        campaign=EvaluationCampaign(goal,'factorial',expected_plan_sha256=plan['sha256'])
        from qjig.evaluation_campaign import applicability_digest
        metadata_hashes={case['id']:applicability_digest(inputs) for case in design['cases']}
        config_digest = campaign.freeze_config({k:dict(spec) for k in stage_names},want=1,max_bytes=5000,case_applicability=metadata_hashes, **({'planner_prompt_version':'exception_applicability_v2'} if driver in ('runner_v2','runner_semantic') else {})) if driver!='manual' else None
        if driver=='runner':
            assert campaign.freeze_config({k:dict(spec) for k in stage_names},want=1,max_bytes=5000,case_applicability=metadata_hashes)==config_digest
            with pytest.raises(ContractError):
                campaign.freeze_config({k:dict(spec) for k in stage_names},want=1,max_bytes=5000,
                                       case_applicability={'holdout':metadata_hashes['holdout']})
            with pytest.raises(ContractError):
                campaign.freeze_config({k:dict(spec) for k in stage_names},want=2,max_bytes=5000,case_applicability=metadata_hashes)
        for arm in design['arms']:
            assignment=next(a for a in plan['manifest']['assignments'] if a['case_id']=='holdout' and a['arm']==arm and a['repeat']==1)
            rid=assignment['request_id'];ledger=BudgetLedger(per,journal,rid,goal_budget=goal,partition='holdout')
            if driver!='manual':
                archive=stack.enter_context(RunArchive.open(tmp_path/('archive-'+arm)))
                if arm in ('combined','decomposition_only'):
                    responses=[raw({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                        raw({'supported':True,'quote':'Tests must pass.','reason':'synthetic'}),
                        raw({'supported':False,'quote':'','reason':'synthetic'}),raw({'assessment':'uncertain','reason':'synthetic'})]
                else:
                    responses=[raw({'action':'answer','query':None,'answer':'unknown','citations':[]})]
                if driver=='runner_semantic':
                    responses.append(raw({'assessment':'uncertain','reason':'synthetic review'}))
                    semantic_archive=stack.enter_context(RunArchive.open(tmp_path/('semantic-'+arm)))
                transport=StandInTransport(responses)
                if driver=='runner_semantic':
                    with pytest.raises(ContractError,match='semantic review archive'):
                        run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                            applicability_inputs=inputs,transport=transport,archive=archive,journal=journal,
                            config={k:dict(spec) for k in stage_names},want=1,max_bytes=5000,expected_config_sha256=config_digest)
                    assert campaign.status()['in_progress']==[] and transport.calls_made==0
                changed_inputs=ApplicabilityInputs(Collection((MemberMetadata(ref['source_revisions'][0],'other',Interval('2020-01-01',OPEN)),)),frozenset(),'2026-11-07',False)
                with pytest.raises(ContractError):
                    run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                        applicability_inputs=changed_inputs,transport=transport,archive=archive,journal=journal,
                        config={k:dict(spec) for k in stage_names},want=1,max_bytes=5000,
                        expected_config_sha256=config_digest)
                assert campaign.status()['in_progress']==[] and transport.calls_made==0
                bad_config={k:dict(spec) for k in stage_names}
                changed='planner' if arm in ('combined','decomposition_only') else 'direct'
                bad_config[changed]['input_tokens']=99
                with pytest.raises(ContractError):
                    run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                        applicability_inputs=inputs,transport=transport,archive=archive,journal=journal,
                        config=bad_config,want=1,max_bytes=5000,expected_config_sha256=config_digest)
                assert campaign.status()['in_progress']==[] and journal.events(rid)==[] and transport.calls_made==0
                with pytest.raises(ContractError):
                    run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                        applicability_inputs=inputs,transport=transport,archive=archive,journal=journal,
                        config={k:dict(spec) for k in stage_names},want=2,max_bytes=5000,
                        expected_config_sha256=config_digest)
                with pytest.raises(ContractError):
                    run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                        applicability_inputs=inputs,transport=transport,archive=archive,journal=journal,
                        config={k:dict(spec) for k in stage_names},want=1,max_bytes=5000,
                        expected_config_sha256='0'*64)
                receipt=run_campaign_assignment(campaign,rid,tmp_path,design,lock,ref,protected,
                    applicability_inputs=inputs,transport=transport,archive=archive,journal=journal,
                    config={k:dict(spec) for k in stage_names},want=1,max_bytes=5000,expected_config_sha256=config_digest,
                    **({'semantic_review_archive':semantic_archive} if driver=='runner_semantic' else {}))
                assert receipt['status']=='scored' and transport.calls_made==((4 if arm in ('combined','decomposition_only') else 1)+(driver=='runner_semantic'))
                if driver=='runner_semantic':
                    from qjig.evaluation_scoring import score_reviewed_reserved_assignment
                    review_kwargs=dict(partition='holdout',expected_plan_sha256=plan['sha256'],
                        expected_run_sha256=receipt['run_sha256'],expected_journal_sha256=receipt['journal_sha256'],
                        expected_reference_sha256=reference_digest(ref),expected_review_sha256=receipt['semantic_review_sha256'],
                        reviewer_spec=spec)
                    verified=score_reviewed_reserved_assignment(goal,archive,journal,ref,semantic_archive,**review_kwargs)
                    assert verified['review']['assessment']=='uncertain'
                    with pytest.raises(ContractError):
                        score_reviewed_reserved_assignment(goal,archive,journal,ref,semantic_archive,
                            **{**review_kwargs,'expected_review_sha256':'0'*64})
                    assert EvaluationCampaign(goal,'factorial',expected_plan_sha256=plan['sha256']).status()['scored'] >= 1
                if driver=='runner_v2' and arm in ('combined','decomposition_only'):
                    assert archive.context()['planner_prompt_version']=='exception_applicability_v2'
                    from qjig.evaluation_campaign import check_archive_config
                    frozen=campaign.require_config({k:dict(spec) for k in stage_names},want=1,max_bytes=5000,expected_config_sha256=config_digest)
                    changed_context={**archive.context(), 'planner_prompt_version':'legacy_v1'}
                    with pytest.raises(ContractError, match='prompt version'):
                        check_archive_config(frozen,changed_context,assignment)
                prompts=[e['data']['prompt'] for e in archive.events() if e['kind']=='request']
                assert all(gold.decode() not in p and rid not in p and arm not in p for p in prompts)
                entries[arm]={'archive':archive,'journal':journal,'reference':ref,'run_sha256':receipt['run_sha256'],
                              'reference_sha256':reference_digest(ref),'journal_sha256':receipt['journal_sha256']}
                if driver=='runner_semantic':
                    entries[arm].update(review_archive=semantic_archive,review_sha256=receipt['semantic_review_sha256'])
                with pytest.raises(ContractError):campaign.claim(rid)
                continue
            claim=campaign.claim(rid)
            assert claim['case_id']=='holdout' and claim['arm']==arm and claim['repeat']==1
            archive=stack.enter_context(RunArchive.open(tmp_path/('archive-'+arm)))
            binding={'plan_id':'factorial','plan_sha256':plan['sha256'],'arm':arm,'repeat':1}
            if arm in ('combined','decomposition_only'):
                transport=StandInTransport([raw({'predicates':[{'id':'p','question':'Do tests pass?'}],'expression':{'ref':'p'}}),
                    raw({'supported':True,'quote':'Tests must pass.','reason':'synthetic'}),
                    raw({'supported':False,'quote':'','reason':'synthetic'}),raw({'assessment':'uncertain','reason':'synthetic'})])
                def factory(req):return fresh_slot_reservation(goal,'evaluation:factorial',request_id=rid,partition='holdout',
                    request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
                result=run_locked_fresh(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
                    expected_case_sha256=case_lock_digest(lock),applicability_inputs=inputs,ledger=ledger,transport=transport,
                    archive=archive,planner=('stand-in',model['id']),judge=('stand-in',model['id']),reviewer=('stand-in',model['id']),
                    planner_max_tokens=100,judge_max_tokens=100,reviewer_max_tokens=100,planner_max_price=cap,
                    judge_max_price=cap,reviewer_max_price=cap,reservation_factory=factory,review_reservation_factory=factory,
                    assignment_binding=binding,evidence_mode='full' if arm=='decomposition_only' else 'catalog')
                assert result.status=='deferred' and result.review.status=='recorded' and transport.calls_made==4
                replay=verify_archive(archive);assert replay.status=='unanchored'
                run_hash=replay.digest;journal_hash=fresh_journal_digest(journal,rid)
            else:
                transport=StandInTransport([raw({'action':'answer','query':None,'answer':'unknown','citations':[]})])
                def factory(req):return direct_slot_reservation(goal,'evaluation:factorial',request_id=rid,partition='holdout',
                    request=req,model=model,input_tokens=100,input_bound_provenance='synthetic')
                mode={'direct_full_evidence':'full','direct_retrieval':'retrieved','retrieval_only':'catalog'}[arm]
                result=run_locked_direct(tmp_path,design,lock,ref,protected,expected_design_sha256=digest,
                    expected_case_sha256=case_lock_digest(lock),ledger=ledger,transport=transport,archive=archive,
                    provider='stand-in',model=model['id'],max_tokens=100,want=1,max_bytes=5000,
                    followups=0 if mode=='full' else 1,evidence_mode=mode,applicability_inputs=inputs,
                    reservation_factory=factory,max_price=cap,assignment_binding=binding)
                assert result['status']=='recorded_unvalidated' and transport.calls_made==1
                replay=verify_direct_archive(archive,journal);assert replay['status']=='unanchored'
                run_hash=replay['sha256'];journal_hash=None
            prompts=[e['data']['prompt'] for e in archive.events() if e['kind']=='request']
            assert all(gold.decode() not in p and rid not in p and arm not in p for p in prompts)
            entries[arm]={'archive':archive,'journal':journal,'reference':ref,'run_sha256':run_hash,
                          'reference_sha256':reference_digest(ref),'journal_sha256':journal_hash}
            with pytest.raises(ContractError):
                campaign.finish(rid,archive,journal,ref,expected_run_sha256='0'*64,
                                expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash)
            assert campaign.status()['in_progress']==[rid]
            receipt=campaign.finish(rid,archive,journal,ref,expected_run_sha256=run_hash,
                                    expected_reference_sha256=reference_digest(ref),expected_journal_sha256=journal_hash)
            assert receipt['status']=='scored' and len(receipt['score_sha256'])==64
            with pytest.raises(ContractError):campaign.claim(rid)
        assert goal.audit_journal(journal)['status']=='verified'
        if driver=='runner_semantic':
            assert campaign.status()['scored']==5
            pair=[entries['direct_retrieval'],entries['combined']]
            opts=dict(plan_id='factorial',expected_plan_sha256=plan['sha256'],expected_design_sha256=digest,
                      baseline_arm='direct_retrieval',candidate_arm='combined',expected_config_sha256=config_digest)
            report=build_reserved_holdout_comparison(goal,design,pair,**opts)
            assert report['recorded_pairs']==1 and report['missing_pairs']==5 and report['outcome_support'] is None
            assert report['semantic_reviews']['uncertain']==2 and report['semantic_reviews']['assurance']=='unvalidated'
            assert {r['arm'] for r in report['semantic_reviews']['records']}=={'direct_retrieval','combined'}
            assert all(r['case_id']=='holdout' and r['repeat']==1 for r in report['semantic_reviews']['records'])
            with pytest.raises(ContractError):
                build_reserved_holdout_comparison(goal,design,[pair[0],{**pair[1],'review_sha256':'0'*64}],**opts)
            with pytest.raises(ContractError):
                build_reserved_holdout_comparison(goal,design,pair,**{**opts,'expected_config_sha256':'0'*64})
            return
        for arm in ('direct_full_evidence','retrieval_only','decomposition_only','combined'):
            report=build_reserved_holdout_comparison(goal,design,[entries['direct_retrieval'],entries[arm]],plan_id='factorial',
                expected_plan_sha256=plan['sha256'],expected_design_sha256=digest,baseline_arm='direct_retrieval',candidate_arm=arm)
            assert report['recorded_pairs']==1 and report['missing_pairs']==5 and report['outcome_support'] is None
        pending=next(a for a in plan['manifest']['assignments'] if a['case_id']=='holdout' and a['repeat']==2 and a['arm']=='direct_retrieval')
        if driver=='runner':
            interrupted=stack.enter_context(RunArchive.open(tmp_path/'interrupted'))
            timed_out=StandInTransport([TimeoutError('synthetic timeout')])
            with pytest.raises(ContractError):
                run_campaign_assignment(campaign,pending['request_id'],tmp_path,design,lock,ref,protected,
                    applicability_inputs=inputs,transport=timed_out,archive=interrupted,journal=journal,
                    config={k:dict(spec) for k in stage_names},want=1,max_bytes=5000,expected_config_sha256=config_digest)
            assert timed_out.calls_made==1 and journal.pending(pending['request_id'])
        else:
            campaign.claim(pending['request_id'])
        restarted=EvaluationCampaign(goal,'factorial',expected_plan_sha256=plan['sha256'])
        assert restarted.status()['in_progress']==[pending['request_id']]
        other=next(a for a in plan['manifest']['assignments'] if a['request_id']!=pending['request_id'] and a['request_id'] not in {e['archive'].context()['request']['request_id'] for e in entries.values()})
        with pytest.raises(ContractError):restarted.claim(other['request_id'])
        with pytest.raises(ContractError):restarted.claim(pending['request_id'])
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=allocations) as reopened:
        recovered=EvaluationCampaign(reopened,'factorial',expected_plan_sha256=plan['sha256'])
        assert recovered.status()['scored']==5 and recovered.status()['in_progress']==[pending['request_id']]
        if driver=='runner':
            import sqlite3
            recovered.require_config({k:dict(spec) for k in stage_names},
                                     want=1,max_bytes=5000,expected_config_sha256=config_digest)
            with pytest.raises(sqlite3.IntegrityError):
                reopened._con.execute("UPDATE evaluation_campaign_config SET value='{}'")
        with pytest.raises(ContractError):recovered.claim(other['request_id'])
        with pytest.raises(ContractError):EvaluationCampaign(reopened,'factorial',expected_plan_sha256='0'*64)
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            reopened._con.execute("UPDATE evaluation_campaign_events SET payload='{}' WHERE kind='started'")


@pytest.mark.parametrize('mismatch',['scope','date','entity','unknown','semantic','semantic_unknown','semantic_failure','semantic_failure_fresh','semantic_timeout'])
def test_campaign_batch_preflights_all_cases_and_resumes_verified_receipts(tmp_path,mismatch):
    import copy,json
    from qjig.applicability import ApplicabilityInputs,Collection,Interval,MemberMetadata,OPEN,UNKNOWN_BOUND
    from qjig.contracts import Budget,Request
    from qjig.evaluation import load_isolated_sources,validate_evaluation_design
    from qjig.evaluation_budget import build_factorial_allocation,reserve_evaluation_plan
    from qjig.evaluation_campaign import EvaluationCampaign,applicability_digest,run_campaign_batch
    from qjig.evaluation_cases import case_lock_digest
    from qjig.evaluation_scoring import make_reference,reference_digest
    from qjig.goal_budget import GoalBudget
    from qjig.journal import Journal
    from qjig.providers import RawResponse,StandInTransport
    design=_sample_design();sources={}
    for family in design['families']:
        name=family['id'];raw=f'Checks for {name} must pass.'.encode();(tmp_path/name).write_bytes(raw)
        sources[name]={'path':name,'sha256':hashlib.sha256(raw).hexdigest()};family['source_hashes']=[sources[name]['sha256']]
    gold=b'PRIVATE_BATCH_LABEL';(tmp_path/'label').write_bytes(gold)
    protected=[{'path':'label','sha256':hashlib.sha256(gold).hexdigest()}]
    digest=validate_evaluation_design(design);cases={};hashes={};metadata={}
    for case in design['cases']:
        ident,family=case['id'],case['family'];question=f'Do checks for {family} pass?'
        isolated=load_isolated_sources(tmp_path,[sources[family]],protected)
        ref=make_reference(case_id=ident,request=Request('hidden',question,'reviewer','1','project'),sources=isolated,
            as_of='2026-11-07',entities=[],historical_as_known=False,expected_answer='yes',provenance='authored_unvalidated',
            evidence=[{'path':family,'quote':isolated[0].raw.decode()}])
        lock={'schema':'qjig.evaluation-case.v1','case_id':ident,'design_sha256':digest,'question':question,
              'role':'reviewer','role_version':'1','scope':'project','as_of':'2026-11-07','entities':[],
              'historical_as_known':False,'sources':[sources[family]],'reference_sha256':reference_digest(ref)}
        inputs=ApplicabilityInputs(Collection((MemberMetadata(ref['source_revisions'][0],'project',Interval('2020-01-01',OPEN)),)),
                                   frozenset(),'2026-11-07',False)
        cases[ident]={'lock':lock,'reference':ref,'protected':protected,'applicability_inputs':inputs}
        hashes[ident]=case_lock_digest(lock);metadata[ident]=applicability_digest(inputs)
    wrong=cases['holdout']['applicability_inputs'];rev=wrong.collection.members[0].revision_id
    if mismatch=='entity':
        cases['holdout']['reference']['entities']=['target']
        cases['holdout']['lock']['entities']=['target']
        cases['holdout']['lock']['reference_sha256']=reference_digest(cases['holdout']['reference'])
        hashes['holdout']=case_lock_digest(cases['holdout']['lock'])
    scope='other' if mismatch=='scope' else 'project'
    interval=Interval('2027-01-01',OPEN) if mismatch=='date' else Interval(UNKNOWN_BOUND,OPEN) if mismatch in ('unknown','semantic_unknown') else Interval('2020-01-01',OPEN)
    member=MemberMetadata(rev,scope,interval,entity_keys=frozenset({'other'}) if mismatch=='entity' else frozenset())
    wrong=ApplicabilityInputs(Collection((member,)),frozenset({'target'}) if mismatch=='entity' else frozenset(),'2026-11-07',False)
    cases['holdout']['applicability_inputs']=wrong;metadata['holdout']=applicability_digest(wrong)
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    cap={'prompt':2,'completion':3};spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':cap}
    config={k:dict(spec) for k in (('direct','planner','judge','reviewer','semantic_reviewer') if mismatch in ('semantic','semantic_unknown','semantic_failure','semantic_failure_fresh','semantic_timeout') else ('direct','planner','judge','reviewer'))}
    plan=build_factorial_allocation(design,hashes,config,expected_design_sha256=digest,assignment_secret=b'private-synthetic-batch-secret-32-bytes')
    total=Budget(800,200000,10);per=Budget(30,6000,1)
    allocations={'development':Budget(200,50000,2),'pilot':Budget(200,50000,2),'holdout':Budget(400,100000,6)}
    calls=[];usage={'prompt_tokens':10,'completion_tokens':5,'cost_usd':0.0001}
    def transport_for(assignment):
        calls.append(assignment['request_id']);raw=lambda data:RawResponse(200,json.dumps(data),usage)
        if assignment['arm'] in ('combined','decomposition_only'):
            family=next(c['family'] for c in design['cases'] if c['id']==assignment['case_id'])
            text=(tmp_path/family).read_text()
            responses=[raw({'predicates':[{'id':'p','question':'Do checks pass?'}],'expression':{'ref':'p'}}),
                       raw({'supported':True,'quote':text,'reason':'synthetic'}),
                       raw({'supported':False,'quote':'','reason':'synthetic'}),raw({'assessment':'uncertain','reason':'synthetic'})]
        else:responses=[raw({'action':'answer','query':None,'answer':'unknown','citations':[]})]
        if mismatch in ('semantic','semantic_unknown','semantic_failure','semantic_failure_fresh','semantic_timeout'):responses.append(raw({'assessment':'uncertain','reason':'synthetic review'}))
        return StandInTransport(responses)
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=allocations) as goal,Journal.open(tmp_path/'journal.sqlite') as journal:
        reserve_evaluation_plan(goal,'batch',plan,expected_plan_sha256=plan['sha256'])
        campaign=EvaluationCampaign(goal,'batch',expected_plan_sha256=plan['sha256'])
        config_hash=campaign.freeze_config(config,want=1,max_bytes=5000,case_applicability=metadata)
        if mismatch=='semantic_unknown':
            from qjig.evaluation_campaign import run_campaign_assignment
            from qjig.run_archive import RunArchive
            from qjig.evaluation_scoring import score_reviewed_reserved_assignment
            target=next(a for a in plan['manifest']['assignments'] if a['case_id']=='holdout' and a['arm']=='decomposition_only' and a['repeat']==1)
            data=cases['holdout'];rid=target['request_id'];transport=transport_for(target)
            with RunArchive.open(tmp_path/'deferred') as archive,RunArchive.open(tmp_path/'unavailable') as review_archive:
                receipt=run_campaign_assignment(campaign,rid,tmp_path,design,data['lock'],data['reference'],data['protected'],
                    applicability_inputs=data['applicability_inputs'],transport=transport,archive=archive,journal=journal,
                    config=config,want=1,max_bytes=5000,expected_config_sha256=config_hash,semantic_review_archive=review_archive)
                assert transport.calls_made==0 and journal.events(rid)==[] and receipt['status']=='scored'
                scored=score_reviewed_reserved_assignment(goal,archive,journal,data['reference'],review_archive,
                    partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                    expected_reference_sha256=reference_digest(data['reference']),expected_review_sha256=receipt['semantic_review_sha256'],
                    reviewer_spec=spec)
                assert scored['score']['request_status']=='deferred' and scored['review']['assessment']=='uncertain'
                assert scored['review']['assurance']=='not_reviewed' and scored['review']['reason']=='source_applicability_unestablished'
                for changes in ({'expected_review_sha256':'0'*64}, {'expected_run_sha256':'0'*64},
                                {'reviewer_spec':{**spec,'output_tokens':99}}):
                    args=dict(partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                        expected_reference_sha256=reference_digest(data['reference']),expected_review_sha256=receipt['semantic_review_sha256'],reviewer_spec=spec)
                    with pytest.raises(ContractError):
                        score_reviewed_reserved_assignment(goal,archive,journal,data['reference'],review_archive,**{**args,**changes})
                review_archive._con.execute('DROP TRIGGER event_no_update')
                review_archive._con.execute("UPDATE events SET data='{}' WHERE kind='run_result'")
                with pytest.raises(ContractError):
                    score_reviewed_reserved_assignment(goal,archive,journal,data['reference'],review_archive,
                        partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                        expected_reference_sha256=reference_digest(data['reference']),expected_review_sha256=receipt['semantic_review_sha256'],reviewer_spec=spec)
            assert campaign.status()['scored']==1 and campaign.status()['in_progress']==[]
            return
        if mismatch in ('semantic_failure','semantic_failure_fresh','semantic_timeout'):
            from qjig.evaluation_campaign import run_campaign_assignment
            from qjig.run_archive import RunArchive
            from qjig.evaluation_scoring import score_reviewed_reserved_assignment
            target=next(a for a in plan['manifest']['assignments'] if a['case_id']=='holdout' and a['arm']==('combined' if mismatch=='semantic_failure_fresh' else 'direct_full_evidence') and a['repeat']==1)
            data=cases['holdout'];rid=target['request_id']
            transport=StandInTransport([TimeoutError('synthetic timeout') if mismatch=='semantic_timeout' else RawResponse(200,'not json',usage)])
            with RunArchive.open(tmp_path/'failed') as archive,RunArchive.open(tmp_path/'unavailable') as review_archive:
                kwargs=dict(applicability_inputs=data['applicability_inputs'],transport=transport,archive=archive,journal=journal,
                    config=config,want=1,max_bytes=5000,expected_config_sha256=config_hash,semantic_review_archive=review_archive)
                if mismatch=='semantic_timeout':
                    with pytest.raises(ContractError):
                        run_campaign_assignment(campaign,rid,tmp_path,design,data['lock'],data['reference'],data['protected'],**kwargs)
                    assert transport.calls_made==1 and journal.pending(rid) and not review_archive.events()
                    assert campaign.status()['in_progress']==[rid] and campaign.status()['scored']==0
                    return
                receipt=run_campaign_assignment(campaign,rid,tmp_path,design,data['lock'],data['reference'],data['protected'],**kwargs)
                assert transport.calls_made==1 and receipt['status']=='scored'
                result=score_reviewed_reserved_assignment(goal,archive,journal,data['reference'],review_archive,
                    partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                    expected_reference_sha256=reference_digest(data['reference']),expected_review_sha256=receipt['semantic_review_sha256'],reviewer_spec=spec,
                    expected_journal_sha256=receipt['journal_sha256'])
                assert result['score']['classification']=='malformed' and result['score']['failure_verified']
                assert result['review']['assurance']=='not_reviewed' and result['review']['assessment']=='uncertain'
                with pytest.raises(ContractError):
                    score_reviewed_reserved_assignment(goal,archive,journal,data['reference'],review_archive,
                        partition='holdout',expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                        expected_reference_sha256=reference_digest(data['reference']),expected_review_sha256='0'*64,
                        expected_journal_sha256=receipt['journal_sha256'],reviewer_spec=spec)
            assert campaign.status()['scored']==1 and campaign.status()['in_progress']==[]
            return
        broken=copy.deepcopy(cases);broken['holdout']['reference']['expected_answer']='no'
        with pytest.raises(ContractError):
            run_campaign_batch(campaign,tmp_path,design,broken,journal=journal,archive_root=tmp_path/'runs',config=config,
                               want=1,max_bytes=5000,expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=2)
        assert calls==[] and campaign.status()['scored']==0
        first=run_campaign_batch(campaign,tmp_path,design,cases,journal=journal,archive_root=tmp_path/'runs',config=config,
                                 want=1,max_bytes=5000,expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=2)
        assert first['executed']==2 and first['scored']==2 and first['remaining']==58 and len(calls)==2
        second=run_campaign_batch(EvaluationCampaign(goal,'batch',expected_plan_sha256=plan['sha256']),tmp_path,design,cases,
                                  journal=journal,archive_root=tmp_path/'runs',config=config,want=1,max_bytes=5000,
                                  expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=2)
        assert second['executed']==2 and second['scored']==4 and second['remaining']==56 and len(set(calls))==4
        assert all(next(a for a in plan['manifest']['assignments'] if a['request_id']==rid)['case_id'].startswith('dev') for rid in calls)
        if mismatch=='semantic':
            from qjig.live_receipts import inspect_campaign_receipts
            refs={k:v['reference'] for k,v in cases.items()}
            reviews={rid:json.loads(payload)['semantic_review_sha256'] for rid,payload in goal._con.execute(
                "SELECT request_id,payload FROM evaluation_campaign_events WHERE plan_id=? AND kind='scored'",('batch',))}
            unanchored=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references=refs)
            assert unanchored['checked']==4 and 'review_anchor_unavailable' in unanchored['issues']
            anchored=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references=refs,expected_review_sha256=reviews)
            assert anchored['checked']==4 and 'review_anchor_unavailable' not in anchored['issues']
            wrong={**reviews,calls[0]:'0'*64}
            assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references=refs,expected_review_sha256=wrong)['status']=='invalid'
            review_db=tmp_path/'runs'/calls[0]/'semantic-review'/'run.sqlite'
            assert review_db.is_file()
            import sqlite3
            with sqlite3.connect(review_db) as con:
                con.execute('DROP TRIGGER event_no_update')
                con.execute("UPDATE events SET data='{}' WHERE kind='review_record'")
            assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references=refs,expected_review_sha256=reviews)['status']=='invalid'
            with pytest.raises(ContractError):
                run_campaign_batch(campaign,tmp_path,design,cases,journal=journal,archive_root=tmp_path/'runs',config=config,
                    want=1,max_bytes=5000,expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=1)
            assert len(calls)==4 and campaign.status()['scored']==4
            return
        from qjig.live_receipts import inspect_campaign_receipts
        report=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()})
        assert report['status']=='incomplete' and report['checked']==4 and report['scored']==4
        assert 'unstarted_assignments' in report['issues'] and 'provider_attribution_not_live' in report['issues']
        assert 'configuration_anchor_unavailable' in report['issues'] and 'run_anchor_unavailable' in report['issues']
        assert 'reference_anchor_unavailable' in report['issues']
        assert 'case_inputs_unavailable' in report['issues']
        assert report['provider_authenticity']=='not_established'
        anchors={rid:json.loads(payload)['run_sha256'] for rid,payload in goal._con.execute(
            "SELECT request_id,payload FROM evaluation_campaign_events WHERE plan_id=? AND kind='scored'",('batch',))}
        reference_anchors={k:reference_digest(v['reference']) for k,v in cases.items()}
        journal_anchors={rid:json.loads(payload)['journal_sha256'] for rid,payload in goal._con.execute(
            "SELECT request_id,payload FROM evaluation_campaign_events WHERE plan_id=? AND kind='scored'",('batch',))
                         if json.loads(payload)['journal_sha256'] is not None}
        anchored=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                           expected_config_sha256=config_hash,expected_run_sha256=anchors,
                                           expected_reference_sha256=reference_anchors,expected_journal_sha256=journal_anchors)
        assert anchored['checked']==4 and 'configuration_anchor_unavailable' not in anchored['issues']
        assert 'run_anchor_unavailable' not in anchored['issues']
        assert 'reference_anchor_unavailable' not in anchored['issues'] and 'journal_anchor_unavailable' not in anchored['issues']
        inputs_checked=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
            expected_config_sha256=config_hash,expected_run_sha256=anchors,expected_reference_sha256=reference_anchors,
            expected_journal_sha256=journal_anchors,case_root=tmp_path,case_inputs=cases)
        assert 'case_inputs_unavailable' not in inputs_checked['issues'] and inputs_checked['checked_cases']==len(cases)
        altered_cases=copy.deepcopy(cases)
        altered_cases['holdout']['reference']['expected_answer']='no'
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
            expected_config_sha256=config_hash,expected_run_sha256=anchors,expected_reference_sha256=reference_anchors,
            expected_journal_sha256=journal_anchors,case_root=tmp_path,case_inputs=altered_cases)['status']=='invalid'
        exposed=copy.deepcopy(cases)
        exposed['holdout']['protected']=list(exposed['holdout']['lock']['sources'])
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
            expected_config_sha256=config_hash,expected_run_sha256=anchors,expected_reference_sha256=reference_anchors,
            expected_journal_sha256=journal_anchors,case_root=tmp_path,case_inputs=exposed)['status']=='invalid'
        wrong_reference=dict(reference_anchors)
        wrong_reference[next(a['case_id'] for a in plan['manifest']['assignments'] if a['request_id']==calls[0])]='0'*64
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                         expected_config_sha256=config_hash,expected_run_sha256=anchors,
                                         expected_reference_sha256=wrong_reference,expected_journal_sha256=journal_anchors)['status']=='invalid'
        assert journal_anchors
        without_journal=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                                  expected_config_sha256=config_hash,expected_run_sha256=anchors,
                                                  expected_reference_sha256=reference_anchors)
        assert 'journal_anchor_unavailable' in without_journal['issues']
        wrong_journal=dict(journal_anchors);wrong_journal[next(iter(wrong_journal))]='0'*64
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                         expected_config_sha256=config_hash,expected_run_sha256=anchors,
                                         expected_reference_sha256=reference_anchors,expected_journal_sha256=wrong_journal)['status']=='invalid'
        wrong=dict(anchors);wrong[calls[0]]='0'*64
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                         expected_config_sha256=config_hash,expected_run_sha256=wrong)['status']=='invalid'
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()},
                                         expected_config_sha256='0'*64,expected_run_sha256=anchors)['status']=='invalid'
        absent=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={})
        assert absent['status']=='incomplete' and 'reference_unavailable' in absent['issues'] and absent['checked']==0
        import sqlite3
        with sqlite3.connect(tmp_path/'runs'/calls[0]/'run.sqlite') as con:
            con.execute('DROP TRIGGER event_no_update')
            seq, original = con.execute("SELECT seq,data FROM events WHERE kind='response' LIMIT 1").fetchone()
            altered=json.loads(original);altered['body']='tampered'
            con.execute('UPDATE events SET data=? WHERE seq=?',(json.dumps(altered),seq))
        altered_report=inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()})
        assert altered_report['status']=='invalid' and 'scored_receipt_invalid' in altered_report['issues']
        with sqlite3.connect(tmp_path/'runs'/calls[0]/'run.sqlite') as con:
            con.execute('UPDATE events SET data=? WHERE seq=?',(original,seq))
        from qjig.evaluation_campaign import run_campaign_assignment
        from qjig.run_archive import RunArchive
        target=next(a for a in plan['manifest']['assignments'] if a['case_id']=='holdout' and a['arm']=='decomposition_only' and a['repeat']==1)
        with RunArchive.open(tmp_path/'runs'/target['request_id']) as archive:
            transport=StandInTransport([]);data=cases['holdout']
            receipt=run_campaign_assignment(campaign,target['request_id'],tmp_path,design,data['lock'],data['reference'],data['protected'],
                applicability_inputs=data['applicability_inputs'],transport=transport,archive=archive,journal=journal,config=config,
                want=1,max_bytes=5000,expected_config_sha256=config_hash)
            assert receipt['status']=='scored' and transport.calls_made==0 and journal.events(target['request_id'])==[]
            assert archive.context()['schema']=='qjig.applicability-deferral.v1'
            assert campaign.status()['scored']==5
            from qjig.evaluation_deferral import verify_applicability_deferral
            assert verify_applicability_deferral(archive,journal,expected_digest=receipt['run_sha256'])['status']=='structurally_verified'
            from qjig.evaluation_scoring import score_reserved_assignment
            scored=score_reserved_assignment(goal,archive,journal,data['reference'],partition='holdout',
                expected_plan_sha256=plan['sha256'],expected_run_sha256=receipt['run_sha256'],
                expected_reference_sha256=reference_digest(data['reference']))
            assert scored['score']['classification']=='unknown_review' and scored['score']['request_answer'] is None
            assert scored['score']['resources']['total']['calls']==0
            original=archive.context();changed=copy.deepcopy(original)
            changed['verdicts'][rev]['combined']='match'
            encoded=json.dumps(changed,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            archive._con.execute('DROP TRIGGER context_no_update')
            archive._con.execute('UPDATE run_context SET data=?,sha256=?',(encoded,hashlib.sha256(encoded.encode()).hexdigest()))
            assert verify_applicability_deferral(archive,journal)['status']=='invalid'
            encoded=json.dumps(original,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            archive._con.execute('UPDATE run_context SET data=?,sha256=?',(encoded,hashlib.sha256(encoded.encode()).hexdigest()))
        third=run_campaign_batch(campaign,tmp_path,design,cases,journal=journal,archive_root=tmp_path/'runs',config=config,
                                 want=1,max_bytes=5000,expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=1)
        assert third['executed']==1 and third['scored']==6 and len(calls)==5
        journal._con.execute('DROP TRIGGER events_no_update')
        journal._con.execute("UPDATE events SET payload='{}' WHERE kind='receipt' AND request_id=?",(calls[0],))
        assert inspect_campaign_receipts(campaign,journal,tmp_path/'runs',references={k:v['reference'] for k,v in cases.items()})['status']=='invalid'
        with pytest.raises(ContractError):
            run_campaign_batch(campaign,tmp_path,design,cases,journal=journal,archive_root=tmp_path/'runs',config=config,
                               want=1,max_bytes=5000,expected_config_sha256=config_hash,transport_factory=transport_for,max_assignments=2)
        assert len(calls)==5
def test_retained_campaign_inspection_refuses_unstarted_work_without_creating_archives(tmp_path):
    from qjig.contracts import Budget
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_budget import build_factorial_allocation, reserve_evaluation_plan
    from qjig.evaluation_campaign import EvaluationCampaign
    from qjig.goal_budget import GoalBudget
    from qjig.journal import Journal
    from qjig.live_receipts import inspect_campaign_receipts

    design = _sample_design()
    digest = validate_evaluation_design(design)
    hashes = {case['id']: hashlib.sha256(case['id'].encode()).hexdigest() for case in design['cases']}
    model = {'id': 'synthetic/model', 'context_length': 10000,
             'top_provider': {'max_completion_tokens': 1000},
             'pricing': {'prompt': '0.000001', 'completion': '0.000002'}}
    spec = {'provider': 'stand-in', 'model': model, 'input_tokens': 100, 'output_tokens': 100,
            'max_price': {'prompt': 2, 'completion': 3}}
    plan = build_factorial_allocation(design, hashes, {k: dict(spec) for k in ('direct', 'planner', 'judge', 'reviewer')},
                                      expected_design_sha256=digest, assignment_secret=b'synthetic-private-test-secret-32-bytes')
    total, per = Budget(800, 200000, 10), Budget(30, 6000, 1)
    allocations = {'development': Budget(200, 50000, 2), 'pilot': Budget(200, 50000, 2),
                   'holdout': Budget(400, 100000, 6)}
    archive_root = tmp_path / 'not-created'
    with GoalBudget.open(tmp_path / 'goal.sqlite', total=total, per_request=per, allocations=allocations) as goal, Journal.open(tmp_path / 'journal.sqlite') as journal:
        reserve_evaluation_plan(goal, 'test', plan, expected_plan_sha256=plan['sha256'])
        campaign = EvaluationCampaign(goal, 'test', expected_plan_sha256=plan['sha256'])
        report = inspect_campaign_receipts(campaign, journal, archive_root, references={})
        assert report['status'] == 'incomplete'
        assert report['assigned'] == 60 and report['scored'] == 0
        assert 'unstarted_assignments' in report['issues']
        assert report['provider_authenticity'] == 'not_established'
        assert not archive_root.exists()


def test_semantic_campaign_configuration_freezes_review_slots_before_claim(tmp_path):
    from qjig.contracts import Budget
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_budget import build_factorial_allocation, reserve_evaluation_plan
    from qjig.evaluation_campaign import EvaluationCampaign
    from qjig.goal_budget import GoalBudget
    design=_sample_design(); design_hash=validate_evaluation_design(design)
    hashes={c['id']:hashlib.sha256(c['id'].encode()).hexdigest() for c in design['cases']}
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    spec={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':100,'max_price':{'prompt':2,'completion':3}}
    config={name:dict(spec) for name in ('direct','planner','judge','reviewer','semantic_reviewer')}
    plan=build_factorial_allocation(design,hashes,config,expected_design_sha256=design_hash,assignment_secret=b'x'*32)
    total=Budget(1000,300000,12); per=Budget(30,6000,1)
    allocations={'development':Budget(250,75000,3),'pilot':Budget(250,75000,3),'holdout':Budget(500,150000,6)}
    metadata={case['id']:hashlib.sha256(('metadata:'+case['id']).encode()).hexdigest() for case in design['cases']}
    with GoalBudget.open(tmp_path/'goal.sqlite',total=total,per_request=per,allocations=allocations) as goal:
        reserve_evaluation_plan(goal,'semantic',plan,expected_plan_sha256=plan['sha256'])
        campaign=EvaluationCampaign(goal,'semantic',expected_plan_sha256=plan['sha256'])
        digest=campaign.freeze_config(config,want=1,max_bytes=5000,case_applicability=metadata,
                                      planner_prompt_version='exception_applicability_v2')
        frozen=campaign.require_config(config,want=1,max_bytes=5000,expected_config_sha256=digest)
        assert frozen['schema']=='qjig.campaign-config.v4'
        assert frozen['stages']['semantic_reviewer']==spec
        assert frozen['planner_prompt_version']=='exception_applicability_v2'
        rid=plan['manifest']['assignments'][0]['request_id']
        campaign.claim(rid)
        assert campaign.status()['in_progress']==[rid]
        altered={**config,'semantic_reviewer':{**spec,'output_tokens':99}}
        with pytest.raises(ContractError):
            campaign.require_config(altered,want=1,max_bytes=5000,expected_config_sha256=digest)
