"""Companion summaries retain unknowns and avoid double-counting paired arms."""
import copy
import pytest
from qjig.contracts import ContractError


def test_companion_counts_unique_arms_and_preserves_unknown_usage():
    from qjig.evaluation_companion import summarize_companion_assertions
    def record(arm, cost, covered):
        total={'calls':1,'input_tokens':10,'output_tokens':5,'cost_usd':cost,
               'known_input_tokens':10,'known_output_tokens':5,'known_cost_usd':cost if cost is not None else 0,
               'unknown_usage_calls':int(cost is None),'latency_seconds':0.2}
        return {'arm':arm,'repeat':1,'score':{'case_id':'case','required_evidence_covered':covered,
                'resources':{'total':total,'stages':{}}}}
    combined=record('combined',None,None)
    def report(baseline, category):
        return {'scored_assignments':[record(baseline,0.1,True),copy.deepcopy(combined)],
                'outcome_reviews':{'records':[{'case_id':'case','repeat':1,'arm':baseline,'category':category,'assurance':'synthetic_unvalidated'},
                    {'case_id':'case','repeat':1,'arm':'combined','category':'unknown_assessment','assurance':'synthetic_unvalidated'}]}}
    reports={'direct_full_evidence':report('direct_full_evidence','supported_match'),
             'direct_retrieval':report('direct_retrieval','failed')}
    result=summarize_companion_assertions(reports)
    assert result['assurance']=='caller_asserted_unverified'
    assert result['arms']['combined']['assignments']==1
    assert result['arms']['combined']['outcomes']['unknown_assessment']==1
    assert result['arms']['combined']['resources']['calls']==1
    assert result['arms']['combined']['resources']['cost_usd'] is None
    assert result['arms']['direct_full_evidence']['resources']['cost_usd']==0.1
    assert result['arms']['direct_retrieval']['outcomes']['failed']==1
    changed=copy.deepcopy(reports);changed['direct_retrieval']['scored_assignments'][1]['score']['required_evidence_covered']=True
    with pytest.raises(ContractError): summarize_companion_assertions(changed)
    missing=copy.deepcopy(reports);missing['direct_retrieval']['scored_assignments'].pop(1);missing['direct_retrieval']['outcome_reviews']['records'].pop(1)
    with pytest.raises(ContractError): summarize_companion_assertions(missing)
    def ablation(arm):
        return {'scored_assignments':[record('direct_retrieval',0.1,True),record(arm,0.2,False)],
                'outcome_reviews':{'records':[{'case_id':'case','repeat':1,'arm':'direct_retrieval','category':'failed','assurance':'synthetic_unvalidated'},
                    {'case_id':'case','repeat':1,'arm':arm,'category':'reference_misaligned','assurance':'synthetic_unvalidated'}]}}
    extras={arm:ablation(arm) for arm in ('retrieval_only','decomposition_only')}
    full=summarize_companion_assertions(reports,additional_reports=extras)
    assert full['scope']=='holdout_five_arms_only' and len(full['arms'])==5
    assert full['arms']['direct_retrieval']['assignments']==1 and full['arms']['direct_retrieval']['resources']['calls']==1
    assert full['arms']['retrieval_only']['resources']['cost_usd']==0.2
    assert full['arms']['decomposition_only']['outcomes']['reference_misaligned']==1
    with pytest.raises(ContractError): summarize_companion_assertions(reports,additional_reports={'retrieval_only':extras['retrieval_only']})
    changed=copy.deepcopy(extras);changed['retrieval_only']['scored_assignments'][0]['score']['required_evidence_covered']=False
    with pytest.raises(ContractError): summarize_companion_assertions(reports,additional_reports=changed)


def test_group_holdout_interventions_preserves_missing_and_unknown():
    from test_evaluation import _sample_design
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_companion import group_holdout_interventions
    design=_sample_design();digest=validate_evaluation_design(design)
    def row(case,repeat,category):
        return {'case_id':case,'repeat':repeat,'category':category,'review_assurance':'synthetic_unvalidated',
                'evidence_covered':None,'request_status':'deferred','classification':'unknown_review'}
    arms={arm:{'cases':[row('holdout',1,'supported_match'),row('holdout-changed',1,'failed'),
                        row('holdout',2,'unknown_assessment')]} for arm in design['arms']}
    result=group_holdout_interventions(design,{'arms':arms},expected_design_sha256=digest)
    assert result['assurance']=='caller_asserted_unverified'
    changed=result['groups']['changed_decisive']
    assert len(changed)==10
    first=next(r for r in changed if r['arm']=='combined' and r['repeat']==1)
    assert first['parent']['category']=='supported_match' and first['intervention']['category']=='failed'
    assert first['category_changed'] is True
    missing=next(r for r in changed if r['arm']=='combined' and r['repeat']==2)
    assert missing['intervention'] is None and missing['category_changed'] is None
    assert result['groups']['missing_decisive']==[] and result['groups']['irrelevant_change']==[]
    duplicate=copy.deepcopy(arms);duplicate['combined']['cases'].append(row('holdout',1,'failed'))
    with pytest.raises(ContractError):
        group_holdout_interventions(design,{'arms':duplicate},expected_design_sha256=digest)
