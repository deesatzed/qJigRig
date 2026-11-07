"""Synthetic review records; no provider calls and no independent adjudication."""
import copy
from qjig.contracts import Request


def test_review_record_exact_binding():
    from qjig.programs import make_review, verify_review
    request = Request('r1', 'Can this change be merged?', 'reviewer', '1', 'project')
    binding = {'request': request.to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Tests pass?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': ['rev1:' + 'a' * 64], 'as_of': '2026-11-07', 'entities': [],
               'source_metadata': {'rev1:' + 'a' * 64: {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01', 'effective_end': 'open', 'observed_at': None}},
               'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b' * 64, 'config': {'max_tokens': 100}}}
    reviewer = {'kind': 'synthetic', 'provider': 'stand-in', 'model': 'reviewer', 'prompt_sha256': 'c' * 64, 'config': {'max_tokens': 100}}
    review = make_review(binding, reviewer, {'finding': 'no obvious gap'})
    matched = verify_review(review, binding, reviewer)
    assert matched == {'status': 'matching_unvalidated', 'activation': False, 'semantic_assurance': 'not_assessed'}
    assert review['payload']['assurance'] == 'synthetic_review_unvalidated'
    for change in ('request', 'graph', 'source', 'metadata', 'date', 'role', 'scope', 'planner', 'reviewer'):
        candidate, reviewer_candidate = copy.deepcopy(binding), copy.deepcopy(reviewer)
        if change == 'request': candidate['request']['question'] = 'Different question?'
        if change == 'graph': candidate['plan']['predicates'][0]['question'] = 'Tests passed yesterday?'
        if change == 'source':
            candidate['corpus_revision_ids'] = ['rev1:' + 'd' * 64]
            candidate['source_metadata'] = {'rev1:' + 'd' * 64: candidate['source_metadata']['rev1:' + 'a' * 64]}
        if change == 'metadata': candidate['source_metadata']['rev1:' + 'a' * 64]['effective_start'] = '2026-02-01'
        if change == 'date': candidate['as_of'] = '2026-11-08'
        if change == 'role': candidate['request']['role_version'] = '2'
        if change == 'scope': candidate['request']['scope'] = 'other'
        if change == 'planner': candidate['planner']['config']['max_tokens'] = 101
        if change == 'reviewer': reviewer_candidate['model'] = 'other'
        assert verify_review(review, candidate, reviewer_candidate)['status'] == 'stale'
    changed = copy.deepcopy(review)
    changed['payload']['result']['finding'] = 'changed'
    assert verify_review(changed, binding, reviewer)['status'] == 'invalid'
    incomplete = copy.deepcopy(binding)
    del incomplete['source_metadata']['rev1:' + 'a' * 64]['authority_id']
    assert verify_review(review, incomplete, reviewer)['status'] == 'invalid_candidate'
    binding['request']['question'] = 'mutated later'
    assert review['payload']['binding']['request']['question'] == 'Can this change be merged?'
    ai_reviewer = {**reviewer, 'kind': 'ai', 'provider': 'asserted-provider'}
    assert make_review(review['payload']['binding'], ai_reviewer, {'finding': 'asserted'})['payload']['assurance'] == 'ai_reviewed_unvalidated'


def test_review_record_persistence_and_source_binding(tmp_path):
    import pytest
    from qjig.contracts import ContractError
    from qjig.programs import make_review, verify_review
    from qjig.sources import SourceRevision, decode_source
    from qjig.store import Catalog, CatalogStateChanged
    revision = SourceRevision.create('source.md', 'fixture', decode_source(b'# Rule\nText\n', encoding='utf-8'))
    metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01',
                'effective_end': 'open', 'observed_at': None}
    binding = {'request': Request('r', 'Question?', 'reviewer', '1', 'project').to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Text?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
    reviewer = {'kind': 'synthetic', 'provider': 'stand-in', 'model': 'reviewer', 'prompt_sha256': 'c'*64, 'config': {}}
    record = make_review(binding, reviewer, {'finding': 'fixture'})
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        before_import = catalog.source_state()
        with pytest.raises(ContractError):
            catalog.save_program_review(record, before_import)
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        state = catalog.source_state()
        with pytest.raises(CatalogStateChanged):
            catalog.save_program_review(record, before_import)
        ident = catalog.save_program_review(record, state)
        assert ident == record['sha256'] == catalog.save_program_review(record, state)
    with Catalog.open(path) as catalog:
        restored = catalog.program_review(ident)
        assert restored == record and verify_review(restored, binding, reviewer)['status'] == 'matching_unvalidated'
        changed = copy.deepcopy(binding)
        changed['source_metadata'][revision.revision_id]['scope'] = 'other'
        wrong_record = make_review(changed, reviewer, {'finding': 'fixture'})
        with pytest.raises(ContractError):
            catalog.save_program_review(wrong_record, catalog.source_state())
    import json
    import sqlite3
    with sqlite3.connect(path) as con:
        con.execute('DROP TRIGGER program_reviews_no_update')
        payload = copy.deepcopy(record)
        payload['payload']['result']['finding'] = 'tampered'
        con.execute('UPDATE program_reviews SET record=? WHERE review_id=?', (json.dumps(payload), ident))
    with Catalog.open(path) as catalog:
        with pytest.raises(ContractError, match='integrity'):
            catalog.program_review(ident)


def test_draft_links_only_exact_review_without_activation(tmp_path):
    import pytest
    from qjig.contracts import ContractError
    from qjig.programs import make_draft, make_review
    from qjig.sources import SourceRevision, decode_source
    from qjig.store import Catalog
    revision = SourceRevision.create('source.md', 'fixture', decode_source(b'# Rule\nText\n', encoding='utf-8'))
    metadata = {'scope': 'project', 'authority_id': None, 'entity_keys': [], 'effective_start': '2026-01-01',
                'effective_end': 'open', 'observed_at': None}
    binding = {'request': Request('r', 'Question?', 'reviewer', '1', 'project').to_dict(),
               'plan': {'origin': 'fresh', 'predicates': [{'id': 'p', 'question': 'Text?'}], 'expression': {'ref': 'p'}},
               'corpus_revision_ids': [revision.revision_id], 'source_metadata': {revision.revision_id: metadata},
               'as_of': '2026-11-07', 'entities': [], 'historical_as_known': False,
               'planner': {'provider': 'stand-in', 'model': 'planner', 'prompt_sha256': 'b'*64, 'config': {}}}
    reviewer = {'kind': 'synthetic', 'provider': 'stand-in', 'model': 'reviewer', 'prompt_sha256': 'c'*64, 'config': {}}
    draft = make_draft(binding)
    review = make_review(binding, reviewer, {'assessment': 'no_gap_found'})
    different = copy.deepcopy(binding)
    different['request']['question'] = 'Different question?'
    unrelated_review = make_review(different, reviewer, {'assessment': 'no_gap_found'})
    path = tmp_path / 'catalog.sqlite'
    with Catalog.open(path) as catalog:
        catalog.add_revision(revision)
        catalog.put_metadata_row((revision.revision_id, 'project', None, '[]', '2026-01-01', 'open', None))
        state = catalog.source_state()
        draft_id = catalog.save_program_draft(draft, state)
        assert catalog.program_status(draft_id, binding)['status'] == 'draft'
        review_id = catalog.save_program_review(review, state)
        other_id = catalog.save_program_review(unrelated_review, state)
        with pytest.raises(ContractError):
            catalog.link_program_review(draft_id, other_id, state)
        catalog.link_program_review(draft_id, review_id, state)
        catalog.link_program_review(draft_id, review_id, state)
    with Catalog.open(path) as catalog:
        status = catalog.program_status(draft_id, binding)
        assert status['status'] == 'review_record_linked' and status['review_ids'] == [review_id]
        assert status['activation'] is False and status['semantic_assurance'] == 'not_assessed'
        assert catalog.program_status(draft_id, different)['status'] == 'stale'
        catalog._con.execute('INSERT INTO program_review_links VALUES (?,?)', (draft_id, other_id))
        with pytest.raises(ContractError, match='link invalid'):
            catalog.program_status(draft_id, binding)
