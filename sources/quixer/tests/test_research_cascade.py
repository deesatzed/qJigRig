import pytest


def test_escalation_only_for_declared_uncertainty_and_preserves_role_and_sources():
    from quix_knowledge.research_cascade import escalate
    request={'task_id':'t','query':'Resolve conflicting evidence','role':'reviewer','role_version':'1','role_purpose':'Review sources','context':{'catalog_fingerprint':'abc','results':[{'id':'s','revision':'r','body':'fact'}]}}
    seen=[]
    def planner(value):
        seen.append(value)
        return {'output':'proposal','call':{'costUSD':0.02,'usedModel':'tencent/hy4'}}
    assert escalate(request,signal='clear',planner=planner)['status']=='not_needed'
    assert not seen
    result=escalate(request,signal='conflicting_evidence',planner=planner)
    assert result['status']=='completed' and result['output']=='proposal'
    assert seen[0]['role_purpose']=='Review sources' and seen[0]['context']['results'][0]['id']=='s'
    assert 'conflicting_evidence' in seen[0]['query'] and result['call']['costUSD']==0.02


def test_escalation_budget_and_source_failures_are_explicit():
    from quix_knowledge.research_cascade import escalate
    request={'task_id':'t','query':'task','role':'reviewer','role_version':'1','role_purpose':'purpose','context':{'results':[{'id':'s','body':'x'*300}]}}
    called=[]
    def planner(r):called.append(r);return {'status':'agent_failure','call':{'costUSD':0.1}}
    assert escalate(request,signal='decision_unclear',planner=planner,max_input_characters=100)['status']=='input_budget_exceeded'
    assert not called
    result=escalate(request,signal='decision_unclear',planner=planner)
    assert result['status']=='agent_failure' and result['call']['costUSD']==0.1
    with pytest.raises(ValueError):escalate(request,signal='invented',planner=planner)
    def changed():raise ValueError('changed')
    assert escalate(request,signal='decision_unclear',planner=planner,verify_sources=changed)['status']=='source_changed'


def test_post_call_source_change_withholds_proposal_but_retains_receipt():
    from quix_knowledge.research_cascade import escalate
    request={'task_id':'t','query':'task','role':'reviewer','role_version':'1','role_purpose':'purpose','context':{'results':[{'id':'s','body':'fact'}]}}
    calls=[]
    def verify():
        calls.append(True)
        if len(calls)==2: raise ValueError('changed')
    result=escalate(request,signal='synthesis_requested',planner=lambda _: {'output':'proposal','call':{'costUSD':0.01}},verify_sources=verify)
    assert result['status']=='source_changed' and 'output' not in result and result['call']['costUSD']==0.01


def test_combined_context_keeps_baseline_and_marks_failed_stages():
    from quix_knowledge.research_cascade import select_context
    baseline=[{'id':'a','body':'a'},{'id':'b','body':'b'},{'id':'c','body':'c'}]
    rerank={'status':'fallback','candidates':baseline}
    switch={'status':'insufficient_evidence'}
    selected,signals=select_context('combined',baseline,rerank,switch,limit=2)
    assert [x['id'] for x in selected]==['a','b']
    assert set(signals)=={'rerank_unavailable','insufficient_evidence'}
    selected,signals=select_context('combined',baseline,{'status':'ok','candidates':[baseline[2],baseline[0],baseline[1]]},{'status':'complete','rows':[baseline[1]]},limit=3)
    assert [x['id'] for x in selected]==['b','c','a'] and not signals
    assert [x['id'] for x in baseline]==['a','b','c']


def test_missing_rerank_and_untrusted_switch_rows_fall_back():
    from quix_knowledge.research_cascade import select_context
    baseline=[{'id':'a','body':'source'}]
    rows,signals=select_context('combined',baseline,None,{'status':'complete','rows':[{'id':'invented'}]})
    assert rows==baseline and set(signals)=={'rerank_unavailable','insufficient_evidence'}


def test_switch_cannot_invent_body_for_known_source_id():
    from quix_knowledge.research_cascade import select_context
    original=[{'id':'a','body':'source text','revision':'actual'}]
    rows,signals=select_context('reflex',original,None,{'status':'complete','rows':[{'id':'a','body':'invented','revision':'actual'}]})
    assert rows==original and signals==['insufficient_evidence']


def test_rerank_cannot_replace_source_body_or_revision():
    from quix_knowledge.research_cascade import select_context
    original=[{'id':'a','body':'source text','revision':'actual'}]
    rows,signals=select_context('rerank',original,{'status':'ok','candidates':[{'id':'a','body':'invented','revision':'fake','rerank_score':0.9}]},None)
    assert rows[0]['body']=='source text' and rows[0]['revision']=='actual'


def test_planner_preserves_receipt_when_source_changes_after_call():
    from quix_knowledge.research_cascade import propose
    request={'query':'task'};calls=[]
    def verify():
        calls.append(True)
        if len(calls)==2: raise ValueError('changed')
    result=propose(request,planner=lambda _: {'output':'proposal','call':{'costUSD':0.02}},verify_sources=verify)
    assert result['status']=='source_changed' and result['call']['costUSD']==0.02 and 'output' not in result


def test_regular_proposal_records_input_hash_and_respects_character_budget():
    from quix_knowledge.research_cascade import propose
    request={'query':'a task','context':{'body':'evidence'}}
    r=propose(request,planner=lambda _: {'output':'plan'},verify_sources=lambda:None)
    assert r['status']=='completed' and len(r['request_sha256'])==64 and r['request_characters']>0
    r=propose(request,planner=lambda _: {'output':'plan'},verify_sources=lambda:None,max_input_characters=10)
    assert r['status']=='input_budget_exceeded'


def test_hash_check_recognizes_both_source_ids_and_revisions():
    from quix_knowledge.research_cascade import unrecognized_hashes
    source='a'*64;revision='b'*64;other='c'*64
    packet={'results':[{'id':source,'revision':revision,'evidence_sources':[]}]}
    assert unrecognized_hashes('source '+source+' revision '+revision,packet)==[]
    assert unrecognized_hashes('unknown '+other,packet)==[other]
