import json
import pytest


def test_blind_review_hides_condition_and_keeps_failed_runs_separate():
    from quix_knowledge.agent_review import prepare_agent_review
    report={'agent_kind':'actual','runs':[
        {'task_id':'t1','condition':'baseline','status':'completed','output':'First response'},
        {'task_id':'t1','condition':'switch','status':'completed','output':'Second response'},
        {'task_id':'t2','condition':'none','status':'timeout','output':None}]}
    tasks=[{'id':'t1','query':'task one'},{'id':'t2','query':'task two'}]
    packet,key=prepare_agent_review(report,tasks,seed=8)
    assert len(packet['items'])==2
    assert len(key['missing'])==6 and sum(x['status']=='timeout' for x in key['missing'])==1
    assert sum(x['status']=='missing' for x in key['missing'])==5
    assert 'baseline' not in json.dumps(packet) and 'switch' not in json.dumps(packet)
    assert all(item['review'] is None for item in packet['items'])
    assert prepare_agent_review(report,tasks,seed=8)==(packet,key)
    assert {item['blind_id'] for item in packet['items']}==set(key['conditions'])


def test_blind_review_rejects_fixture_and_duplicate_conditions():
    from quix_knowledge.agent_review import prepare_agent_review
    task=[{'id':'t','query':'task'}]
    with pytest.raises(ValueError): prepare_agent_review({'agent_kind':'fixture','runs':[]},task,seed=1)
    run={'task_id':'t','condition':'none','status':'completed','output':'ok'}
    with pytest.raises(ValueError): prepare_agent_review({'agent_kind':'actual','runs':[run,run]},task,seed=1)


def test_review_compilation_validates_blind_contract_before_unblinding():
    from quix_knowledge.agent_review import prepare_agent_review, compile_agent_review
    task=[{'id':'t','query':'task'}]
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':c,'status':'completed','output':f'answer {i}'} for i,c in enumerate(('none','baseline','role','switch'))]}
    packet,key=prepare_agent_review(report,task,seed=4)
    packet['reviewer']='Independent reviewer'; packet['reviewed_at']='2026-11-03'
    for item in packet['items']:
        item['review']={'correctness':'partial','source_support':'unknown','missing_evidence':'unknown','task_completion':'partial','explanation':'Reviewed against source','source_ids':[]}
    result=compile_agent_review(packet,key)
    assert result['complete_pairs']==['t']
    assert len(result['outcomes'])==4 and not result['missing']
    assert result['reviewer_independence']=='self-reported; not verified'
    packet['items'][0]['output']='modified'
    with pytest.raises(ValueError,match='contract'):
        compile_agent_review(packet,key)


def test_review_compilation_rejects_incomplete_or_unknown_source():
    from quix_knowledge.agent_review import prepare_agent_review, compile_agent_review, seal_review_packet
    packet,key=prepare_agent_review({'agent_kind':'actual','runs':[{'task_id':'t','condition':'none','status':'completed','output':'ok'}]},[{'id':'t','query':'task'}],seed=1)
    packet['source_candidates']=[{'id':'s1'}]; seal_review_packet(packet,key)
    packet['reviewer']='reviewer'; packet['reviewed_at']='2026-11-03'
    with pytest.raises(ValueError,match='review'):
        compile_agent_review(packet,key)
    packet['items'][0]['review']={'correctness':'correct','source_support':'supported','missing_evidence':'none','task_completion':'complete','explanation':'x','source_ids':['not-a-source']}
    with pytest.raises(ValueError,match='source'):
        compile_agent_review(packet,key)


def test_review_compilation_rejects_changed_condition_key_and_missing_run_list():
    from quix_knowledge.agent_review import prepare_agent_review, compile_agent_review
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':'none','status':'completed','output':'ok'}]}
    packet,key=prepare_agent_review(report,[{'id':'t','query':'task'}],seed=1)
    packet['reviewer']='reviewer'; packet['reviewed_at']='2026-11-03'
    packet['items'][0]['review']={'correctness':'correct','source_support':'unknown','missing_evidence':'unknown','task_completion':'complete','explanation':'x','source_ids':[]}
    altered=json.loads(json.dumps(key)); altered['missing'].pop()
    with pytest.raises(ValueError,match='key'):
        compile_agent_review(packet,altered)
    altered=json.loads(json.dumps(key)); altered['conditions']['answer-001']['condition']='role'
    with pytest.raises(ValueError,match='key'):
        compile_agent_review(packet,altered)


def test_outcome_review_rejects_changed_source_candidate_material(tmp_path):
    import sqlite3
    from pathlib import Path
    from quix_knowledge.agent_review import validate_review_sources
    from quix_knowledge.retrieval_study import prepare_study
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'experiments/retrieval/manifest.json').read_text())
    study=tmp_path/'study'; prepare_study(root,root/'experiments/retrieval/manifest.json',study)
    packet=json.loads((study/'blind-review-packet.json').read_text())
    db=sqlite3.connect(study/'catalog.db'); db.row_factory=sqlite3.Row
    try:
        validate_review_sources(db,packet,manifest['tasks'])
        packet['candidates'][0]['body']='altered'
        with pytest.raises(ValueError,match='candidate'):
            validate_review_sources(db,packet,manifest['tasks'])
    finally: db.close()
