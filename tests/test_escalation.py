"""Authored stand-in responses exercise orchestration, not model capability."""
import json
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget
from qjig.escalation import escalate_predicate
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.judge import judge_predicate
from qjig.logic import Outcome
from qjig.packets import build_packet
from qjig.providers import RawResponse, StandInTransport
from qjig.retrieval import bm25_candidates
from qjig.sources import SourceRevision, decode_source


def test_standalone_and_escalation_remain_separate(tmp_path):
    quote = 'Refunds are accepted within 14 days of purchase.'
    rev = SourceRevision.create('p/a.md', '/x', decode_source(('# Refunds\n' + quote).encode(), encoding='utf-8'))
    packet = build_packet(bm25_candidates(index_entries(rev), 'refund days'), max_bytes=3000)
    usage = {'prompt_tokens': 20, 'completion_tokens': 5, 'cost_usd': 0.01}
    def side(supported, text=''):
        return RawResponse(200, json.dumps({'supported': supported, 'quote': text, 'reason': 'synthetic'}), usage)
    with Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(Budget(4, 5000, 1), journal, 'r')
        standalone = judge_predicate(ledger, StandInTransport([RawResponse(200, 'bad', usage), side(False)]),
                                     'Is the rule supported?', packet, provider='stand-in', model='m')
        escalated = escalate_predicate(standalone, ledger, StandInTransport([side(True, quote), side(False)]),
                                       'Is the rule supported?', packet, reason='standalone failure', provider='stand-in')
        assert escalated.standalone is standalone and standalone.positive.failure == 'malformed_output'
        assert escalated.result.outcome is Outcome.TRUE and escalated.reason == 'standalone failure'
        assert escalated.model == 'tencent/hy4' and ledger.used_calls() == 4
        intents = [e for e in journal.events('r') if e.kind == 'intent']
        assert [e.stage for e in intents] == ['judge_positive', 'judge_negative', 'escalation_positive', 'escalation_negative']
        assert [e.model for e in intents[-2:]] == ['tencent/hy4', 'tencent/hy4']
        from qjig.costs import summarize_resources
        assert summarize_resources(journal)['stages']['escalation_positive']['cost_usd'] == 0.01
        assert summarize_resources(journal)['stages']['escalation_negative']['cost_usd'] == 0.01


def test_escalation_budget_refusal_preserves_original_and_never_dispatches(tmp_path):
    import pytest
    from qjig.contracts import ContractError
    rev = SourceRevision.create('p/a.md', '/x', decode_source(b'# Refunds\nRefunds apply within 14 days.', encoding='utf-8'))
    packet = build_packet(bm25_candidates(index_entries(rev), 'refund'), max_bytes=3000)
    response = RawResponse(200, json.dumps({'supported': False, 'quote': '', 'reason': 'none'}),
                           {'prompt_tokens': 2, 'completion_tokens': 1, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(Budget(2, 5000, 1), journal, 'r')
        standalone = judge_predicate(ledger, StandInTransport([response, response]), 'Question?', packet,
                                     provider='stand-in', model='m')
        transport = StandInTransport([])
        with pytest.raises(ContractError):
            escalate_predicate(standalone, ledger, transport, 'Question?', packet, reason=' ', provider='stand-in')
        result = escalate_predicate(standalone, ledger, transport, 'Question?', packet,
                                    reason='unknown evidence', provider='stand-in')
        assert result.standalone is standalone and result.result.outcome is Outcome.UNKNOWN
        assert result.result.positive.failure == 'budget_exceeded' and transport.calls_made == 0
        assert ledger.used_calls() == 2


def test_escalation_rejects_a_different_request_ledger_before_call(tmp_path):
    import pytest
    from qjig.contracts import ContractError
    rev = SourceRevision.create('p/a.md', '/x', decode_source(b'# Refunds\nRefunds apply.', encoding='utf-8'))
    packet = build_packet(bm25_candidates(index_entries(rev), 'refund'), max_bytes=3000)
    response = RawResponse(200, json.dumps({'supported': False, 'quote': '', 'reason': 'none'}),
                           {'prompt_tokens': 2, 'completion_tokens': 1, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal:
        original_ledger = BudgetLedger(Budget(4, 5000, 1), journal, 'original')
        standalone = judge_predicate(original_ledger, StandInTransport([response, response]), 'Question?', packet,
                                     provider='stand-in', model='m')
        other = BudgetLedger(Budget(4, 5000, 1), journal, 'different')
        transport = StandInTransport([response, response])
        with pytest.raises(ContractError, match='ledger'):
            escalate_predicate(standalone, other, transport, 'Question?', packet, reason='unknown', provider='stand-in')
        assert transport.calls_made == 0 and journal.events('different') == []


def test_escalation_rejects_changed_question_or_packet_provenance(tmp_path):
    from dataclasses import replace
    import pytest
    from qjig.contracts import ContractError
    rev = SourceRevision.create('p/a.md', '/x', decode_source(b'# Refunds\nRefunds apply.', encoding='utf-8'))
    packet = build_packet(bm25_candidates(index_entries(rev), 'refunds'), max_bytes=3000)
    changed_item = replace(packet.items[0], span=replace(packet.items[0].span, revision_id='different-revision'))
    changed_packet = replace(packet, items=(changed_item,))
    response = RawResponse(200, json.dumps({'supported': False, 'quote': '', 'reason': 'none'}),
                           {'prompt_tokens': 2, 'completion_tokens': 1, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(Budget(4, 5000, 1), journal, 'r')
        standalone = judge_predicate(ledger, StandInTransport([response, response]), 'Question?', packet,
                                     provider='stand-in', model='m')
        transport = StandInTransport([response, response])
        for question, evidence in [('Different question?', packet), ('Question?', changed_packet)]:
            with pytest.raises(ContractError, match='binding'):
                escalate_predicate(standalone, ledger, transport, question, evidence, reason='unknown', provider='stand-in')
        swapped = replace(standalone, positive=standalone.negative, negative=standalone.positive)
        with pytest.raises(ContractError, match='binding'):
            escalate_predicate(swapped, ledger, transport, 'Question?', packet, reason='unknown', provider='stand-in')
        assert transport.calls_made == 0 and ledger.used_calls() == 2


def test_escalation_refuses_changed_applicability_before_dispatch(tmp_path):
    import pytest
    from qjig.applicability import Applicability
    from qjig.contracts import ContractError
    rev = SourceRevision.create('p/a.md', '/x', decode_source(b'# Refunds\nRefunds apply.', encoding='utf-8'))
    packet = build_packet(bm25_candidates(index_entries(rev), 'refunds'), max_bytes=3000)
    response = RawResponse(200, json.dumps({'supported': False, 'quote': '', 'reason': 'none'}),
                           {'prompt_tokens': 2, 'completion_tokens': 1, 'cost_usd': 0.01})
    with Journal.open(tmp_path / 'j.sqlite') as journal:
        ledger = BudgetLedger(Budget(4, 5000, 1), journal, 'r')
        standalone = judge_predicate(ledger, StandInTransport([response, response]), 'Question?', packet,
                                     provider='stand-in', model='m', applicability=lambda _: Applicability.MATCH)
        transport = StandInTransport([response, response])
        with pytest.raises(ContractError, match='binding'):
            escalate_predicate(standalone, ledger, transport, 'Question?', packet, reason='unknown', provider='stand-in',
                               applicability=lambda _: Applicability.NO_MATCH)
        assert transport.calls_made == 0 and ledger.used_calls() == 2
        checked = []
        def same_verdict(revision_id):
            checked.append(revision_id)
            return Applicability.MATCH
        result = escalate_predicate(standalone, ledger, transport, 'Question?', packet, reason='unknown',
                                    provider='stand-in', applicability=same_verdict)
        assert result.standalone is standalone and checked == [rev.revision_id]
        assert transport.calls_made == 2
