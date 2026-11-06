from quix_knowledge.store import open_catalog
from quix_knowledge.ingest import ingest
from quix_knowledge.records import add_topic, add_role
from quix_knowledge.records import add_record
from quix_knowledge.retrieve import search

def test_topic_and_role_keep_relevant_source(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'doc.md'
    path.write_text('# Interface\nservice protocol\n# Tests\nservice failures\n')
    source = ingest(db,path)
    sections = db.execute('SELECT id FROM sections WHERE source_id=? ORDER BY start_line',(source,)).fetchall()
    add_topic(db,sections[1][0],'resilience','manual','accepted')
    rev = db.execute('SELECT revision FROM sources WHERE id=?',(source,)).fetchone()[0]
    add_role(db,sections[1][0],'reviewer','1',1.0,'manual',rev)
    results = search(db,'service',variant='role',role='reviewer',role_version='1')
    assert len(results) == 2
    assert results[0]['title'] == 'Tests'
    assert results[0]['path'] == str(path.resolve())
    assert search(db,'resilience',variant='topic')[0]['title'] == 'Tests'

def test_agent_claim_is_returned_with_evidence_and_failure_receipt(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'doc.md'
    path.write_text('# Design\nretry behavior\n')
    ingest(db,path)
    sid = db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','retry failure is possible','reviewer',evidence=[sid])
    add_record(db,'unsupported','finding','retry claim','reviewer')
    def broken(state, question):
        raise TimeoutError()
    results = search(db,'retry',variant='decision',provider=broken)
    by_id = {r['id']:r for r in results}
    assert by_id['finding']['evidence'] == [sid]
    assert by_id['unsupported']['unsupported'] is True
    assert len(results) == 3
    assert db.execute('SELECT COUNT(*) FROM decision_receipts').fetchone()[0] == 3

def test_receipt_keeps_probability_and_usage(tmp_path):
    import json
    db = open_catalog(':memory:')
    path = tmp_path/'doc.md'
    path.write_text('# Retry\nretry behavior')
    ingest(db,path)
    provider = lambda s,q: {'outcome':'unclear','provider':'openrouter','model':'m','probability':0.7,'usage':{'cost':0.01}}
    search(db,'retry',variant='decision',provider=provider)
    detail = json.loads(db.execute('SELECT detail FROM decision_receipts').fetchone()[0])
    assert detail['probability'] == 0.7
    assert detail['usage']['cost'] == 0.01

def test_receipt_preserves_local_score_qualifiers(tmp_path):
    import json
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after delay.')
    ingest(db,path)
    def provider(*args):
        return {'outcome':'unclear','provider':'jevedge0','probability':0.8,'probability_status':'conditional_option_score_uncalibrated','legal_mass':0.3,'stability':{'stable_across_permutations':False}}
    search(db,'retry',variant='decision',provider=provider)
    detail=json.loads(db.execute('SELECT detail FROM decision_receipts').fetchone()[0])
    assert detail['probability_status'] == 'conditional_option_score_uncalibrated'
    assert detail['legal_mass'] == 0.3
    assert detail['stability']['stable_across_permutations'] is False

def test_decision_call_count_respects_candidate_budget(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'doc.md'
    path.write_text('# One\nretry\n# Two\nretry\n# Three\nretry\n')
    ingest(db,path)
    calls=[]
    def provider(state,question):
        calls.append(state)
        return {'outcome':'unclear','provider':'fake'}
    assert len(search(db,'retry',variant='decision',provider=provider,limit=1)) == 1
    assert len(calls) == 1

def test_changed_source_marks_finding_evidence_and_annotations_stale(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'spec.md'
    path.write_text('# Retry\nOld retry behavior.')
    ingest(db, path)
    section = db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db, 'finding', 'finding', 'Retry is allowed', 'reviewer', evidence=[section])
    db.execute("INSERT INTO topic_links(record_id,topic,method,status) VALUES ('finding','retry','manual','accepted')")
    db.execute("INSERT INTO role_annotations(record_id,role,role_version,score,method,status) VALUES ('finding','reviewer','1',1,'manual','accepted')")
    db.commit()
    path.write_text('# Retry\nRetry is prohibited.')
    ingest(db, path)
    finding = next(item for item in search(db, 'retry') if item['id'] == 'finding')
    assert finding['evidence_status'] == 'stale'
    assert finding['evidence'] == [section]
    assert db.execute("SELECT status FROM topic_links WHERE record_id='finding'").fetchone()[0] == 'stale'
    assert db.execute("SELECT status FROM role_annotations WHERE record_id='finding'").fetchone()[0] == 'stale'

def test_context_budget_limits_text_without_destroying_anchors(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'doc.md'
    path.write_text('# Retry\nRetry with backoff and jitter.\n# Other\nRetry with timeout.\n')
    ingest(db, path)
    results = search(db, 'retry', context_chars=12)
    assert sum(len(row['body']) for row in results) <= 12
    assert results[0]['context_truncated'] is True
    assert results[0]['start_line'] in (1, 3)
    assert results[0]['path'] == str(path.resolve())

def test_token_budget_uses_supplied_counter_without_splitting_text(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'doc.md'
    path.write_text('# Retry\nretry with very long timeout\n# Logging\nretry trace logging')
    ingest(db,path)
    count = lambda text: len(text.split())
    rows = search(db,'retry',context_tokens=3,count_tokens=count)
    assert sum(count(row['body']) for row in rows) <= 3
    assert rows[0]['context_truncated']
    assert rows[0]['context_token_count'] == count(rows[0]['body'])

def test_token_budget_requires_counter_and_excludes_char_budget():
    import pytest
    db = open_catalog(':memory:')
    with pytest.raises(ValueError):
        search(db,'retry',context_tokens=10)
    with pytest.raises(ValueError):
        search(db,'retry',context_tokens=10,count_tokens=len,context_chars=10)

def test_uncertain_decision_falls_back_to_ungated_baseline(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# True\nretry failure retry failure\n# Other\nretry unrelated content')
    source=ingest(db,path)
    rows=db.execute('SELECT id FROM sections WHERE source_id=? ORDER BY start_line',(source,)).fetchall()
    add_topic(db,rows[1]['id'],'retry failure','manual','accepted')
    def fail(*args):
        raise TimeoutError()
    results=search(db,'retry failure',variant='decision',provider=fail,limit=1)
    assert results[0]['id'] == rows[0]['id']
    assert results[0]['fallback_reason'] == 'decision_unknown'

def test_no_exact_match_broadens_inflections_and_reports_it(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Checks\nDocument failures and retries.')
    ingest(db,path)
    result=search(db,'failure')
    assert len(result) == 1
    assert result[0]['fallback_reason'] == 'lexical_broadened'
    assert 'failures' in result[0]['body']
    assert search(db,'retry')[0]['fallback_reason'] == 'lexical_broadened'

def test_exact_match_is_not_mixed_with_plural_fallback(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# First\nFailure is documented.\n# Second\nFailures are reviewed.')
    ingest(db,path)
    rows=search(db,'failure')
    assert len(rows) == 1
    assert rows[0]['title'] == 'First'

def test_model_fallback_preserves_lexical_broadening_reason(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Checks\nDocument failures.')
    ingest(db,path)
    row=search(db,'failure',variant='decision',provider=lambda *args: {'outcome':'unclear','provider':'fake'})[0]
    assert row['fallback_reason'] == 'decision_unclear'
    assert row['lexical_fallback_reason'] == 'lexical_broadened'

def test_source_changed_during_decision_never_returns_old_section(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    old=ingest(db,path)
    def provider(*args):
        path.write_text('# Retry\nRetry is prohibited.')
        ingest(db,path)
        return {'outcome':'supported','provider':'fixture'}
    rows=search(db,'retry',variant='decision',provider=provider)
    assert rows and all(row['source_id'] != old for row in rows)
    assert rows[0]['fallback_reason'] == 'source_changed'
    assert db.execute('SELECT outcome FROM decision_receipts').fetchone()[0] == 'unknown'

def test_source_removed_during_decision_never_returns_old_section(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    def provider(*args):
        path.unlink()
        ingest(db,path)
        return {'outcome':'supported','provider':'fixture'}
    assert search(db,'retry',variant='decision',provider=provider) == []
    assert db.execute('SELECT outcome FROM decision_receipts').fetchone()[0] == 'unknown'

def test_ambiguous_record_and_section_ids_are_rejected(tmp_path):
    import pytest
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    db.execute("INSERT INTO records(id,kind,body,producer) VALUES (?,'finding','retry','agent')",(section,))
    with pytest.raises(ValueError,match='ambiguous'):
        search(db,'retry')
