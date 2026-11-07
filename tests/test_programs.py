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
