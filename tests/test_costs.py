"""Synthetic journal events only; no inference or provider cost assumptions."""
from qjig.journal import Journal, run_journaled
from qjig.costs import summarize_resources


def test_resource_report_preserves_failed_and_unknown_usage(tmp_path):
    with Journal.open(tmp_path / 'journal.sqlite', clock=iter([1, 3, 4, 5, 6, 9]).__next__) as journal:
        run_journaled(journal, request_id='r', stage='planner', provider='stand-in', model='m', input_sha256='a'*64,
                      call=lambda: ('ok', {'prompt_tokens': 20, 'completion_tokens': 10, 'cost_usd': 0.1}))
        try:
            run_journaled(journal, request_id='r', stage='judge', provider='stand-in', model='m', input_sha256='b'*64,
                          call=lambda: (_ for _ in ()).throw(ValueError('synthetic failure')))
        except ValueError:
            pass
        run_journaled(journal, request_id='r', stage='escalation', provider='stand-in', model='hy4', input_sha256='c'*64,
                      call=lambda: ('ok', {'prompt_tokens': 7, 'completion_tokens': 3, 'cost_usd': None}))
        report = summarize_resources(journal)
        assert report['total'] == {'calls': 3, 'input_tokens': None, 'output_tokens': None, 'cost_usd': None,
                                   'known_input_tokens': 27, 'known_output_tokens': 13, 'known_cost_usd': 0.1,
                                   'unknown_usage_calls': 2, 'latency_seconds': 6}
        assert report['stages']['judge']['calls'] == 1
        assert report['stages']['judge']['cost_usd'] is None
        assert report['stages']['escalation']['calls'] == 1
        assert report['stages']['planner']['cost_usd'] == 0.1


def test_incomplete_calls_and_malformed_sequences_do_not_create_known_usage(tmp_path):
    import pytest
    from qjig.contracts import ContractError

    with Journal.open(tmp_path / 'journal.sqlite', clock=lambda: 1) as journal:
        intent = journal.record_intent(request_id='one', stage='judge', provider='stand-in', model='m', input_sha256='a'*64)
        report = summarize_resources(journal)
        assert report['total']['calls'] == 1
        assert report['total']['cost_usd'] is None and report['total']['latency_seconds'] is None
        journal.record_terminal(intent, 'receipt', {'usage': {'prompt_tokens': True, 'completion_tokens': 0, 'cost_usd': 0}})
        report = summarize_resources(journal)
        assert report['total']['input_tokens'] is None and report['total']['output_tokens'] == 0
        assert report['total']['cost_usd'] == 0 and report['total']['unknown_usage_calls'] == 1
        journal.record_terminal(intent, 'receipt', {'usage': {}})
        with pytest.raises(ContractError, match='duplicate'):
            summarize_resources(journal)


def test_resource_report_includes_separate_requests_and_uncertain_calls(tmp_path):
    from qjig.journal import UncertainOutcome
    import pytest
    with Journal.open(tmp_path / 'journal.sqlite', clock=lambda: 10) as journal:
        for request in ('one', 'two'):
            with pytest.raises(UncertainOutcome):
                run_journaled(journal, request_id=request, stage='judge', provider='stand-in', model='m', input_sha256='a'*64,
                              call=lambda: (_ for _ in ()).throw(UncertainOutcome('synthetic uncertainty')))
        report = summarize_resources(journal)
        assert report['total']['calls'] == 2 and report['total']['unknown_usage_calls'] == 2
        assert report['total']['cost_usd'] is None and report['stages']['judge']['calls'] == 2
        only_one = summarize_resources(journal,request_id='one')
        assert only_one['total']['calls'] == 1 and only_one['total']['unknown_usage_calls'] == 1
        assert only_one['total']['cost_usd'] is None
