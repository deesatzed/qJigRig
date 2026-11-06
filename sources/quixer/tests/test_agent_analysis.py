import copy

import pytest

from quix_knowledge.agent_review import prepare_agent_review


def reviewed_packet(report, tasks):
    packet,key=prepare_agent_review(report,tasks,seed=17)
    packet['reviewer']='Synthetic fixture reviewer'; packet['reviewed_at']='2026-11-03'
    for item in packet['items']:
        item['review']={'correctness':'partial','source_support':'unknown','missing_evidence':'unknown',
                        'task_completion':'partial','explanation':'Fixture only','source_ids':[]}
    return packet,key


def test_paired_analysis_preserves_missing_failure_and_unknown_cost():
    from quix_knowledge.agent_analysis import analyze_agent_outcomes
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    report={'agent_kind':'actual','runs':[
        {'task_id':'t','condition':'none','status':'completed','output':'one','reported_cost':0.1,'elapsed_seconds':1.0},
        {'task_id':'t','condition':'baseline','status':'completed','output':'two','reported_cost':0.2,'elapsed_seconds':2.0},
        {'task_id':'t','condition':'role','status':'timeout','output':None,'reported_cost':None,'elapsed_seconds':3.0}]}
    packet,key=reviewed_packet(report,tasks)
    result=analyze_agent_outcomes(packet,key,report,tasks)
    conditions=result['tasks'][0]['conditions']
    assert conditions['none']['review']['correctness']=='partial'
    assert conditions['role']['status']=='timeout' and conditions['role']['review'] is None
    assert conditions['switch']['status']=='missing' and conditions['switch']['elapsed_seconds'] is None
    assert result['complete_pairs']==[]
    assert result['cost']['known_subtotal_usd']==pytest.approx(0.3)
    assert result['cost']['total_usd'] is None and result['cost']['unknown_count']==2
    assert result['condition_counts']['role']['statuses']=={'timeout':1}
    assert result['condition_counts']['switch']['statuses']=={'missing':1}
    assert result['condition_counts']['baseline']['reviewed']==1
    assert result['condition_counts']['baseline']['correctness']=={'partial':1}
    assert result['reviewer_independence']=='self-reported; not verified'


def test_paired_analysis_rejects_a_review_bound_to_other_output():
    from quix_knowledge.agent_analysis import analyze_agent_outcomes
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':'none','status':'completed','output':'one','reported_cost':None,'elapsed_seconds':1.0}]}
    packet,key=reviewed_packet(report,tasks)
    changed=copy.deepcopy(report); changed['runs'][0]['output']='different'
    with pytest.raises(ValueError,match='output'):
        analyze_agent_outcomes(packet,key,changed,tasks)


def test_paired_analysis_reports_complete_pairs_without_declaring_winner():
    from quix_knowledge.agent_analysis import analyze_agent_outcomes
    tasks=[{'id':'t','query':'task','role':'implementer','role_version':'1'}]
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':name,'status':'completed','output':name,'reported_cost':0.01,'elapsed_seconds':1.0} for name in ('none','baseline','role','switch')]}
    packet,key=reviewed_packet(report,tasks)
    result=analyze_agent_outcomes(packet,key,report,tasks)
    assert result['complete_pairs']==['t']
    assert result['cost']['total_usd']==pytest.approx(0.04)
    assert 'winner' not in result


def test_analysis_does_not_treat_completed_status_with_missing_output_as_reviewed():
    from quix_knowledge.agent_analysis import analyze_agent_outcomes
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':'none','status':'completed','output':None,'reported_cost':None,'elapsed_seconds':1.0}]}
    packet,key=reviewed_packet(report,tasks)
    result=analyze_agent_outcomes(packet,key,report,tasks)
    condition=result['tasks'][0]['conditions']['none']
    assert condition['status']=='invalid_output'
    assert condition['recorded_status']=='completed'
    assert condition['review'] is None


def test_recorded_packet_check_rejects_changed_context():
    import hashlib
    import json
    from quix_knowledge.agent_analysis import validate_recorded_packets
    task={'id':'t','query':'task','role':'reviewer','role_version':'1'}
    packet={'task':'task','role':'reviewer','role_version':'1','catalog_fingerprint':'fp','results':[{'id':'s','revision':'rev','path':'p','body':'text'}]}
    digest=hashlib.sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    report={'manifest':{'corpus_revision':'fp'},'runs':[{'task_id':'t','condition':'baseline','context_provenance':{'packet_sha256':digest,'catalog_fingerprint':'fp','sources':[{'id':'s','revision':'rev','path':'p'}]}}]}
    packets=[{'task_id':'t','condition':'baseline','packet':packet}]
    validate_recorded_packets(report,packets,[task])
    altered=copy.deepcopy(packets); altered[0]['packet']['results'][0]['body']='tampered'
    with pytest.raises(ValueError,match='packet'):
        validate_recorded_packets(report,altered,[task])
    altered_report=copy.deepcopy(report); altered_report['runs'][0]['context_provenance']['omitted_count']=99
    with pytest.raises(ValueError,match='packet'):
        validate_recorded_packets(altered_report,packets,[task])


def test_retrieval_costs_are_separate_and_missing_usage_remains_unknown():
    from quix_knowledge.agent_analysis import summarize_retrieval_accounting
    comparison={'variants':{'switch':{'queries':{
        'a':{'physical_requests':2,'reported_cost':0.02},
        'b':{'physical_requests':None,'reported_cost':None}}}}}
    preparation={'role_scoring':{'calls':8,'reported_cost':0.04,'unknown':1}}
    result=summarize_retrieval_accounting(comparison,preparation)
    assert result['switch']['known_reported_usd']==pytest.approx(0.02)
    assert result['switch']['total_reported_usd'] is None
    assert result['switch']['physical_requests'] is None
    assert result['switch']['unknown_cost_queries']==1
    assert result['role_indexing']['reported_cost']==pytest.approx(0.04)


def test_recorded_role_purposes_must_match_frozen_role_definitions():
    from quix_knowledge.agent_analysis import validate_recorded_role_definitions
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    roles={'reviewer':{'version':'1','purpose':'Review evidence.'}}
    report={'manifest':{'planner_role_purpose_included':True,'planner_prompt_contract':'quix-planner-role-purpose-v1','role_definitions':roles}}
    assert validate_recorded_role_definitions(report,tasks,roles)=='recorded'
    assert validate_recorded_role_definitions({'manifest':{}},tasks,roles)=='not_recorded'
    altered=copy.deepcopy(report); altered['manifest']['role_definitions']['reviewer']['purpose']='Different purpose.'
    with pytest.raises(ValueError,match='role'):
        validate_recorded_role_definitions(altered,tasks,roles)


def test_request_hashes_bind_role_purpose_and_full_study_input():
    from quix_knowledge.agent_analysis import validate_study_requests
    from quix_knowledge.agent_study import run_agent_study
    tasks=[{'id':'t','query':'task','role':'reviewer','role_version':'1'}]
    roles={'reviewer':{'version':'1','purpose':'Review evidence.'}}
    report=run_agent_study(tasks,context_provider=lambda *_:{'fixture':'context'},agent=lambda _: {'output':'fixture'},seed=1,role_definitions=roles)
    report['manifest']={'planner_role_purpose_included':True,'role_definitions':roles}
    packets=[{'task_id':'t','condition':c,'packet':{'fixture':'context'}} for c in ('baseline','role','switch')]
    assert validate_study_requests(report,packets,tasks)=='verified'
    altered=copy.deepcopy(report); altered['manifest']['role_definitions']['reviewer']['purpose']='Changed purpose.'
    with pytest.raises(ValueError,match='request'):
        validate_study_requests(altered,packets,tasks)
    old=copy.deepcopy(report)
    for row in old['runs']:
        row.pop('study_request_sha256'); row.pop('study_request_characters')
    old['manifest']={}
    assert validate_study_requests(old,packets,tasks)=='not_recorded'


def test_reconstruct_saved_agent_packets_from_verified_retrieval(tmp_path):
    from quix_knowledge.agent_context import build_agent_packets
    from quix_knowledge.ingest import ingest
    from quix_knowledge.store import open_catalog
    from quix_knowledge.switch_comparison import run_switch_comparison
    db=open_catalog(':memory:'); source=tmp_path/'doc.md'; source.write_text('# Topic\nSource evidence.')
    ingest(db,source)
    tasks=[{'id':'t','query':'source','role':'reviewer','role_version':'1'}]
    report=run_switch_comparison(db,tasks,switch_runner=lambda _: {'status':'insufficient_evidence','reason':'unknown','state':{'evidence':[]},'receipts':[]},packet_tokens=3000,count_tokens=len,tokenizer_name='fixture-characters')
    packets=build_agent_packets(db,report,tasks,body_characters=8,result_limit=3)
    assert set(packets)=={('t','baseline'),('t','role'),('t','switch')}
    assert packets[('t','baseline')]['results'][0]['body']=='# Topic\n'
    assert packets[('t','baseline')]['results'][0]['body_truncated'] is True
    assert packets[('t','switch')]['results'][0]['fallback_reason']=='switch_insufficient_evidence'
    db.close()


def test_analysis_cli_verifies_source_and_reconstructs_paired_fixture(tmp_path):
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tiktoken
    from quix_knowledge.agent_context import build_agent_packets
    from quix_knowledge.agent_review import seal_review_packet
    from quix_knowledge.agent_study import run_agent_study
    from quix_knowledge.retrieval_study import prepare_study
    from quix_knowledge.store import open_catalog
    from quix_knowledge.switch_comparison import run_switch_comparison
    root=Path(__file__).resolve().parents[1]
    study=tmp_path/'study'; run=tmp_path/'run'; run.mkdir()
    prep=prepare_study(root,root/'experiments/retrieval/manifest.json',study,isolated_sources=True)
    manifest=json.loads((root/'experiments/agent_tasks/manifest-exploratory-16.json').read_text()); manifest['tasks']=manifest['tasks'][:1]
    manifest_bytes=json.dumps(manifest,indent=2).encode(); (run/'manifest.json').write_bytes(manifest_bytes)
    db=open_catalog(study/'catalog.db'); encoding=tiktoken.get_encoding('cl100k_base')
    comparison=run_switch_comparison(db,manifest['tasks'],switch_runner=lambda _: {'status':'insufficient_evidence','reason':'fixture','state':{'evidence':[]},'receipts':[]},packet_tokens=2000,count_tokens=lambda x:len(encoding.encode(x)),tokenizer_name='cl100k_base',limit=3,include_proposed=True,ranking='bm25')
    packets=build_agent_packets(db,comparison,manifest['tasks'],body_characters=100,result_limit=3); db.close()
    report=run_agent_study(manifest['tasks'],context_provider=lambda task,condition:packets[(task['id'],condition)],agent=lambda _: {'output':'synthetic fixture','usage':{'cost':0.01}},seed=manifest['seed'],agent_kind='actual')
    report['manifest']={'sha256':hashlib.sha256(manifest_bytes).hexdigest(),'corpus_revision':prep['corpus_revision'],'context_body_character_limit':100,'context_result_limit':3}
    (run/'agent-report.json').write_text(json.dumps(report)); (run/'retrieval-report.json').write_text(json.dumps(comparison))
    (run/'packets.json').write_text(json.dumps([{'task_id':k[0],'condition':k[1],'packet':v} for k,v in packets.items()]))
    packet,key=reviewed_packet(report,manifest['tasks'])
    source_packet=json.loads((study/'blind-review-packet.json').read_text())
    packet['corpus_revision']=prep['corpus_revision']; packet['source_candidates']=source_packet['candidates']; seal_review_packet(packet,key)
    reviewed=tmp_path/'reviewed.json'; keyfile=tmp_path/'key.json'; out=tmp_path/'analysis.json'
    reviewed.write_text(json.dumps(packet)); keyfile.write_text(json.dumps(key))
    cmd=[sys.executable,str(root/'experiments/agent_tasks/analyze_review.py'),str(reviewed),str(keyfile),str(run),str(study),str(out)]
    result=subprocess.run(cmd,text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=20)
    assert result.returncode==0, result.stderr
    analysis=json.loads(out.read_text())
    assert analysis['complete_pairs']==[manifest['tasks'][0]['id']]
    assert analysis['source_verification']['catalog_current_at_analysis'] is True
    assert analysis['cost']['total_usd']==pytest.approx(0.04)
    saved=json.loads((run/'packets.json').read_text()); saved[0]['packet']['results'][0]['body']='tampered'; (run/'packets.json').write_text(json.dumps(saved))
    bad=subprocess.run(cmd[:-1]+[str(tmp_path/'bad.json')],text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=20)
    assert bad.returncode!=0 and not (tmp_path/'bad.json').exists()
    (run/'packets.json').write_text(json.dumps([{'task_id':k[0],'condition':k[1],'packet':v} for k,v in packets.items()]))
    (study/'source-snapshot/experiments/retrieval/fixtures/stale-original.txt').write_text('changed after review')
    bad_source=subprocess.run(cmd[:-1]+[str(tmp_path/'bad-source.json')],text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=20)
    assert bad_source.returncode!=0 and not (tmp_path/'bad-source.json').exists()
