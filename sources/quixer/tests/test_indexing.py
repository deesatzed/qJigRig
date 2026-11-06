from quix_knowledge.indexing import index_source
from quix_knowledge.store import open_catalog


def test_ingestion_gate_and_topic_proposals_remain_provisional(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'guide.md'
    path.write_text('# Retry policy\nRetries are allowed.\n# Backoff\nUse exponential backoff.\n')
    calls = []
    def provider(state, question):
        calls.append(question)
        return {'outcome': 'supported', 'provider': 'fixture'}
    result = index_source(db, path, provider=provider, max_decisions=3)
    assert result['source_id']
    assert result['structure_judgment']['outcome'] == 'supported'
    assert calls == ['structure usable', 'topic supported', 'topic supported']
    links = db.execute('SELECT topic,status FROM topic_links ORDER BY id').fetchall()
    assert [tuple(row) for row in links] == [('Retry policy','proposed'),('Backoff','proposed')]
    assert db.execute('SELECT COUNT(*) FROM decision_receipts').fetchone()[0] == 3


def test_provider_failure_does_not_discard_unstructured_source(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'plain.txt'
    path.write_text('Unheaded searchable document.')
    def fail(*args):
        raise TimeoutError()
    result = index_source(db, path, provider=fail)
    assert result['structure_judgment']['outcome'] == 'unknown'
    assert db.execute('SELECT body FROM sections').fetchone()[0] == 'Unheaded searchable document.'
    assert result['topic_candidates'] == 0

def test_candidates_created_offline_can_be_assessed_later(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'guide.md'
    path.write_text('# Retry policy\nRetry twice.\n')
    index_source(db, path)
    calls = []
    def provider(state, question):
        calls.append(question)
        return {'outcome': 'unclear', 'provider': 'fixture'}
    index_source(db, path, provider=provider, max_decisions=2)
    assert calls == ['structure usable', 'topic supported']
    assert db.execute('SELECT COUNT(*) FROM topic_links').fetchone()[0] == 1

def test_indexing_reports_measured_usage_and_unknown_cost(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetries are bounded.')
    def provider(state,question):
        return {'outcome':'unclear','provider':'fixture','usage':{'cost':0.02,'input_tokens':7}}
    result=index_source(db,path,provider=provider,max_decisions=2)
    assert result['decision_calls'] == 2
    assert result['reported_cost'] == 0.04
    assert result['input_tokens'] == 14
    assert result['elapsed_seconds'] >= 0
    assert len(result['receipt_ids']) == 2

    def missing_usage(state,question):
        return {'outcome':'unclear','provider':'fixture'}
    other=tmp_path/'other.md'
    other.write_text('# Backoff\nUse a delay.')
    result=index_source(db,other,provider=missing_usage,max_decisions=2)
    assert result['reported_cost'] is None
    assert result['input_tokens'] is None

def test_invalid_usage_is_unknown_not_a_measured_cost(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after delay.')
    provider=lambda *args: {'outcome':'unclear','provider':'fixture','usage':{'cost':float('nan'),'input_tokens':-1}}
    result=index_source(db,path,provider=provider,max_decisions=1)
    assert result['reported_cost'] is None
    assert result['input_tokens'] is None

def test_negative_structure_decision_proposes_finer_entries_without_discarding_source(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# General\nRetry after failure.')
    def provider(state,question):
        return {'outcome':'unsuitable' if question == 'structure usable' else 'unclear','provider':'fixture'}
    result=index_source(db,path,provider=provider,max_decisions=3)
    assert result['generated_entries'] == 1
    assert db.execute('SELECT status FROM generated_index').fetchone()[0] == 'proposed'
    assert db.execute('SELECT count(*) FROM sections').fetchone()[0] == 1

def test_source_change_during_structure_decision_does_not_create_stale_proposals(tmp_path):
    from quix_knowledge.ingest import ingest
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    def provider(state,question):
        path.write_text('# Retry\nRetry is prohibited.')
        ingest(db,path)
        return {'outcome':'unsuitable','provider':'fixture'}
    result=index_source(db,path,provider=provider,max_decisions=2)
    assert result['structure_judgment']['outcome'] == 'unknown'
    assert result['decision_calls'] == 1
    assert db.execute('SELECT count(*) FROM generated_index').fetchone()[0] == 0
    assert db.execute('SELECT count(*) FROM topic_links').fetchone()[0] == 0

def test_source_change_during_topic_assessment_does_not_create_stale_link(tmp_path):
    from quix_knowledge.ingest import ingest
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    def provider(state,question):
        if question == 'topic supported':
            path.write_text('# Retry\nRetry is prohibited.')
            ingest(db,path)
        return {'outcome':'unclear','provider':'fixture'}
    result=index_source(db,path,provider=provider,max_decisions=2)
    assert result['status'] == 'source_changed'
    assert db.execute('SELECT count(*) FROM topic_links').fetchone()[0] == 0
    assert db.execute("SELECT outcome FROM decision_receipts ORDER BY id DESC LIMIT 1").fetchone()[0] == 'unknown'
