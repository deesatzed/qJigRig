from quix_knowledge.indexing import index_source
from quix_knowledge.ingest import ingest
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_unheaded_text_gets_source_linked_provisional_topic_entries(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'manual.txt'
    path.write_text('Retries prevent short outages. Use exponential backoff.\n\nAudit logs preserve results. Record every run.\n')
    result = index_source(db,path)
    rows = db.execute('SELECT * FROM generated_index ORDER BY start_offset').fetchall()
    assert len(rows) == 2
    assert result['generated_entries'] == 2
    source = db.execute('SELECT body FROM sections WHERE id=?',(rows[0]['section_id'],)).fetchone()[0]
    assert source[rows[0]['start_offset']:rows[0]['end_offset']] == rows[0]['body']
    assert rows[0]['status'] == 'proposed'
    result_rows = search(db,'audit',variant='topic',include_proposed=True)
    entry = next(r for r in result_rows if r['record_type'] == 'generated_index')
    assert entry['index_status'] == 'proposed'
    assert entry['source_section_id'] == rows[1]['section_id']
    assert not any(r['record_type'] == 'generated_index' for r in search(db,'audit'))


def test_source_update_marks_generated_entries_stale(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'manual.txt'
    path.write_text('Retry is enabled.\n\nAudit is enabled.')
    index_source(db,path)
    path.write_text('Retry is disabled.\n\nAudit is enabled.')
    ingest(db,path)
    assert {r[0] for r in db.execute('SELECT status FROM generated_index')} == {'stale'}

def test_generated_index_decision_is_bounded_and_does_not_approve(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path/'manual.txt'
    path.write_text('Retries prevent outages. More detail.\n\nLogging preserves evidence. More detail.')
    calls=[]
    def provider(state, question):
        calls.append((state,question))
        return {'outcome':'supported','provider':'fixture'}
    result=index_source(db,path,provider=provider,max_decisions=2)
    assert result['decision_calls'] == 2
    assert [q for _,q in calls] == ['structure usable','topic supported']
    assert db.execute('SELECT count(*) FROM generated_index WHERE status=?',('proposed',)).fetchone()[0] == 2
    assert db.execute('SELECT count(*) FROM decision_receipts').fetchone()[0] == 2

def test_long_paragraphs_do_not_lose_non_whitespace(tmp_path):
    db = open_catalog(':memory:')
    path=tmp_path/'long.txt'
    source='word ' * 600
    path.write_text(source)
    index_source(db,path)
    entries=db.execute('SELECT body FROM generated_index ORDER BY start_offset').fetchall()
    assert len(entries) >= 3
    assert ' '.join(r[0] for r in entries).split() == source.split()
    assert all(len(r[0]) <= 1200 for r in entries)

def test_offline_generated_proposals_can_be_assessed_later(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry is limited.\n\nRecord failures.')
    index_source(db,path)
    calls=[]
    def provider(state,question):
        calls.append(question)
        return {'outcome':'unclear','provider':'fixture'}
    index_source(db,path,provider=provider,max_decisions=3)
    assert calls == ['structure usable','topic supported','topic supported']
    assert db.execute('SELECT count(*) FROM generated_index').fetchone()[0] == 2
    assert db.execute('SELECT count(*) FROM decision_receipts').fetchone()[0] == 3

def test_reviewed_index_is_retrievable_by_default_and_audited(tmp_path):
    from quix_knowledge.indexing import review_generated_entry
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry helps outages.\n\nAudit ensures traceability.')
    index_source(db,path)
    entry=db.execute("SELECT id FROM generated_index WHERE title LIKE 'Audit%'").fetchone()[0]
    review_generated_entry(db,entry,'accepted',reviewer='reviewer-1')
    assert db.execute('SELECT reviewer FROM generated_index_reviews').fetchone()[0] == 'reviewer-1'
    assert any(r['id'] == entry for r in search(db,'audit',variant='topic'))

def test_stale_index_entry_cannot_be_accepted(tmp_path):
    import pytest
    from quix_knowledge.indexing import review_generated_entry
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry is allowed.')
    index_source(db,path)
    entry=db.execute('SELECT id FROM generated_index').fetchone()[0]
    path.write_text('Retry is not allowed.')
    ingest(db,path)
    with pytest.raises(ValueError):
        review_generated_entry(db,entry,'accepted',reviewer='reviewer-1')

def test_reverted_source_reproposes_stale_entry_for_fresh_review(tmp_path):
    from quix_knowledge.indexing import review_generated_entry
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry is allowed.')
    index_source(db,path)
    entry=db.execute('SELECT id FROM generated_index').fetchone()[0]
    review_generated_entry(db,entry,'accepted',reviewer='reviewer-1')
    path.write_text('Retry is not allowed.')
    index_source(db,path)
    path.write_text('Retry is allowed.')
    index_source(db,path)
    assert db.execute('SELECT status FROM generated_index WHERE id=?',(entry,)).fetchone()[0] == 'proposed'
    assert db.execute('SELECT count(*) FROM generated_index_reviews WHERE entry_id=?',(entry,)).fetchone()[0] == 1

def test_broad_existing_heading_gets_topic_level_proposals(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.md'
    path.write_text('# Operations\nRetries are bounded.\n\nAudit records track outcomes.\n\nRetention is seven days.')
    result=index_source(db,path)
    sections=db.execute('SELECT * FROM sections').fetchall()
    assert len(sections) == 1
    assert sections[0]['title'] == 'Operations'
    assert sections[0]['generated'] == 0
    entries=db.execute('SELECT title,status FROM generated_index ORDER BY start_offset').fetchall()
    assert result['generated_entries'] == 3
    assert any(row['title'] == 'Audit records track outcomes.' for row in entries)
    assert all(row['status'] == 'proposed' for row in entries)

def test_source_change_during_generated_assessment_never_publishes_entry(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.txt'
    path.write_text('Retry is allowed.')
    def provider(state,question):
        if question == 'topic supported':
            path.write_text('Retry is prohibited.')
            ingest(db,path)
        return {'outcome':'supported','provider':'fixture'}
    result=index_source(db,path,provider=provider,max_decisions=2)
    assert result['status'] == 'source_changed'
    assert db.execute('SELECT count(*) FROM generated_index').fetchone()[0] == 0
    assert db.execute('SELECT outcome FROM decision_receipts ORDER BY id DESC LIMIT 1').fetchone()[0] == 'unknown'
