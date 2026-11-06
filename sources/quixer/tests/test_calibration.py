import pytest
from quix_knowledge.calibration import replay_policy, select_policy


def row(id,split,score,label):
    return {'id':id,'split':split,'probability':score,'label':label,'model':'model-v1','prompt_version':'prompt-v1','question':'relevance'}


def test_threshold_selection_uses_development_only_and_reports_held_out_errors():
    data=[row('d1','development',0.95,True),row('d2','development',0.8,True),row('d3','development',0.1,False),row('d4','development',0.6,True),row('h1','held_out',0.9,False)]
    result=select_policy(data,[(0.2,0.9),(0.65,0.75)],max_error_rate=0.0,min_actions=2,label_provenance='synthetic test')
    assert result['selected'] == {'low':0.2,'high':0.9}
    assert result['development']['acted'] == 2
    assert result['held_out']['false_positive'] == 1
    assert result['held_out']['error_rate'] == 1.0


def test_missing_and_unlabeled_values_are_not_treated_as_negative():
    data=[row('a','development',None,True),row('b','development',0.8,None),row('c','development',0.5,True)]
    report=replay_policy(data,0.2,0.8)
    assert report['unknown'] == 1
    assert report['unlabeled'] == 1
    assert report['deferred'] == 1
    assert report['error_rate'] is None


def test_rejects_leakage_duplicate_ids_and_incompatible_models():
    data=[row('same','development',0.9,True),row('same','held_out',0.1,False)]
    with pytest.raises(ValueError,match='unique'):
        select_policy(data,[(0.2,0.8)],label_provenance='fixture',min_actions=1)
    data=[row('a','development',0.9,True),row('b','held_out',0.1,False)]
    data[1]['model']='other-model'
    with pytest.raises(ValueError,match='model'):
        select_policy(data,[(0.2,0.8)],label_provenance='fixture',min_actions=1)

def test_unstable_option_order_cannot_trigger_an_action():
    item=row('a','development',0.99,True)
    item['stability']={'stable_across_permutations':False,'trials':2}
    report=replay_policy([item],0.2,0.8)
    assert report['unstable'] == 1
    assert report['acted'] == 0
    assert report['error_rate'] is None

def test_no_candidate_meeting_development_constraint_does_not_select_policy():
    data=[row('d','development',0.9,False),row('h','held_out',0.9,True)]
    result=select_policy(data,[(0.2,0.8)],label_provenance='synthetic',min_actions=1)
    assert result['selected'] is None
    assert result['held_out'] is None

def test_required_but_missing_stability_evidence_is_unknown():
    item=row('a','development',0.99,True)
    item['stability_required'] = True
    report=replay_policy([item],0.2,0.8)
    assert report['unknown'] == 1
    assert report['acted'] == 0
