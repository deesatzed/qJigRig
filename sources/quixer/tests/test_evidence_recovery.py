import copy
import hashlib
from pathlib import Path


def section(path, body):
    path.write_text(body,encoding='utf-8')
    return {'id':path.stem,'record_type':'section','title':path.stem,'body':body,'path':str(path),'revision':hashlib.sha256(body.encode()).hexdigest(),'source_status':'current','start_line':1,'end_line':len(body.splitlines())}


def test_recovery_replaces_unsupported_and_stale_records_without_mutation(tmp_path):
    from quix_knowledge.evidence_recovery import recover_evidence
    good=section(tmp_path/'good.txt','Current evidence.')
    unsupported={'id':'claim','record_type':'agent_record','title':'finding','body':'unsupported','source_status':'proposed','unsupported':True,'evidence_status':'unsupported','evidence':[],'evidence_sources':[]}
    stale={'id':'old','record_type':'agent_record','title':'finding','body':'old claim','source_status':'proposed','unsupported':False,'evidence_status':'stale','evidence':['s'],'evidence_sources':[]}
    candidates=[unsupported,stale,good]; before=copy.deepcopy(candidates)
    result=recover_evidence(candidates,[],limit=1)
    assert result['status']=='recovered' and [x['id'] for x in result['results']]==['good']
    assert [(x['id'],x['reason']) for x in result['excluded']]==[('claim','unsupported_evidence'),('old','stale_evidence')]
    assert candidates==before


def test_recovery_skips_missing_changed_sources_and_reports_no_evidence(tmp_path):
    from quix_knowledge.evidence_recovery import recover_evidence
    missing=section(tmp_path/'missing.txt','original');Path(missing['path']).unlink()
    changed=section(tmp_path/'changed.txt','original');Path(changed['path']).write_text('changed')
    result=recover_evidence([missing,changed],[],limit=2)
    assert result['status']=='insufficient_evidence' and result['results']==[]
    assert [x['reason'] for x in result['excluded']]==['source_unavailable','source_changed']


def test_recovery_checks_line_spans_and_retains_valid_evidence_sources(tmp_path):
    from quix_knowledge.evidence_recovery import recover_evidence
    good=section(tmp_path/'source.txt','first\nsecond')
    forged={**good,'id':'forged','body':'invented'}
    source={'section_id':good['id'],'path':good['path'],'revision':good['revision'],'source_status':'current','start_line':1,'end_line':2}
    record={'id':'finding','record_type':'agent_record','title':'finding','body':'claim','source_status':'proposed','unsupported':False,'evidence_status':'current','evidence':[good['id']],'evidence_sources':[source]}
    result=recover_evidence([forged,record],[good],limit=2)
    assert result['excluded'][0]['reason']=='source_span_mismatch'
    assert [x['id'] for x in result['results']]==['finding','source']
    assert result['results'][0]['body']=='claim'


def test_recovery_notice_reaches_planner_and_packet_task_stays_aligned():
    from quix_knowledge.evidence_recovery import add_recovery_notice
    request={'query':'Explain retry','context':{'task':'Explain retry','results':[{'id':'good'}]}}
    result=add_recovery_notice(request,{'status':'recovered','excluded':[{'id':'claim','reason':'unsupported_evidence'}],'shortfall_count':0})
    assert 'claim' in result['query'] and 'unsupported_evidence' in result['query']
    assert result['context']['task']==result['query']
    assert request['query']=='Explain retry'


def test_recovery_notice_marks_incomplete_context_even_without_rejections():
    from quix_knowledge.evidence_recovery import add_recovery_notice
    req={'query':'task','context':{'task':'task','results':[{'id':'good'}]}}
    result=add_recovery_notice(req,{'status':'ok','excluded':[],'shortfall_count':2})
    assert '2' in result['query'] and 'fewer' in result['query'].lower()
    assert result['context']['task']==result['query']


def test_recovery_builds_packet_and_returns_no_planner_request_when_empty(tmp_path):
    from quix_knowledge.evidence_recovery import prepare_recovery_request
    good=section(tmp_path/'good.txt','Useful source.')
    bad={'id':'claim','record_type':'agent_record','title':'finding','body':'unsupported','source_status':'proposed','unsupported':True,'evidence_status':'unsupported','evidence':[],'evidence_sources':[]}
    task={'id':'t','query':'Find sources','role':'reviewer','role_version':'1'}
    result=prepare_recovery_request(task,[bad],[good],fingerprint='catalog',limit=1,body_characters=100,role_purpose='Review sources')
    assert result['status']=='recovered' and result['request']['context']['results'][0]['id']=='good'
    assert 'unsupported_evidence' in result['request']['query'] and result['request']['context']['task']==result['request']['query']
    empty=prepare_recovery_request(task,[bad],[],fingerprint='catalog',limit=1,body_characters=100,role_purpose='Review sources')
    assert empty['status']=='insufficient_evidence' and empty['request'] is None


def test_recovery_notice_is_delivered_across_planner_process_boundary(tmp_path):
    import json,sys
    from quix_knowledge.agent_process import PlannerProcess
    from quix_knowledge.evidence_recovery import prepare_recovery_request
    good=section(tmp_path/'good.txt','Useful evidence.')
    bad={'id':'claim','record_type':'agent_record','title':'finding','body':'unsupported','source_status':'proposed','unsupported':True,'evidence_status':'unsupported','evidence':[],'evidence_sources':[]}
    task={'id':'t','query':'Find source','role':'reviewer','role_version':'1'}
    prepared=prepare_recovery_request(task,[bad],[good],fingerprint='fp',limit=1,body_characters=100,role_purpose='Review sources')
    script=tmp_path/'agent.py'
    script.write_text('import json,sys\nr=json.load(sys.stdin)\nassert r["task"]==r["packet"]["task"]\nprint(json.dumps({"status":"completed","proposal":{"task":r["task"]}}))\n')
    process=PlannerProcess([sys.executable,str(script)],api_key='fake',model='fixture',role_definitions={'reviewer':{'version':'1','purpose':'Review sources'}})
    result=process(prepared['request'])
    assert 'claim (unsupported_evidence)' in json.loads(result['output'])['task']


def test_recovery_with_no_packet_space_does_not_send_empty_context(tmp_path):
    from quix_knowledge.evidence_recovery import prepare_recovery_request
    good=section(tmp_path/'good.txt','Useful.');good['title']='x'*12000
    task={'id':'t','query':'task','role':'reviewer','role_version':'1'}
    result=prepare_recovery_request(task,[good],[],fingerprint='fp',limit=1,body_characters=100,role_purpose='Review')
    assert result['status']=='insufficient_evidence' and result['request'] is None
    assert result['recovery']['packet_omitted_count']==1


def test_recovery_records_pdf_and_agent_claim_verification_limits(tmp_path):
    from quix_knowledge.evidence_recovery import recover_evidence
    pdf=tmp_path/'source.pdf';data=b'%PDF synthetic';pdf.write_bytes(data)
    row={'id':'p','record_type':'section','title':'pdf','body':'unverified extracted text','path':str(pdf),'revision':hashlib.sha256(data).hexdigest(),'source_status':'current','page_start':1,'page_end':1}
    result=recover_evidence([row],[],limit=1)
    assert result['status']=='ok'
    assert 'pdf_text_not_independently_verified' in result['verification_limitations']
    good=section(tmp_path/'source.txt','document')
    source={'section_id':good['id'],'path':good['path'],'revision':good['revision'],'source_status':'current','start_line':1,'end_line':1}
    finding={'id':'finding','record_type':'agent_record','title':'finding','body':'claim','source_status':'proposed','unsupported':False,'evidence_status':'current','evidence':[good['id']],'evidence_sources':[source]}
    assert 'agent_claim_not_verified' in recover_evidence([finding],[],limit=1)['verification_limitations']
