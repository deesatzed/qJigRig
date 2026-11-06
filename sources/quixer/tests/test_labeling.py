import pytest
from quix_knowledge.ingest import ingest
from quix_knowledge.labeling import prepare_review, compile_review
from quix_knowledge.store import open_catalog


def test_review_packet_is_blind_and_compiles_exact_candidate_labels(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry only after a timeout.')
    ingest(db,path)
    tasks=[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'held_out'}]
    packet=prepare_review(db,tasks)
    assert packet['tasks'][0]['labels'] is None
    assert 'score' not in packet['candidates'][0]
    assert 'Retry only after a timeout.' in packet['candidates'][0]['body']
    packet['reviewer']='independent-reviewer'
    packet['tasks'][0]['labels']=[packet['candidates'][0]['id']]
    packet['tasks'][0]['reviewed']=True
    compiled=compile_review(db,packet)
    assert compiled['tasks'][0]['labels'] == [packet['candidates'][0]['id']]
    assert compiled['label_provenance']['reviewer'] == 'independent-reviewer'
    assert compiled['tasks'][0]['reviewed_at'] is None
    assert compiled['label_provenance']['reviewed_without_date']==1


def test_invalid_review_date_is_not_silently_accepted(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'; path.write_text('# Retry\nRetry later.'); ingest(db,path)
    packet=prepare_review(db,[{'id':'q','query':'retry','role':'reviewer','role_version':'1'}]); packet['reviewer']='Reviewer'
    packet['tasks'][0].update(reviewed=True,labels=[packet['candidates'][0]['id']],reviewed_at='2026-02-30')
    with pytest.raises(ValueError,match='review date'): compile_review(db,packet)
    packet['tasks'][0].update(reviewed=False,labels=None,reviewed_at='2026-11-03')
    with pytest.raises(ValueError,match='unreviewed'): compile_review(db,packet)


def test_review_rejects_catalog_change_or_unknown_candidate(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry twice.')
    ingest(db,path)
    packet=prepare_review(db,[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'development'}])
    packet['reviewer']='reviewer'
    packet['tasks'][0].update(labels=['not-a-candidate'],reviewed=True)
    with pytest.raises(ValueError,match='candidate'):
        compile_review(db,packet)
    packet['tasks'][0]['labels']=[packet['candidates'][0]['id']]
    path.write_text('# Retry\nDo not retry.')
    ingest(db,path)
    with pytest.raises(ValueError,match='catalog'):
        compile_review(db,packet)


def test_empty_review_requires_explicit_missing_evidence_reason(tmp_path):
    db=open_catalog(':memory:')
    packet=prepare_review(db,[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'held_out'}])
    packet['reviewer']='reviewer'
    packet['tasks'][0].update(labels=[],reviewed=True)
    with pytest.raises(ValueError,match='reason'):
        compile_review(db,packet)
    packet['tasks'][0]['missing_reason']='Corpus contains no retry material.'
    assert compile_review(db,packet)['tasks'][0]['labels'] == []

def test_reviewed_experiment_binds_labels_to_catalog_snapshot(tmp_path):
    from quix_knowledge.experiment import run_reviewed_experiment
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry twice.')
    ingest(db,path)
    packet=prepare_review(db,[{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'held_out'}])
    packet['reviewer']='reviewer'
    packet['tasks'][0].update(reviewed=True,labels=[packet['candidates'][0]['id']],reviewed_at='2026-11-03')
    compiled=compile_review(db,packet)
    result=run_reviewed_experiment(db,compiled)
    assert result['variants']['baseline']['metrics_by_split']['held_out']['mean_recall'] == 1
    assert result['manifest']['tasks'][0]['reviewed_at']=='2026-11-03'
    assert result['manifest']['label_provenance']['reviewed_with_date']==1
    path.write_text('# Retry\nNever retry.')
    ingest(db,path)
    with pytest.raises(ValueError,match='catalog'):
        run_reviewed_experiment(db,compiled)
