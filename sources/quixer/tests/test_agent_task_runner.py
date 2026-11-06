import json
import pytest


def test_paired_runs_are_seeded_isolated_and_preserve_failures():
    from quix_knowledge.agent_study import run_agent_study
    tasks=[{'id':'t1','query':'first task','role':'reviewer','role_version':'1'},
           {'id':'t2','query':'second task','role':'reviewer','role_version':'1'}]
    observed=[]
    def context(task,condition):
        return {'source':condition,'task':task['id']}
    def agent(request):
        observed.append(request)
        if request['task_id']=='t2' and request['context'] and request['context']['source']=='baseline':
            raise TimeoutError()
        return {'output':'fixture answer','usage':None}
    report=run_agent_study(tasks,context_provider=context,agent=agent,seed=17)
    again=run_agent_study(tasks,context_provider=context,agent=agent,seed=17)
    assert report['schedule']==again['schedule']
    assert len(report['runs'])==8
    assert all(set(x)=={'task_id','query','role','role_version','context','max_input_characters'} for x in observed)
    assert sum(x['context'] is None for x in observed)==4
    assert all(x['context']['task']==x['task_id'] for x in observed if x['context'] is not None)
    assert next(r for r in report['runs'] if r['task_id']=='t2' and r['condition']=='baseline')['status']=='timeout'
    assert all(r['reported_cost'] is None for r in report['runs'])
    assert report['agent_kind']=='fixture'


def test_duplicate_tasks_and_oversized_context_are_rejected_or_recorded():
    from quix_knowledge.agent_study import run_agent_study
    task={'id':'t','query':'what','role':'reviewer','role_version':'1'}
    with pytest.raises(ValueError):
        run_agent_study([task,task],context_provider=lambda *_: None,agent=lambda _: {},seed=1)
    report=run_agent_study([task],context_provider=lambda *_: 'x'*1000,agent=lambda _: {'output':'ok'},seed=1,max_input_characters=300)
    assert sum(r['status']=='input_budget_exceeded' for r in report['runs'])==3


def test_process_agent_captures_real_output_usage_and_errors_without_key_in_args(tmp_path):
    import sys
    from quix_knowledge.agent_process import PlannerProcess
    script=tmp_path/'agent.py'
    script.write_text('import json,os,sys\nq=json.load(sys.stdin)\nassert os.environ["OPENROUTER_API_KEY"] == "secret"\nassert "secret" not in str(sys.argv)\nprint(json.dumps({"status":"completed","proposal":{"title":q["task"]},"call":{"costUSD":0.01}}))\n')
    agent=PlannerProcess([sys.executable,str(script)],api_key='secret',model='test/model',timeout=5)
    result=agent({'query':'a task','role':'reviewer','role_version':'1','context':None})
    assert json.loads(result['output'])['title']=='a task'
    assert result['usage']['cost']==0.01
    script.write_text('import json\nprint(json.dumps({"status":"source_changed"}))\n')
    assert agent({'query':'a task','role':'reviewer','role_version':'1','context':None})['status']=='source_changed'


def test_runner_preserves_explicit_agent_failure_status():
    from quix_knowledge.agent_study import run_agent_study
    task={'id':'t','query':'what','role':'reviewer','role_version':'1'}
    report=run_agent_study([task],context_provider=lambda *_: {},agent=lambda _: {'status':'source_changed'},seed=1)
    assert {run['status'] for run in report['runs']}=={'source_changed'}


def test_failed_agent_call_keeps_reported_usage():
    from quix_knowledge.agent_study import run_agent_study
    task={'id':'t','query':'what','role':'reviewer','role_version':'1'}
    result=run_agent_study([task],context_provider=lambda *_:{},agent=lambda _:{'status':'agent_failure','call':{'costUSD':0.02}},seed=1)
    assert all(run['reported_cost']==0.02 for run in result['runs'])


def test_study_records_packet_provenance_without_sending_another_condition():
    from quix_knowledge.agent_study import run_agent_study
    task={'id':'t','query':'what','role':'reviewer','role_version':'1'}
    packet={'catalog_fingerprint':'abc','results':[{'id':'s','revision':'rev','path':'doc','body':'evidence'}],'omitted_count':1}
    report=run_agent_study([task],context_provider=lambda *_:packet,agent=lambda _: {'output':'ok'},seed=3)
    result=next(x for x in report['runs'] if x['condition']=='baseline')
    assert result['context_provenance']['catalog_fingerprint']=='abc'
    assert result['context_provenance']['sources']==[{'id':'s','revision':'rev','path':'doc'}]
    assert len(result['context_provenance']['packet_sha256'])==64


def test_agent_packet_preserves_revision_and_marks_body_truncation():
    from quix_knowledge.agent_context import make_agent_packet
    task={'query':'what','role':'reviewer','role_version':'1'}
    row={'id':'id1','record_type':'section','title':'source','body':'a'*500,'path':'/source','revision':'rev','source_status':'current','start_line':1,'end_line':1}
    packet=make_agent_packet(task,[row],fingerprint='fp',body_characters=100)
    assert packet['results'][0]['body']=='a'*100
    assert packet['results'][0]['body_truncated'] is True
    assert packet['results'][0]['revision']=='rev'
    assert packet['tokenizer']=='json-characters'
    assert row['body']=='a'*500


def test_agent_packet_can_include_multiple_sources_and_counts_omissions():
    from quix_knowledge.agent_context import make_agent_packet
    task={'query':'what','role':'reviewer','role_version':'1'}
    rows=[{'id':str(i),'record_type':'section','title':'source','body':'abc','path':'/source','revision':'rev','source_status':'current','start_line':1,'end_line':1} for i in range(4)]
    packet=make_agent_packet(task,rows,fingerprint='fp',body_characters=10,result_limit=3)
    assert [x['id'] for x in packet['results']]==['0','1','2']
    assert packet['omitted_count']==1


def test_agent_manifest_rejects_labels_and_wrong_condition_set_before_calls():
    from quix_knowledge.agent_study import validate_agent_manifest
    manifest={'schema':'quix-agent-study-manifest-v1','seed':1,'max_input_characters':12000,
              'conditions':['none','baseline','role','switch'],
              'tasks':[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]}
    validate_agent_manifest(manifest)
    bad=json.loads(json.dumps(manifest)); bad['tasks'][0]['labels']=['answer']
    with pytest.raises(ValueError,match='label'): validate_agent_manifest(bad)
    bad=json.loads(json.dumps(manifest)); bad['conditions'].pop()
    with pytest.raises(ValueError,match='conditions'): validate_agent_manifest(bad)


def test_agent_study_emits_schedule_before_runs_and_each_result_as_it_finishes():
    from quix_knowledge.agent_study import run_agent_study
    task={'id':'t','query':'task','role':'reviewer','role_version':'1'}
    events=[]
    def agent(_):
        assert events and events[0][0]=='schedule'
        return {'output':'fixture'}
    result=run_agent_study([task],context_provider=lambda *_:{},agent=agent,seed=1,
        on_schedule=lambda schedule:events.append(('schedule',schedule)),
        on_result=lambda row:events.append(('result',row)))
    assert events[0][1]==result['schedule']
    assert [event[1] for event in events[1:]]==result['runs']
    assert len(events)==5


def test_retrieval_replay_requires_same_tasks_scope_and_corpus():
    from quix_knowledge.agent_study import validate_retrieval_replay
    task={'id':'t','query':'task','role':'reviewer','role_version':'1'}
    r={'manifest':{'corpus_revision':'fp','tasks':[task],'packet_tokens':2000,'tokenizer':'cl100k_base','limit':3,'ranking':'bm25','candidate_scope':'sections_and_records','include_proposed':True},
       'variants':{name:{'queries':{'t':{'results':[]}}} for name in ('baseline','role','switch')}}
    validate_retrieval_replay(r,[task],'fp')
    changed=json.loads(json.dumps(r)); changed['manifest']['tasks'][0]['query']='other'
    with pytest.raises(ValueError,match='tasks'): validate_retrieval_replay(changed,[task],'fp')
    with pytest.raises(ValueError,match='corpus'): validate_retrieval_replay(r,[task],'other')
    changed=json.loads(json.dumps(r)); del changed['variants']['role']['queries']['t']
    with pytest.raises(ValueError,match='queries'): validate_retrieval_replay(changed,[task],'fp')


def test_planner_process_rejects_changed_executable_before_use(tmp_path):
    from quix_knowledge.agent_process import PlannerProcess
    executable=tmp_path/'planner'
    executable.write_text('#!/bin/sh\necho original\n'); executable.chmod(0o700)
    planner=PlannerProcess([str(executable)],api_key='key',model='test',timeout=5)
    executable.write_text('#!/bin/sh\necho changed\n')
    result=planner({'query':'task','role':'reviewer','role_version':'1','context':None})
    assert result['status']=='executable_changed'


def test_planner_process_preserves_unsupported_or_stale_evidence_status(tmp_path):
    import sys
    from quix_knowledge.agent_process import PlannerProcess
    script=tmp_path/'agent.py'
    script.write_text('import json\nprint(json.dumps({"status":"unsupported_or_stale_evidence"}))\n')
    agent=PlannerProcess([sys.executable,str(script)],api_key='key',model='test',timeout=5)
    result=agent({'query':'task','role':'reviewer','role_version':'1','context':None})
    assert result['status']=='unsupported_or_stale_evidence'


def test_planner_process_sends_versioned_role_purpose_and_refuses_mismatch(tmp_path):
    import sys
    from quix_knowledge.agent_process import PlannerProcess, validate_role_bindings
    definitions={'reviewer':{'version':'1','purpose':'Review source evidence.'}}
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    validate_role_bindings(tasks,definitions)
    with pytest.raises(ValueError,match='role'):
        validate_role_bindings([dict(tasks[0],role_version='2')],definitions)
    script=tmp_path/'agent.py'
    script.write_text('import json,sys\nq=json.load(sys.stdin)\nassert q["role_purpose"] == "Review source evidence."\nprint(json.dumps({"status":"completed","proposal":{"title":"ok"}}))\n')
    planner=PlannerProcess([sys.executable,str(script)],api_key='key',model='test',timeout=5,role_definitions=definitions)
    request={'query':'task','role':'reviewer','role_version':'1','context':None}
    assert json.loads(planner(request)['output'])['title']=='ok'
    assert planner(dict(request,role_version='2'))['status']=='role_definition_mismatch'
    definitions['reviewer']['purpose']='changed after configuration'
    assert json.loads(planner(request)['output'])['title']=='ok'


def test_study_role_purpose_is_identical_in_all_conditions_and_counted_in_input_budget():
    from quix_knowledge.agent_study import run_agent_study
    role_definitions={'reviewer':{'version':'1','purpose':'Review source evidence.'}}
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    seen=[]
    def agent(request):
        seen.append(request)
        return {'output':'synthetic'}
    report=run_agent_study(tasks,context_provider=lambda *_:{},agent=agent,seed=3,role_definitions=role_definitions)
    assert len(seen)==4 and all(x['role_purpose']=='Review source evidence.' for x in seen)
    assert all(isinstance(row['study_request_sha256'],str) and len(row['study_request_sha256'])==64 for row in report['runs'])
    long_role={'reviewer':{'version':'1','purpose':'x'*300}}
    seen.clear()
    limited=run_agent_study(tasks,context_provider=lambda *_:{},agent=agent,seed=3,role_definitions=long_role,max_input_characters=300)
    assert not seen and all(row['status']=='input_budget_exceeded' for row in limited['runs'])


def test_agent_retrieval_comparison_requires_and_uses_decision_provider(tmp_path):
    from quix_knowledge.agent_study import run_agent_retrieval_comparison
    from quix_knowledge.store import open_catalog
    from quix_knowledge.ingest import ingest
    db=open_catalog(':memory:')
    path=tmp_path/'source.md'; path.write_text('# Retry\nRetry after a timeout.')
    ingest(db,path)
    task={'id':'q','query':'retry timeout','role':'reviewer','role_version':'1'}
    calls=[]
    def provider(state,question):
        calls.append((state,question))
        return {'outcome':'unclear','provider':'fixture','usage':{'cost':0.01}}
    def switch(snapshot):
        return {'status':'insufficient_evidence','reason':'fixture','state':{'evidence':[]},'receipts':[]}
    with pytest.raises(ValueError,match='decision provider'):
        run_agent_retrieval_comparison(db,[task],switch_runner=switch,count_tokens=len,provider=None)
    report=run_agent_retrieval_comparison(db,[task],switch_runner=switch,count_tokens=len,provider=provider)
    assert report['manifest']['provider_configured'] is True
    assert report['manifest']['switch']['max_steps'] == 20
    assert report['manifest']['switch']['max_model_calls'] == 20
    assert any(question=='relevant' for _,question in calls)
    assert report['variants']['decision']['queries']['q']['decision_calls'] > 0
    assert report['variants']['decision']['queries']['q']['results']


def test_replayed_provider_status_is_reported_without_inference():
    from quix_knowledge.agent_study import retrieval_provider_provenance
    assert retrieval_provider_provenance({'manifest':{'provider_configured':False,'provider':None}})=={'configured':False,'provider':None}
    provider={'configured_model':'test/decision','thresholds':None}
    assert retrieval_provider_provenance({'manifest':{'provider_configured':True,'provider':provider}})=={'configured':True,'provider':provider}
    with pytest.raises(ValueError): retrieval_provider_provenance({'manifest':{'provider_configured':True,'provider':None}})
