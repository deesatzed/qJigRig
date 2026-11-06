from quix_knowledge.indexing import map_topics
from quix_knowledge.ingest import ingest
from quix_knowledge.records import add_record
from quix_knowledge.store import open_catalog


def test_bounded_topic_mapping_resumes_without_duplicate_links(tmp_path):
    db=open_catalog(':memory:')
    for name,text in [('a.md','# Retry\nRetry after failures.'),('b.md','# Backup\nKeep a backup.')]:
        path=tmp_path/name
        path.write_text(text)
        ingest(db,path)
    add_record(db,'finding','finding','Retry needs testing','agent')
    calls=[]
    def provider(state,question):
        calls.append(question)
        return {'outcome':'unclear','provider':'fixture','usage':{'cost':0.01,'input_tokens':10}}
    first=map_topics(db,['resilience'],provider,max_decisions=2)
    assert first['decision_calls'] == 2
    assert first['remaining_pairs'] == 1
    assert first['reported_cost'] == 0.02
    second=map_topics(db,['resilience'],provider,max_decisions=2)
    assert second['decision_calls'] == 1
    assert second['remaining_pairs'] == 0
    assert db.execute("SELECT count(*) FROM topic_links WHERE topic='resilience'").fetchone()[0] == 3
    assert all(row[0] == 'proposed' for row in db.execute('SELECT status FROM topic_links'))


def test_topic_mapping_skips_stale_agent_evidence(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry allowed.')
    ingest(db,path)
    sid=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry allowed','agent',evidence=[sid])
    path.write_text('# Retry\nRetry prohibited.')
    ingest(db,path)
    result=map_topics(db,['retry'],lambda *args:{'outcome':'unclear','provider':'fixture'},max_decisions=10)
    assert result['excluded_stale_records'] == 1
    assert db.execute("SELECT count(*) FROM topic_links WHERE record_id='finding'").fetchone()[0] == 0

def test_mapping_can_target_provisional_generated_spans(tmp_path):
    from quix_knowledge.indexing import index_source
    db=open_catalog(':memory:')
    path=tmp_path/'manual.txt'
    path.write_text('Retry reduces outages.\n\nAudit records preserve evidence.')
    index_source(db,path)
    result=map_topics(db,['resilience'],lambda *args:{'outcome':'unclear','provider':'fixture'},max_decisions=10,include_proposed=True)
    assert result['decision_calls'] == 3
    assert db.execute('SELECT count(*) FROM topic_links WHERE generated_index_id IS NOT NULL').fetchone()[0] == 2

def test_mapping_rejects_unbounded_or_duplicate_inputs():
    import pytest
    db=open_catalog(':memory:')
    provider=lambda *args:{'outcome':'unclear','provider':'fixture'}
    with pytest.raises(ValueError):
        map_topics(db,['Retry','retry'],provider,max_decisions=2)
    with pytest.raises(ValueError):
        map_topics(db,['retry'],provider,max_decisions=-1)
