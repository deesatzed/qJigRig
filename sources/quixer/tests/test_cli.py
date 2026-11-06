import json
import subprocess
import sys
import os
from pathlib import Path

def test_cli_ingest_and_search(tmp_path):
    path = tmp_path/'doc.md'
    path.write_text('# Interface\nmessage protocol\n')
    db = tmp_path/'catalog.db'
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    def run(*args):
        return subprocess.run([sys.executable,'-m','quix_knowledge', '--db',str(db),*args],env=env,capture_output=True,text=True,check=True)
    assert json.loads(run('ingest',str(path)).stdout)['source_id']
    result = json.loads(run('search','protocol').stdout)
    assert result[0]['title'] == 'Interface'
    assert result[0]['start_line'] == 1

def test_cli_requires_both_env_file_and_slot_for_model(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    result = subprocess.run([sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'search','retry','--variant','decision','--model-slot','2'],env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert '--env-file' in result.stderr

def test_cli_index_creates_proposed_topic(tmp_path):
    path = tmp_path/'doc.md'
    path.write_text('# Retry policy\nRetry twice.\n')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    result = subprocess.run([sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'index',str(path)],env=env,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['topic_candidates'] == 1

def test_cli_experiment_emits_manifest_for_unlabeled_task(tmp_path):
    taskfile = tmp_path/'tasks.json'
    taskfile.write_text(json.dumps([{'id':'q','query':'retry','role':'reviewer','role_version':'1','labels':None}]))
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    result = subprocess.run([sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'experiment',str(taskfile),'--context-chars','100'],env=env,capture_output=True,text=True,check=True)
    report = json.loads(result.stdout)
    assert report['variants']['baseline']['metrics']['unlabeled'] == 1
    assert report['manifest']['context_chars'] == 100

def test_cli_token_budget_uses_named_tokenizer(tmp_path):
    import pytest
    pytest.importorskip('tiktoken')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry with exponential backoff and jitter.')
    db=tmp_path/'db'
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(db)]
    subprocess.run([*base,'ingest',str(path)],env=env,capture_output=True,text=True,check=True)
    result=subprocess.run([*base,'search','retry','--context-tokens','3','--tokenizer','cl100k_base'],env=env,capture_output=True,text=True,check=True)
    rows=json.loads(result.stdout)
    assert sum(row['context_token_count'] for row in rows) <= 3

def test_cli_can_list_and_review_generated_entries(tmp_path):
    path=tmp_path/'manual.txt'
    path.write_text('Retries prevent outages.\n\nRecord failures.')
    db=tmp_path/'db'
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(db)]
    subprocess.run([*base,'index',str(path)],env=env,capture_output=True,text=True,check=True)
    listed=json.loads(subprocess.run([*base,'list-index'],env=env,capture_output=True,text=True,check=True).stdout)
    assert len(listed) == 2
    entry=listed[0]['id']
    subprocess.run([*base,'review-index',entry,'accepted','--reviewer','human-reviewer'],env=env,capture_output=True,text=True,check=True)
    listed=json.loads(subprocess.run([*base,'list-index'],env=env,capture_output=True,text=True,check=True).stdout)
    assert next(x for x in listed if x['id'] == entry)['status'] == 'accepted'

def test_cli_experiment_accepts_saved_index_receipt_ids(tmp_path):
    tasks=tmp_path/'tasks.json'
    tasks.write_text(json.dumps([{'id':'q','query':'retry','labels':None}]))
    receipts=tmp_path/'receipts.json'
    receipts.write_text('[]')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'experiment',str(tasks),'--indexing-receipts',str(receipts)]
    report=json.loads(subprocess.run(cmd,env=env,capture_output=True,text=True,check=True).stdout)
    assert report['manifest']['indexing']['decision_calls'] == 0

def test_cli_role_assessment_requires_explicit_model_and_role_purpose(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'assess-role','section','--role','reviewer','--role-version','1']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert '--role-purpose' in result.stderr

def test_cli_rejects_mixed_local_and_openrouter_configuration(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'search','retry','--variant','decision','--env-file','config.env','--model-slot','2','--jev-url','http://127.0.0.1:8090']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert 'choose one decision provider' in result.stderr

def test_cli_lists_and_reviews_heading_topics(tmp_path):
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry twice.')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db')]
    subprocess.run([*base,'index',str(path)],env=env,capture_output=True,text=True,check=True)
    links=json.loads(subprocess.run([*base,'list-topics'],env=env,capture_output=True,text=True,check=True).stdout)
    assert links[0]['topic'] == 'Retry'
    subprocess.run([*base,'review-topic',str(links[0]['id']),'accepted','--reviewer','reviewer'],env=env,capture_output=True,text=True,check=True)
    links=json.loads(subprocess.run([*base,'list-topics','--status','accepted'],env=env,capture_output=True,text=True,check=True).stdout)
    assert len(links) == 1

def test_cli_record_topic_requires_provider_configuration(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'assess-record-topic','finding','retry']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert 'requires a decision provider' in result.stderr

def test_cli_context_includes_metadata_in_named_token_budget(tmp_path):
    import pytest
    tiktoken=pytest.importorskip('tiktoken')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry after failure and record the result.')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db')]
    subprocess.run([*base,'ingest',str(path)],env=env,capture_output=True,text=True,check=True)
    result=subprocess.run([*base,'context','retry','--role','reviewer','--role-version','1','--budget','250','--tokenizer','cl100k_base'],env=env,capture_output=True,text=True,check=True)
    packet=json.loads(result.stdout)
    serialized=json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    assert len(tiktoken.get_encoding('cl100k_base').encode_ordinary(serialized)) <= 250
    assert packet['catalog_fingerprint']

def test_cli_refuses_thresholds_without_provider(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'search','retry','--variant','decision','--thresholds','0.2','0.8']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert 'thresholds require a decision provider' in result.stderr

def test_cli_hybrid_requires_explicit_local_encoder_paths(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'search','retry','--ranking','hybrid']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert '--jevedge-root and --embedding-model-path' in result.stderr

def test_cli_review_packet_roundtrip(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db')]
    source=tmp_path/'doc.md'
    source.write_text('# Retry\nRetry twice.')
    subprocess.run([*base,'ingest',str(source)],env=env,capture_output=True,text=True,check=True)
    taskfile=tmp_path/'tasks.json'
    taskfile.write_text(json.dumps([{'id':'q','query':'retry','role':'reviewer','role_version':'1','split':'held_out'}]))
    packet=json.loads(subprocess.run([*base,'prepare-review',str(taskfile)],env=env,capture_output=True,text=True,check=True).stdout)
    packet['reviewer']='reviewer'
    packet['tasks'][0].update(reviewed=True,labels=[packet['candidates'][0]['id']])
    review=tmp_path/'review.json'
    review.write_text(json.dumps(packet))
    compiled=json.loads(subprocess.run([*base,'compile-review',str(review)],env=env,capture_output=True,text=True,check=True).stdout)
    label_file=tmp_path/'labels.json'
    label_file.write_text(json.dumps(compiled))
    report=json.loads(subprocess.run([*base,'experiment',str(label_file),'--reviewed'],env=env,capture_output=True,text=True,check=True).stdout)
    assert report['variants']['baseline']['metrics_by_split']['held_out']['mean_recall'] == 1

def test_cli_calibrates_development_and_reports_held_out(tmp_path):
    spec={'rows':[{'id':'d','split':'development','probability':0.9,'label':True,'model':'m','prompt_version':'p','question':'relevance'},{'id':'h','split':'held_out','probability':0.1,'label':False,'model':'m','prompt_version':'p','question':'relevance'}],'threshold_pairs':[[0.2,0.8]],'min_actions':1,'label_provenance':'synthetic fixture'}
    path=tmp_path/'calibration.json'
    path.write_text(json.dumps(spec))
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'calibrate',str(path)]
    result=json.loads(subprocess.run(cmd,env=env,capture_output=True,text=True,check=True).stdout)
    assert result['selected'] == {'low':0.2,'high':0.8}
    assert result['held_out']['true_negative'] == 1

def test_cli_refresh_reports_changed_source(tmp_path):
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry allowed.')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db')]
    subprocess.run([*base,'ingest',str(path)],env=env,capture_output=True,text=True,check=True)
    path.write_text('# Retry\nRetry prohibited.')
    result=subprocess.run([*base,'refresh'],env=env,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)['updated'] == 1

def test_cli_records_agent_proposal_and_named_review(tmp_path):
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    base=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db')]
    body=tmp_path/'finding.txt'
    body.write_text('Retry requires review.')
    created=json.loads(subprocess.run([*base,'add-record','finding-1','finding','--body-file',str(body),'--producer','agent'],env=env,capture_output=True,text=True,check=True).stdout)
    assert created['status'] == 'proposed'
    subprocess.run([*base,'review-record','finding-1','accepted','--reviewer','reviewer'],env=env,capture_output=True,text=True,check=True)
    rows=json.loads(subprocess.run([*base,'search','retry'],env=env,capture_output=True,text=True,check=True).stdout)
    assert rows[0]['source_status'] == 'current'
    assert rows[0]['evidence_status'] == 'unsupported'
    listed=json.loads(subprocess.run([*base,'list-records'],env=env,capture_output=True,text=True,check=True).stdout)
    assert listed[0]['reviews'][0]['reviewer'] == 'reviewer'

def test_cli_topic_mapping_requires_explicit_provider_and_budget(tmp_path):
    topics=tmp_path/'topics.json'
    topics.write_text('["resilience"]')
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    cmd=[sys.executable,'-m','quix_knowledge','--db',str(tmp_path/'db'),'map-topics',str(topics),'--max-decisions','1']
    result=subprocess.run(cmd,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert 'requires a decision provider' in result.stderr
