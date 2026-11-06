import pytest
from quix_knowledge.decisions import assess_generated_topic
from quix_knowledge.indexing import index_source, review_generated_entry
from quix_knowledge.ingest import ingest
from quix_knowledge.records import review_topic
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_specific_topic_is_attached_to_generated_span_only(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retries reduce outages.\n\nAudit records preserve evidence.')
    index_source(db,path)
    entry=db.execute('SELECT id,section_id FROM generated_index ORDER BY start_offset LIMIT 1').fetchone()
    assess_generated_topic(db,entry['id'],'resilience',lambda *args:{'outcome':'unclear','provider':'fixture'})
    link=db.execute('SELECT * FROM topic_links WHERE generated_index_id=?',(entry['id'],)).fetchone()
    assert link['section_id'] == entry['section_id']
    assert link['status'] == 'proposed'
    rows=search(db,'resilience',variant='topic',include_proposed=True)
    assert [r['id'] for r in rows] == [entry['id']]
    assert rows[0]['topic_annotations'][0]['status'] == 'proposed'
    review_topic(db,link['id'],'accepted','reviewer')
    review_generated_entry(db,entry['id'],'accepted','reviewer')
    assert search(db,'resilience',variant='topic')[0]['id'] == entry['id']
    assert search(db,'resilience',variant='baseline') == []


def test_stale_generated_span_is_not_sent_to_model(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry is allowed.')
    index_source(db,path)
    entry=db.execute('SELECT id FROM generated_index').fetchone()[0]
    path.write_text('Retry is prohibited.')
    ingest(db,path)
    calls=[]
    with pytest.raises(ValueError):
        assess_generated_topic(db,entry,'resilience',lambda *args:calls.append(args))
    assert calls == []

def test_rejecting_span_stales_its_topic_link(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retries reduce outages.')
    index_source(db,path)
    entry=db.execute('SELECT id FROM generated_index').fetchone()[0]
    assess_generated_topic(db,entry,'resilience',lambda *args:{'outcome':'unclear','provider':'fixture'})
    review_generated_entry(db,entry,'rejected','reviewer')
    assert db.execute('SELECT status FROM topic_links WHERE generated_index_id=?',(entry,)).fetchone()[0] == 'stale'
    assert search(db,'resilience',variant='topic',include_proposed=True) == []

def test_database_rejects_generated_topic_with_wrong_parent(tmp_path):
    import sqlite3
    db=open_catalog(':memory:')
    paths=[tmp_path/'a.txt',tmp_path/'b.txt']
    for path in paths:
        path.write_text('Retry is allowed.')
        index_source(db,path)
    entries=db.execute('SELECT id,section_id FROM generated_index ORDER BY id').fetchall()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO topic_links(section_id,generated_index_id,topic,method,status) VALUES (?,?,?,'manual','proposed')",(entries[1]['section_id'],entries[0]['id'],'retry'))

def test_changed_generated_title_does_not_get_a_stale_topic_decision(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry is allowed.')
    index_source(db,path)
    entry=db.execute('SELECT id FROM generated_index').fetchone()[0]
    def provider(*args):
        db.execute("UPDATE generated_index SET title='Changed' WHERE id=?",(entry,))
        return {'outcome':'supported','provider':'fixture'}
    result=assess_generated_topic(db,entry,'resilience',provider)
    assert result['outcome'] == 'unknown'
    assert db.execute('SELECT count(*) FROM topic_links WHERE generated_index_id=?',(entry,)).fetchone()[0] == 0
