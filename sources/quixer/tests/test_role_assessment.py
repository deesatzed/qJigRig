from quix_knowledge.decisions import assess_role
from quix_knowledge.ingest import ingest
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_role_assessment_records_provisional_score_and_provenance(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nReview retry failures.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    def provider(state,question):
        assert question == 'role usefulness'
        return {'outcome':'unclear','provider':'fixture','model':'model-v1','probability':0.8,'usage':{'cost':0.01}}
    result=assess_role(db,section,'reviewer','1','Find implementation defects',provider)
    assert result['outcome'] == 'unclear'
    annotation=db.execute('SELECT * FROM role_annotations').fetchone()
    assert annotation['status'] == 'proposed'
    assert annotation['model'] == 'model-v1'
    assert annotation['score'] == 0.8
    row=search(db,'retry',variant='role',role='reviewer',role_version='1')[0]
    assert row['role_score_status'] == 'proposed'
    assert row['role_score'] == 0.8


def test_failed_role_assessment_records_unknown_without_inventing_score(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after failure.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    def fail(*args):
        raise TimeoutError()
    assert assess_role(db,section,'reviewer','1','Find defects',fail)['outcome'] == 'unknown'
    assert db.execute('SELECT count(*) FROM role_annotations').fetchone()[0] == 0
    assert db.execute('SELECT outcome FROM decision_receipts').fetchone()[0] == 'unknown'

def test_role_score_is_version_specific_and_stales_with_source(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nReview retry failures.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    provider=lambda *args: {'outcome':'unclear','provider':'fixture','probability':0.8}
    assess_role(db,section,'reviewer','1','Find defects',provider)
    assert search(db,'retry',variant='role',role='reviewer',role_version='2')[0]['role_score'] is None
    path.write_text('# Retry\nReview recovery behavior.')
    ingest(db,path)
    assert db.execute('SELECT status FROM role_annotations').fetchone()[0] == 'stale'
    assert search(db,'retry',variant='role',role='reviewer',role_version='1')[0]['role_score'] is None

def test_generated_topics_have_distinct_role_scores(tmp_path):
    from quix_knowledge.indexing import index_source
    db=open_catalog(':memory:')
    path=tmp_path/'doc.txt'
    path.write_text('Retry tests expose defects.\n\nRetry style improves prose.')
    index_source(db,path)
    entries=db.execute('SELECT id,title FROM generated_index ORDER BY start_offset').fetchall()
    def provider(state,question):
        value=0.9 if 'tests' in state['text'] else 0.1
        return {'outcome':'unclear','provider':'fixture','model':'m','probability':value}
    for entry in entries:
        assess_role(db,entry['id'],'reviewer','1','Find defects',provider)
    rows=search(db,'retry',variant='role',role='reviewer',role_version='1',include_proposed=True)
    generated=[r for r in rows if r['record_type']=='generated_index']
    by_id={r['id']:r for r in generated}
    assert by_id[entries[0]['id']]['role_score'] == 0.9
    assert by_id[entries[1]['id']]['role_score'] == 0.1
    assert by_id[entries[0]['id']]['role_score_scope'] == 'generated_index'
    path.write_text('Retry tests changed.')
    ingest(db,path)
    assert {r[0] for r in db.execute('SELECT status FROM index_role_annotations')} == {'stale'}

def test_source_changed_while_role_model_runs_does_not_create_annotation(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    def provider(*args):
        path.write_text('# Retry\nRetry is prohibited.')
        ingest(db,path)
        return {'outcome':'unclear','provider':'fixture','probability':0.9}
    result=assess_role(db,section,'reviewer','1','Find defects',provider)
    assert result['outcome'] == 'unknown'
    assert db.execute('SELECT count(*) FROM role_annotations').fetchone()[0] == 0
    assert db.execute('SELECT outcome FROM decision_receipts').fetchone()[0] == 'unknown'

def test_agent_record_can_receive_role_score_without_becoming_verified(tmp_path):
    from quix_knowledge.records import add_record
    db=open_catalog(':memory:')
    add_record(db,'finding','finding','Retry risk exists','reviewer')
    provider=lambda *args: {'outcome':'unclear','provider':'fixture','probability':0.7}
    assess_role(db,'finding','implementer','1','Implement retry behavior',provider)
    row=next(r for r in search(db,'retry',variant='role',role='implementer',role_version='1') if r['id']=='finding')
    assert row['role_score'] == 0.7
    assert row['role_score_scope'] == 'record'
    assert row['evidence_status'] == 'unsupported'

def test_stale_agent_record_role_assessment_makes_no_model_call(tmp_path):
    from quix_knowledge.records import add_record
    import pytest
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry allowed','reviewer',evidence=[section])
    path.write_text('# Retry\nRetry prohibited.')
    ingest(db,path)
    calls=[]
    with pytest.raises(ValueError):
        assess_role(db,'finding','reviewer','1','Find defects',lambda *args:calls.append(args))
    assert calls == []
