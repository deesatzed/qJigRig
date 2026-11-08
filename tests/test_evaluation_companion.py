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
