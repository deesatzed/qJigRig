"""Synthetic review transport; no hosted inference or independent labels."""
import json
import pytest
from qjig.budgets import BudgetLedger
from qjig.contracts import Budget, Request
from qjig.indexing import index_entries
from qjig.journal import Journal
from qjig.packets import build_packet
from qjig.providers import RawResponse, StandInTransport
from qjig.retrieval import bm25_candidates
from qjig.run_archive import RunArchive
from qjig.sources import SourceRevision, decode_source
from qjig.store import Catalog


@pytest.fixture
def review_case():
    revision = SourceRevision.create('source.md', 'fixture', decode_source(b'# Rule\nTests must pass.\n', encoding='utf-8'))
    metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01',
                'effective_end': 'open', 'observed_at': None}
    binding = {'request': Request('r', 'Can this merge?', 'reviewer', '1', 'project').to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Tests pass?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
    packet = build_packet(bm25_candidates(index_entries(revision), 'tests'), max_bytes=3000)
    return revision, binding, packet


def test_budgeted_synthetic_review_is_recorded_without_activation(tmp_path, review_case):
    from qjig.program_review import review_plan
    revision, binding, packet = review_case
    response = RawResponse(200, json.dumps({'assessment': 'no_gap_found', 'reason': 'synthetic'}),
                           {'prompt_tokens': 12, 'completion_tokens': 5, 'cost_usd': 0.01})
    transport = StandInTransport([response])
    with Catalog.open(tmp_path / 'catalog.sqlite') as catalog, Journal.open(tmp_path / 'journal.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        ledger = BudgetLedger(Budget(2, 10000, 1), journal, 'r')
        outcome = review_plan(catalog, ledger, transport, binding, packet, provider='stand-in', model='reviewer', archive=archive)
        assert outcome.status == 'recorded' and outcome.activation is False
        assert outcome.record['payload']['assurance'] == 'synthetic_review_unvalidated'
        assert outcome.record['payload']['result']['assessment'] == 'no_gap_found'
        assert catalog.program_review(outcome.record['sha256']) == outcome.record
        assert outcome.draft_id is not None
        program = catalog.program_status(outcome.draft_id, binding)
        assert program['status'] == 'review_record_linked' and program['review_ids'] == [outcome.record['sha256']]
        assert program['activation'] is False
        request = next(e for e in archive.events() if e['kind'] == 'request')
        assert request['data']['stage'] == 'plan_review'
        assert 'Tests must pass.' in request['data']['prompt'] and 'untrusted' in request['data']['prompt'].lower()
        assert [e.kind for e in journal.events('r')] == ['intent', 'receipt']
        assert ledger.used_calls() == 1 and transport.calls_made == 1
    with Catalog.open(tmp_path / 'catalog.sqlite') as reopened:
        restored = reopened.program_status(outcome.draft_id, binding)
        assert restored['status'] == 'review_record_linked' and not restored['activation']


@pytest.mark.parametrize('mode', ['malformed', 'budget', 'tampered_span', 'wrong_scope'])
def test_review_failures_never_create_a_record_or_activate(tmp_path, review_case, mode):
    from dataclasses import replace
    from qjig.contracts import ContractError
    from qjig.program_review import review_plan
    revision, binding, packet = review_case
    if mode == 'tampered_span':
        item = packet.items[0]
        packet = replace(packet, items=(replace(item, span=replace(item.span, text='forged')),))
    if mode == 'wrong_scope':
        binding['request']['scope'] = 'other'
    response = RawResponse(200, 'not JSON', {'prompt_tokens': 12, 'completion_tokens': 5, 'cost_usd': 0.01})
    transport = StandInTransport([response])
    with Catalog.open(tmp_path / 'catalog.sqlite') as catalog, Journal.open(tmp_path / 'journal.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        ledger = BudgetLedger(Budget(0 if mode == 'budget' else 2, 10000, 1), journal, 'r')
        if mode in ('tampered_span', 'wrong_scope'):
            with pytest.raises(ContractError):
                review_plan(catalog, ledger, transport, binding, packet, provider='stand-in', model='reviewer', archive=archive)
            assert journal.events('r') == [] and transport.calls_made == 0
        else:
            outcome = review_plan(catalog, ledger, transport, binding, packet, provider='stand-in', model='reviewer', archive=archive)
            assert outcome.status == 'unavailable' and outcome.record is None and outcome.activation is False
            assert outcome.failure == ('budget_exceeded' if mode == 'budget' else 'malformed_output')
            assert transport.calls_made == (0 if mode == 'budget' else 1)
        assert catalog._con.execute('SELECT COUNT(*) FROM program_reviews').fetchone()[0] == 0


def test_review_does_not_store_after_source_state_changes(tmp_path, review_case):
    from qjig.program_review import review_plan
    revision, binding, packet = review_case
    response = RawResponse(200, json.dumps({'assessment': 'no_gap_found', 'reason': 'fixture'}),
                           {'prompt_tokens': 12, 'completion_tokens': 5, 'cost_usd': 0.01})
    with Catalog.open(tmp_path / 'catalog.sqlite') as catalog, Journal.open(tmp_path / 'journal.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        class ChangingTransport(StandInTransport):
            def send(self, request):
                other = SourceRevision.create('other.md', 'fixture', decode_source(b'new source', encoding='utf-8'))
                catalog.add_revision(other)
                return super().send(request)
        transport = ChangingTransport([response])
        ledger = BudgetLedger(Budget(2, 10000, 1), journal, 'r')
        outcome = review_plan(catalog, ledger, transport, binding, packet, provider='stand-in', model='reviewer', archive=archive)
        assert outcome.status == 'unavailable' and outcome.failure == 'source_changed'
        assert outcome.record is None and outcome.call_id is not None and outcome.activation is False
        assert ledger.used_calls() == 1 and transport.calls_made == 1
        assert catalog._con.execute('SELECT COUNT(*) FROM program_reviews').fetchone()[0] == 0


def test_reviewed_draft_transaction_rolls_back_on_link_failure(tmp_path, review_case):
    from qjig.program_review import review_plan
    revision, binding, packet = review_case
    response = RawResponse(200, json.dumps({'assessment': 'uncertain', 'reason': 'fixture'}),
                           {'prompt_tokens': 12, 'completion_tokens': 5, 'cost_usd': 0.01})
    with Catalog.open(tmp_path / 'catalog.sqlite') as catalog, Journal.open(tmp_path / 'journal.sqlite') as journal, RunArchive.open(tmp_path / 'archive') as archive:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        catalog._con.execute("CREATE TRIGGER fixture_link_failure BEFORE INSERT ON program_review_links BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        transport = StandInTransport([response])
        outcome = review_plan(catalog, BudgetLedger(Budget(2, 10000, 1), journal, 'r'), transport, binding, packet,
                              provider='stand-in', model='reviewer', archive=archive)
        assert outcome.status == 'unavailable' and outcome.failure == 'storage_failure'
        assert outcome.record is None and outcome.draft_id is None and not outcome.activation
        assert transport.calls_made == 1 and [event.kind for event in journal.events('r')] == ['intent', 'receipt']
        for table in ('program_drafts', 'program_reviews', 'program_review_links'):
            assert catalog._con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
