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
                'resources':{'total':total,'stages':{'direct_initial':dict(total)}}}}
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
    assert result['arms']['combined']['stages']['direct_initial']['calls']==1
    assert result['arms']['combined']['stages']['direct_initial']['cost_usd'] is None
    assert result['arms']['direct_full_evidence']['resources']['cost_usd']==0.1
    assert result['arms']['direct_retrieval']['outcomes']['failed']==1
    changed=copy.deepcopy(reports);changed['direct_retrieval']['scored_assignments'][1]['score']['required_evidence_covered']=True
    with pytest.raises(ContractError): summarize_companion_assertions(changed)
    bad_stages=copy.deepcopy(reports)
    bad_stages['direct_full_evidence']['scored_assignments'][0]['score']['resources']['stages']={}
    with pytest.raises(ContractError): summarize_companion_assertions(bad_stages)
    bad_total=copy.deepcopy(reports)
    bad_total['direct_full_evidence']['scored_assignments'][0]['score']['resources']['total']['input_tokens']=11
    with pytest.raises(ContractError): summarize_companion_assertions(bad_total)
    bad_stage_cost=copy.deepcopy(reports)
    bad_stage_cost['direct_full_evidence']['scored_assignments'][0]['score']['resources']['stages']['direct_initial']['cost_usd']=0.2
    with pytest.raises(ContractError): summarize_companion_assertions(bad_stage_cost)
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
    with pytest.raises(ContractError): group_holdout_interventions(design,{'arms':arms},expected_design_sha256=None)
    with pytest.raises(ContractError): group_holdout_interventions(design,{'arms':arms},expected_design_sha256='0'*64)
    duplicate=copy.deepcopy(arms);duplicate['combined']['cases'].append(row('holdout',1,'failed'))
    with pytest.raises(ContractError):
        group_holdout_interventions(design,{'arms':duplicate},expected_design_sha256=digest)


def test_campaign_companion_preserves_partitions_and_pilot_interventions():
    from test_evaluation import _sample_design
    from qjig.evaluation import validate_evaluation_design
    from qjig.evaluation_companion import summarize_campaign_assertions
    design=_sample_design();digest=validate_evaluation_design(design)
    partitions={f['id']:f['partition'] for f in design['families']}
    total={'calls':1,'input_tokens':10,'output_tokens':5,'cost_usd':0.1,'known_input_tokens':10,
           'known_output_tokens':5,'known_cost_usd':0.1,'unknown_usage_calls':0,'latency_seconds':0.2}
    records=[]
    for case in design['cases']:
        partition=partitions[case['family']]
        for arm in design['arms']:
            for repeat in range(1,design['repeats'][partition]+1):
                records.append({'arm':arm,'repeat':repeat,'score':{'case_id':case['id'],
                    'required_evidence_covered':None,'resources':{'total':dict(total),'stages':{'synthetic':dict(total)}}},
                    'outcome_category':'unknown_assessment','outcome_assurance':'synthetic_unvalidated'})
    result=summarize_campaign_assertions(design,records,expected_design_sha256=digest)
    assert result['assurance']=='caller_asserted_unverified'
    assert result['partitions']['pilot']['arms']['combined']['assignments']==3
    assert result['partitions']['holdout']['arms']['combined']['assignments']==6
    assert result['partitions']['pilot']['arms']['direct_retrieval']['resources']['calls']==3
    assert len(result['interventions']['pilot']['groups']['changed_decisive'])==5
    assert len(result['interventions']['holdout']['groups']['changed_decisive'])==10
    assert all(row['category_changed'] is None for row in result['interventions']['pilot']['groups']['changed_decisive'])
    with pytest.raises(ContractError): summarize_campaign_assertions(design,records[:-1],expected_design_sha256=digest)
    with pytest.raises(ContractError): summarize_campaign_assertions(design,records+[records[0]],expected_design_sha256=digest)
    with pytest.raises(ContractError): summarize_campaign_assertions(design,records,expected_design_sha256=None)
    with pytest.raises(ContractError): summarize_campaign_assertions(design,records,expected_design_sha256='x'*64)
    with pytest.raises(ContractError): summarize_campaign_assertions(design,records,expected_design_sha256='0'*64)


def test_arm_configuration_discloses_access_and_work_differences():
    from qjig.evaluation_companion import summarize_arm_configuration
    model={'id':'synthetic/model','context_length':10000,'top_provider':{'max_completion_tokens':1000},
           'pricing':{'prompt':'0.000001','completion':'0.000002'}}
    stage={'provider':'stand-in','model':model,'input_tokens':100,'output_tokens':50,'max_price':{'prompt':2,'completion':3}}
    config={'schema':'qjig.campaign-config.v8','want':3,'max_bytes':6000,'max_judge_pairs':2,
            'planner_prompt_version':'legacy_v1','stages':{name:dict(stage) for name in
            ('direct','planner','judge','reviewer','semantic_reviewer','outcome_reviewer')}}
    result=summarize_arm_configuration(config)
    assert result['assurance']=='frozen_configuration_assertion'
    assert result['arms']['direct_full_evidence']['source_mode']=='full_source'
    assert result['arms']['direct_full_evidence']['direct_followups']==0
    assert result['arms']['direct_retrieval']['source_mode']=='lexical_retrieval'
    assert result['arms']['retrieval_only']['source_mode']=='catalog_retrieval'
    assert result['arms']['combined']['source_mode']=='catalog_retrieval'
    assert result['arms']['decomposition_only']['source_mode']=='full_source'
    assert result['arms']['combined']['max_judge_pairs']==2
    assert result['arms']['combined']['stages']['planner']['model']=='synthetic/model'
    assert result['arms']['direct_retrieval']['direct_followups']==1
    assert set(result['arms']['combined']['stages'])=={'planner','judge','reviewer','semantic_reviewer','outcome_reviewer'}
    assert result['arms']['combined']['stages']['planner']['input_tokens_assurance']=='configured_not_provider_verified'
    changed=copy.deepcopy(config);del changed['stages']['outcome_reviewer']
    with pytest.raises(ContractError): summarize_arm_configuration(changed)
