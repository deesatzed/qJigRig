import pytest
from quix_knowledge.store import open_catalog
from quix_knowledge.records import add_record, add_topic, add_role

def test_finding_evidence_and_unknown_claim():
    db = open_catalog(':memory:')
    db.execute("INSERT INTO sources VALUES ('s','a','hash','text','current')")
    db.execute("INSERT INTO sections VALUES ('p','s','t','text',1,1,0)")
    add_record(db,'r','finding','claim','agent', evidence=['p'])
    add_record(db,'u','finding','other','agent')
    assert db.execute('SELECT section_id FROM evidence WHERE record_id=?',('r',)).fetchone()[0] == 'p'
    assert db.execute('SELECT count(*) FROM evidence WHERE record_id=?',('u',)).fetchone()[0] == 0
    add_topic(db,'p','testing','manual','accepted')
    add_role(db,'p','reviewer','1',0.9,'manual','hash')
    with pytest.raises(ValueError):
        add_record(db,'test','test_result','passed','agent')
