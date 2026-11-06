import pytest
from quix_knowledge.evaluate import compare_runs

def test_compare_requires_same_queries_and_corpus():
    labels = {'q':['s']}
    runs = {'baseline':{'corpus_revision':'v1','results':{'q':[{'id':'s'}]}},'topic':{'corpus_revision':'v2','results':{'q':[{'id':'s'}]}}}
    with pytest.raises(ValueError,match='corpus'):
        compare_runs(labels,runs)
    runs['topic']['corpus_revision'] = 'v1'
    out = compare_runs(labels,runs)
    assert out['variants']['baseline']['mean_recall'] == 1
    assert out['corpus_revision'] == 'v1'

def test_unknown_labels_not_scored_as_unanswerable():
    from quix_knowledge.evaluate import evaluate
    result = evaluate({'q':None}, {'q':[]})
    assert result['unlabeled'] == 1
    assert result['unanswerable'] == 0
