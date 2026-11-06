import pytest
from quix_knowledge.ai_review_v2 import build_review_request, validate_review


def test_retrieval_prompt_separates_essential_supporting_and_inspect_only():
    sources=[{'id':'a','body':'Primary evidence.'},{'id':'b','body':'A contradictory claim.'}]
    request=build_review_request('retrieval',{'query':'What is supported?'},sources)
    assert 'essential_ids' in request['system'] and 'inspect_only_ids' in request['system']
    assert 'condition' not in request['input']
    result={'status':'complete','essential_ids':['a'],'supporting_ids':[],'inspect_only_ids':['b'],'explanation':'A is primary; B is a claim.'}
    assert validate_review('retrieval',result,{'a','b'}) == result
    with pytest.raises(ValueError):
        validate_review('retrieval',{**result,'supporting_ids':['a']},{'a','b'})
    with pytest.raises(ValueError):
        validate_review('retrieval',{**result,'essential_ids':['missing']},{'a','b'})


def test_uncertain_review_never_becomes_empty_ground_truth_and_plan_is_judged_as_plan():
    req=build_review_request('plan',{'query':'Implement change','output':'proposed steps'},[{'id':'a','body':'source'}])
    assert 'proposal only' in req['system'].lower()
    assert 'not whether code was implemented' in req['system'].lower()
    result={'status':'uncertain','explanation':'Not enough evidence.'}
    assert validate_review('retrieval',result,{'a'}) == result
    with pytest.raises(ValueError):
        validate_review('retrieval',{'status':'complete','essential_ids':[],'supporting_ids':[],'inspect_only_ids':[],'explanation':'Nothing.'},{'a'})


def test_model_review_keeps_unknown_and_usage_on_invalid_output():
    from quix_knowledge.ai_review_v2 import run_review
    req=build_review_request('retrieval',{'query':'what'},[{'id':'a','body':'fact'}])
    seen=[]
    def transport(request, timeout):
        seen.append(request)
        return {'model':'test/reviewer','usage':{'cost':0.01},'choices':[{'finish_reason':'stop','message':{'content':'{"status":"complete","essential_ids":["unknown"],"supporting_ids":[],"inspect_only_ids":[],"explanation":"x"}'}}]}
    result=run_review(req,kind='retrieval',valid_ids={'a'},api_key='secret',model='test/reviewer',transport=transport)
    assert result['status']=='unknown' and result['usage']['cost']==0.01
    assert 'secret' not in str(result) and 'secret' not in seen[0].full_url
    assert len(result['request_sha256'])==64


def test_model_review_accepts_valid_plan_and_rejects_unexpected_model():
    from quix_knowledge.ai_review_v2 import run_review
    import json
    req=build_review_request('plan',{'query':'Plan X','output':'Propose X'},[{'id':'a','body':'evidence'}])
    verdict={'status':'complete','plan_quality':'adequate','source_support':'supported','missing_requirements':'none','explanation':'Source-backed plan.','source_ids':['a']}
    response={'model':'test/reviewer','usage':{'cost':0.001},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(verdict)}}]}
    result=run_review(req,kind='plan',valid_ids={'a'},api_key='secret',model='test/reviewer',transport=lambda *_:response)
    assert result['status']=='ai_reviewed' and result['verdict']==verdict
    response['model']='other/model'
    assert run_review(req,kind='plan',valid_ids={'a'},api_key='secret',model='test/reviewer',transport=lambda *_:response)['status']=='unknown'


def test_summary_excludes_uncertain_and_keeps_unreviewed_conditions():
    from quix_knowledge.ai_review_v2 import summarize_review
    tasks=[{'id':'t','query':'Plan a change'}]
    packet={'items':[{'blind_id':'b','task_id':'t','task':'Plan a change','output':'proposal'}]}
    key={'conditions':{'b':{'task_id':'t','condition':'baseline'}},'missing':[{'task_id':'t','condition':c,'status':'missing'} for c in ('none','role','switch')]}
    v={'status':'complete','essential_ids':['a'],'supporting_ids':['b'],'inspect_only_ids':[],'explanation':'evidence'}
    rows=[{'kind':'retrieval','id':'t','status':'ai_reviewed','verdict':v}, {'kind':'plan','id':'b','status':'unknown'}]
    comparisons={'baseline':{'queries':{'t':{'results':[{'id':'a'}]}}}}
    result=summarize_review(tasks,packet,key,rows,comparisons)
    assert result['retrieval']['baseline']['mean_essential_recall']==1
    assert result['paired']['t']['baseline']['status']=='unknown'
    assert result['paired']['t']['switch']['status']=='missing'
    assert result['reviewer_type']=='AI; not independently validated'
    with pytest.raises(ValueError): summarize_review(tasks,packet,key,rows+[rows[0]],comparisons)
