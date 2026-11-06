import json
from pathlib import Path

import pytest


def test_retrieval_review_saves_separate_progress_and_resumes(tmp_path):
    from quix_knowledge.review_session import ReviewSession
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'
    packet={'schema':'quix-blind-review-v1','reviewer':None,'corpus_revision':'fp','candidates':[{'id':'a','title':'A','body':'source'}],
        'tasks':[{'id':'q1','query':'task','labels':None,'reviewed':False,'missing_reason':None},
                 {'id':'q2','query':'other','labels':None,'reviewed':False,'missing_reason':None}]}
    original=json.dumps(packet); source.write_text(original)
    session=ReviewSession(source,output,'Reviewer')
    session.record_retrieval(0,['a'])
    assert source.read_text()==original
    assert json.loads(output.read_text())['tasks'][0]['labels']==['a']
    resumed=ReviewSession(source,output,'Reviewer')
    with pytest.raises(ValueError,match='reason'): resumed.record_retrieval(1,[])
    resumed.record_retrieval(1,[],missing_reason='No supporting source')
    assert json.loads(output.read_text())['tasks'][1]['reviewed'] is True
    with pytest.raises(ValueError,match='reviewer'): ReviewSession(source,output,'Different')


def test_review_session_rejects_unknown_source_and_changed_draft(tmp_path):
    from quix_knowledge.review_session import ReviewSession
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'
    source.write_text(json.dumps({'schema':'quix-blind-review-v1','reviewer':None,'candidates':[{'id':'a','title':'A','body':'text'}],
        'tasks':[{'id':'q','query':'task','labels':None,'reviewed':False,'missing_reason':None}]}))
    session=ReviewSession(source,output,'Reviewer')
    with pytest.raises(ValueError,match='source'): session.record_retrieval(0,['invented'])
    with pytest.raises(ValueError,match='date'): session.record_retrieval(0,['a'],reviewed_at='2026-02-30')
    assert not output.exists()
    session.record_retrieval(0,['a'])
    altered=json.loads(output.read_text()); altered['candidates'][0]['body']='modified'; output.write_text(json.dumps(altered))
    with pytest.raises(ValueError,match='contract'): ReviewSession(source,output,'Reviewer')


def test_outcome_review_record_is_compilable_without_reading_key(tmp_path):
    from quix_knowledge.agent_review import prepare_agent_review, compile_agent_review, seal_review_packet
    from quix_knowledge.review_session import ReviewSession
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':'none','status':'completed','output':'answer'}]}
    packet,key=prepare_agent_review(report,[{'id':'t','query':'task'}],seed=1)
    packet['source_candidates']=[{'id':'s','title':'Source','body':'text'}]; seal_review_packet(packet,key)
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'; source.write_text(json.dumps(packet))
    session=ReviewSession(source,output,'Reviewer')
    review={'correctness':'partial','source_support':'unknown','missing_evidence':'unknown','task_completion':'partial','explanation':'Need more evidence','source_ids':['s']}
    with pytest.raises(ValueError,match='source'):
        session.record_outcome(0,dict(review,source_ids=['invented']),reviewed_at='2026-11-03')
    session.record_outcome(0,review,reviewed_at='2026-11-03')
    compiled=compile_agent_review(json.loads(output.read_text()),key)
    assert compiled['outcomes'][0]['review']==review
    assert len(compiled['missing'])==3


def test_guided_terminal_review_can_inspect_and_save_without_condition_key(tmp_path):
    import os
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'
    packet={'schema':'quix-blind-review-v1','reviewer':None,'candidates':[{'id':'source-a','title':'Retry','body':'Retry after timeout.'}],
        'tasks':[{'id':'q','query':'What happens on timeout?','labels':None,'reviewed':False,'missing_reason':None}]}
    source.write_text(json.dumps(packet))
    env=dict(os.environ,PYTHONPATH=str(root/'src'))
    result=subprocess.run([sys.executable,str(root/'experiments/guided_review.py'),str(source),str(output),'--reviewer','Reviewer'],input='show 1\nmark 1\n',text=True,capture_output=True,env=env,timeout=10)
    assert result.returncode==0
    assert 'Retry after timeout.' in result.stdout
    assert json.loads(output.read_text())['tasks'][0]['labels']==['source-a']
    assert json.loads(source.read_text())==packet


def test_guided_outcome_review_compiles_with_separate_key(tmp_path):
    import os
    import subprocess
    import sys
    from quix_knowledge.agent_review import prepare_agent_review, compile_agent_review, seal_review_packet
    root=Path(__file__).resolve().parents[1]
    packet,key=prepare_agent_review({'agent_kind':'actual','runs':[{'task_id':'t','condition':'role','status':'completed','output':'answer'}]},[{'id':'t','query':'question'}],seed=1)
    packet['source_candidates']=[{'id':'s','title':'Retry','body':'Retry later.'}]; seal_review_packet(packet,key)
    source=tmp_path/'packet.json'; output=tmp_path/'review.json'; source.write_text(json.dumps(packet))
    inputs='search Retry\nshow 1\nreview\npartial\nunknown\nunknown\npartial\nNeeds evidence\n1\n'
    result=subprocess.run([sys.executable,str(root/'experiments/guided_review.py'),str(source),str(output),'--reviewer','Reviewer','--date','2026-11-03'],input=inputs,text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=10)
    assert result.returncode==0 and 'Retry later.' in result.stdout
    compiled=compile_agent_review(json.loads(output.read_text()),key)
    assert compiled['outcomes'][0]['condition']=='role'
    assert compiled['outcomes'][0]['review']['source_ids']==['s']


def test_guided_review_quit_keeps_unreviewed_items_unlabeled(tmp_path):
    import os
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'
    packet={'schema':'quix-blind-review-v1','reviewer':None,'candidates':[{'id':'s','title':'source','body':'text'}],
        'tasks':[{'id':'one','query':'first','labels':None,'reviewed':False,'missing_reason':None},
                 {'id':'two','query':'second','labels':None,'reviewed':False,'missing_reason':None}]}
    source.write_text(json.dumps(packet))
    result=subprocess.run([sys.executable,str(root/'experiments/guided_review.py'),str(source),str(output),'--reviewer','Reviewer'],input='mark 1\nquit\n',text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=10)
    assert result.returncode==0
    items=json.loads(output.read_text())['tasks']
    assert items[0]['labels']==['s']
    assert items[1]['labels'] is None and items[1]['reviewed'] is False


def test_guided_retrieval_review_compiles_against_original_catalog(tmp_path):
    import os
    import subprocess
    import sys
    from quix_knowledge.ingest import ingest
    from quix_knowledge.labeling import prepare_review, compile_review
    from quix_knowledge.store import open_catalog
    root=Path(__file__).resolve().parents[1]
    db=open_catalog(':memory:'); document=tmp_path/'source.txt'; document.write_text('A source sentence.')
    ingest(db,document)
    tasks=[{'id':'t','query':'What is in the source?','role':'reviewer','role_version':'1'}]
    packet=prepare_review(db,tasks,include_proposed=True,candidate_scope='sections_and_records')
    source=tmp_path/'packet.json'; output=tmp_path/'review.json'; source.write_text(json.dumps(packet))
    result=subprocess.run([sys.executable,str(root/'experiments/guided_review.py'),str(source),str(output),'--reviewer','Fixture reviewer','--date','2026-11-03'],input='mark 1\n',text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=10)
    assert result.returncode==0
    compiled=compile_review(db,json.loads(output.read_text()))
    assert compiled['tasks'][0]['labels']==[packet['candidates'][0]['id']]
    assert compiled['tasks'][0]['reviewed_at']=='2026-11-03'
    assert compiled['label_provenance']['reviewed_with_date']==1
    assert compiled['label_provenance']['reviewed_without_date']==0
    assert compiled['label_provenance']['identity_independence']=='self-reported; not verified'
    db.close()


def test_interrupted_outcome_form_does_not_save_partial_or_invent_labels(tmp_path):
    import os
    import subprocess
    import sys
    from quix_knowledge.agent_review import prepare_agent_review, seal_review_packet
    root=Path(__file__).resolve().parents[1]
    report={'agent_kind':'actual','runs':[{'task_id':'t','condition':name,'status':'completed','output':'answer'} for name in ('none','baseline')]}
    packet,key=prepare_agent_review(report,[{'id':'t','query':'task'}],seed=3)
    packet['source_candidates']=[{'id':'s','title':'source','body':'text'}]; seal_review_packet(packet,key)
    source=tmp_path/'packet.json'; output=tmp_path/'draft.json'; source.write_text(json.dumps(packet))
    first='review\npartial\nunknown\nunknown\npartial\nExplanation\n\n'
    interrupted='review\ncorrect\n'
    result=subprocess.run([sys.executable,str(root/'experiments/guided_review.py'),str(source),str(output),'--reviewer','Reviewer','--date','2026-11-03'],input=first+interrupted,text=True,capture_output=True,env=dict(os.environ,PYTHONPATH=str(root/'src')),timeout=10)
    assert result.returncode==0
    items=json.loads(output.read_text())['items']
    assert items[0]['review']['correctness']=='partial'
    assert items[1]['review'] is None
