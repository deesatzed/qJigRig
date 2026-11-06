import pytest
from quix_knowledge.ingest import ingest
from quix_knowledge.records import add_record, review_record
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_rejected_replacement_does_not_retire_current_record():
    db=open_catalog(':memory:')
    add_record(db,'old','finding','Retry is allowed','agent')
    review_record(db,'old','accepted','reviewer')
    add_record(db,'new','finding','Retry is prohibited','agent',supersedes='old')
    assert db.execute("SELECT status FROM records WHERE id='old'").fetchone()[0] == 'current'
    review_record(db,'new','rejected','reviewer')
    assert db.execute("SELECT status FROM records WHERE id='old'").fetchone()[0] == 'current'
    assert db.execute("SELECT status FROM records WHERE id='new'").fetchone()[0] == 'invalidated'
    assert next(row for row in search(db,'retry') if row['id']=='old')['evidence_status'] == 'unsupported'


def test_accepting_replacement_supersedes_and_stales_old_metadata():
    db=open_catalog(':memory:')
    add_record(db,'old','finding','Retry is allowed','agent')
    review_record(db,'old','accepted','reviewer')
    db.execute("INSERT INTO topic_links(record_id,topic,method,status) VALUES ('old','retry','manual','accepted')")
    db.commit()
    add_record(db,'new','finding','Retry is prohibited','agent',supersedes='old')
    review_record(db,'new','accepted','reviewer')
    assert db.execute("SELECT status FROM records WHERE id='old'").fetchone()[0] == 'superseded'
    assert db.execute("SELECT status FROM records WHERE id='new'").fetchone()[0] == 'current'
    assert db.execute("SELECT status FROM topic_links WHERE record_id='old'").fetchone()[0] == 'stale'

def test_competing_replacements_do_not_both_become_current():
    db=open_catalog(':memory:')
    add_record(db,'old','finding','Original','agent')
    review_record(db,'old','accepted','reviewer')
    add_record(db,'one','finding','First revision','agent',supersedes='old')
    add_record(db,'two','finding','Second revision','agent',supersedes='old')
    review_record(db,'one','accepted','reviewer')
    with pytest.raises(ValueError,match='not current'):
        review_record(db,'two','accepted','reviewer')
    assert db.execute("SELECT status FROM records WHERE id='two'").fetchone()[0] == 'proposed'


def test_stale_evidence_cannot_be_accepted(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    ingest(db,path)
    section=db.execute('SELECT id FROM sections').fetchone()[0]
    add_record(db,'finding','finding','Retry is allowed','agent',evidence=[section])
    path.write_text('# Retry\nRetry is prohibited.')
    ingest(db,path)
    with pytest.raises(ValueError,match='stale'):
        review_record(db,'finding','accepted','reviewer')

def test_empty_record_provenance_or_body_is_rejected():
    db=open_catalog(':memory:')
    with pytest.raises(ValueError):
        add_record(db,'finding','finding',' ','agent')
    with pytest.raises(ValueError):
        add_record(db,'finding','finding','actual claim',' ')
    with pytest.raises(ValueError):
        add_record(db,'finding','test_result','claimed output','agent',output_ref=' ')

def test_test_output_reference_is_visible_but_not_claimed_verified():
    from quix_knowledge.context import build_context_packet
    db=open_catalog(':memory:')
    add_record(db,'test','test_result','retry test passed','agent',output_ref='results.txt')
    row=search(db,'retry')[0]
    assert row['output_ref'] == 'results.txt'
    assert row['output_ref_status'] == 'unverified'
    packet=build_context_packet('retry','reviewer','1',[row],budget=2000,count_tokens=len,tokenizer_name='fixture')
    assert packet['results'][0]['output_ref_status'] == 'unverified'
