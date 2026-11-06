from quix_knowledge.decisions import judge
from quix_knowledge.decisions import assess_topic
from quix_knowledge.store import open_catalog

def test_failure_is_unknown_and_malformed_is_unknown():
    def bad(state, question):
        raise TimeoutError('timeout')
    assert judge(bad,{},'relevant')['outcome'] == 'unknown'
    assert judge(lambda state,question: {'outcome':'invented'}, {},'relevant')['outcome'] == 'unknown'
    assert judge(lambda state,question: {'outcome':'supported','provider':'fake'}, {},'relevant')['outcome'] == 'supported'

def test_topic_decisions_preserve_uncertainty():
    db = open_catalog(':memory:')
    db.execute("INSERT INTO sources VALUES ('s','a','h','text','current')")
    db.execute("INSERT INTO sections VALUES ('p','s','title','text',1,1,0)")
    assess_topic(db,'p','security',lambda s,q: {'outcome':'unclear','provider':'fake'})
    assert db.execute('SELECT status FROM topic_links').fetchone()[0] == 'proposed'
    assert db.execute('SELECT outcome FROM decision_receipts').fetchone()[0] == 'unclear'
