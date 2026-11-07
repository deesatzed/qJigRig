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
