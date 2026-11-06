import pytest
from quix_knowledge.ingest import ingest
from quix_knowledge.records import add_topic, review_topic
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_heading_topic_can_be_reviewed_and_used_in_retrieval(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Operations\nRetry after network errors.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_topic(db,section,'resilience','manual')
    link=db.execute('SELECT id FROM topic_links').fetchone()[0]
    assert search(db,'resilience',variant='topic') == []
    review_topic(db,link,'accepted','reviewer')
    assert search(db,'resilience',variant='topic')[0]['id'] == section
    assert db.execute('SELECT reviewer FROM topic_link_reviews').fetchone()[0] == 'reviewer'


def test_stale_topic_proposal_cannot_be_accepted(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Operations\nRetry after errors.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_topic(db,section,'resilience','manual')
    link=db.execute('SELECT id FROM topic_links').fetchone()[0]
    path.write_text('# Operations\nDo not retry.')
    ingest(db,path)
    with pytest.raises(ValueError):
        review_topic(db,link,'accepted','reviewer')

def test_agent_finding_can_receive_decision_assessed_topic(tmp_path):
    from quix_knowledge.records import add_record
    from quix_knowledge.decisions import assess_record_topic
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Operations\nRetry after failure.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry can repeat work','reviewer',evidence=[section])
    result=assess_record_topic(db,'finding','idempotence',lambda *args:{'outcome':'supported','provider':'fixture'})
    assert result['outcome'] == 'supported'
    link=db.execute("SELECT id,status FROM topic_links WHERE record_id='finding'").fetchone()
    assert link['status'] == 'proposed'
    review_topic(db,link['id'],'accepted','reviewer')
    assert search(db,'idempotence',variant='topic')[0]['id'] == 'finding'

def test_stale_finding_is_not_sent_for_topic_assessment(tmp_path):
    from quix_knowledge.records import add_record
    from quix_knowledge.decisions import assess_record_topic
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry is allowed','reviewer',evidence=[section])
    path.write_text('# Retry\nRetry is prohibited.')
    ingest(db,path)
    calls=[]
    with pytest.raises(ValueError):
        assess_record_topic(db,'finding','retry',lambda *args: calls.append(args))
    assert calls == []

def test_record_topic_decision_is_unknown_if_evidence_changes_during_call(tmp_path):
    from quix_knowledge.records import add_record
    from quix_knowledge.decisions import assess_record_topic
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry is allowed','reviewer',evidence=[section])
    def provider(*args):
        path.write_text('# Retry\nRetry is prohibited.')
        ingest(db,path)
        return {'outcome':'supported','provider':'fixture'}
    result=assess_record_topic(db,'finding','retry',provider)
    assert result['outcome'] == 'unknown'
    assert db.execute('SELECT count(*) FROM topic_links').fetchone()[0] == 0
