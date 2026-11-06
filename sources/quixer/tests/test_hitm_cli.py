import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from quix_knowledge.ingest import ingest
from quix_knowledge.store import open_catalog


def invoke(db, body):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    return subprocess.run([sys.executable, '-m', 'quix_knowledge', '--db', str(db), 'hitm-context'], input=body, text=True, capture_output=True, env=env, timeout=5)


def test_one_shot_request_is_source_checked_and_does_not_write_catalog(tmp_path):
    path = tmp_path / 'source.md'
    path.write_text('# Retry\nRetry after a timeout.')
    catalog = tmp_path / 'catalog.db'
    db = open_catalog(catalog)
    ingest(db, path)
    db.close()
    before = hashlib.sha256(catalog.read_bytes()).digest()
    request = {'version': 1, 'task': 'retry', 'role': 'reviewer', 'role_version': '1', 'limit': 2, 'budget_characters': 2000}
    result = invoke(catalog, json.dumps(request))
    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response['ok'] is True
    assert response['packet']['results'][0]['path'] == str(path)
    assert hashlib.sha256(catalog.read_bytes()).digest() == before
    path.write_text('# Retry\nChanged.')
    stale = invoke(catalog, json.dumps(request))
    assert stale.returncode != 0
    assert json.loads(stale.stdout)['error']['code'] == 'source_changed'


def test_one_shot_reports_invalid_request_and_missing_catalog(tmp_path):
    result = invoke(tmp_path/'missing.db', '{bad json')
    assert result.returncode != 0
    assert json.loads(result.stdout)['error']['code'] == 'invalid_request'
    result = invoke(tmp_path/'missing.db', json.dumps({'version':1,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':500}))
    assert result.returncode != 0
    assert json.loads(result.stdout)['error']['code'] == 'catalog_unavailable'
    assert not (tmp_path/'missing.db').exists()
    result = invoke(tmp_path/'missing.db', json.dumps({'version':99,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':500}))
    assert json.loads(result.stdout)['error']['code'] == 'invalid_request'
    result = invoke(tmp_path/'missing.db', json.dumps({'version':1,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':500,'path':'/tmp/other'}))
    assert json.loads(result.stdout)['error']['code'] == 'invalid_request'


def test_one_shot_rejects_unsupported_schema_and_oversized_request(tmp_path):
    import sqlite3
    catalog = tmp_path/'unsupported.db'
    db = sqlite3.connect(catalog)
    db.execute('PRAGMA user_version=99')
    db.close()
    request = {'version':1,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':500}
    result = invoke(catalog,json.dumps(request))
    assert json.loads(result.stdout)['error']['code'] == 'catalog_unavailable'
    result = invoke(catalog, ' ' * 65537)
    assert json.loads(result.stdout)['error']['code'] == 'invalid_request'


def test_one_shot_reports_too_small_budget_and_normalizes_crlf(tmp_path):
    source = tmp_path/'source.md'
    source.write_bytes(b'# Retry\r\nRetry after a timeout.\r\n')
    catalog = tmp_path/'catalog.db'
    db = open_catalog(catalog)
    ingest(db,source)
    db.close()
    request = {'version':1,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':1}
    assert json.loads(invoke(catalog,json.dumps(request)).stdout)['error']['code'] == 'budget_too_small'
    request['budget_characters'] = 2000
    assert json.loads(invoke(catalog,json.dumps(request)).stdout)['ok'] is True


def test_one_shot_checks_pdf_bytes_and_page_anchor(tmp_path):
    import pytest
    fitz = pytest.importorskip('fitz')
    from quix_knowledge.pdf import ingest_pdf
    source = tmp_path/'source.pdf'
    document = fitz.open()
    document.new_page().insert_text((72,72),'Retry after timeout')
    document.save(source)
    document.close()
    catalog = tmp_path/'catalog.db'
    db = open_catalog(catalog)
    ingest_pdf(db,source)
    db.close()
    request = {'version':1,'task':'retry','role':'r','role_version':'1','limit':1,'budget_characters':2000}
    result = json.loads(invoke(catalog,json.dumps(request)).stdout)
    assert result['packet']['results'][0]['page_start'] == 1
    source.write_bytes(source.read_bytes() + b'\n')
    assert json.loads(invoke(catalog,json.dumps(request)).stdout)['error']['code'] == 'source_changed'


def test_recovery_command_replaces_missing_source_and_reports_exclusion(tmp_path):
    missing=tmp_path/'missing.txt'; kept=tmp_path/'kept.txt'
    missing.write_text('retry retry missing evidence'); kept.write_text('retry evidence alternative')
    catalog=tmp_path/'catalog.db'; db=open_catalog(catalog)
    ingest(db,missing); ingest(db,kept); db.close(); missing.unlink()
    before=hashlib.sha256(catalog.read_bytes()).digest()
    request={'version':1,'task':'retry missing evidence','role':'reviewer','role_version':'1','limit':2,'budget_characters':5000}
    env=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
    args=[sys.executable,'-m','quix_knowledge','--db',str(catalog),'hitm-recovery-context']
    result=subprocess.run(args,input=json.dumps(request),text=True,capture_output=True,env=env,timeout=5)
    assert result.returncode==0, result.stderr
    response=json.loads(result.stdout)
    assert response['packet']['task']==request['task']
    assert response['packet']['results'][0]['path']==str(kept)
    assert response['recovery']['excluded'][0]['reason']=='source_unavailable'
    assert hashlib.sha256(catalog.read_bytes()).digest()==before
    kept.unlink()
    result=subprocess.run(args,input=json.dumps(request),text=True,capture_output=True,env=env,timeout=5)
    assert json.loads(result.stdout)['error']['code']=='insufficient_evidence'
