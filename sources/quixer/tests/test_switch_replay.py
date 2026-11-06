import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from quix_knowledge.ingest import ingest
from quix_knowledge.store import open_catalog
from quix_knowledge.switch_comparison import NodeSwitchRunner, run_switch_comparison


def test_replay_saved_trace_reconstructs_read_only_and_detects_source_change(tmp_path):
    from quix_knowledge.switch_replay import replay_saved_trace
    node=shutil.which('node')
    root=Path(__file__).resolve().parents[1]
    compare=root/'experiments/switch-navigation/src/compare.ts'
    replay=root/'experiments/switch-navigation/src/replay.ts'
    if not node or not (compare.parents[1]/'node_modules/@osolmaz/switch').exists(): pytest.skip('node or switch unavailable')
    document=tmp_path/'source.txt'; document.write_text('retry after timeout')
    catalog=tmp_path/'catalog.db'; db=open_catalog(catalog); ingest(db,document)
    tasks=[{'id':'q','query':'retry','role':'reviewer','role_version':'1'}]
    report=run_switch_comparison(db,tasks,switch_runner=NodeSwitchRunner(node,compare,mode='fixture'),packet_tokens=2000,count_tokens=len,tokenizer_name='fixture-characters',limit=3,include_proposed=True)
    db.close(); saved=tmp_path/'report.json'; saved.write_text(json.dumps(report))
    before=catalog.read_bytes()
    receipt=replay_saved_trace(catalog,saved,'q',node=node,script=replay)
    assert receipt['status']=='complete' and receipt['model_calls']==0
    assert receipt['evidence_count']==1
    assert catalog.read_bytes()==before
    import sys
    fake=tmp_path/'fake.py'
    fake.write_text('import json; print(json.dumps('+repr({'status':'complete','reason':None,'model_calls':False,'catalog_fingerprint':report['manifest']['corpus_revision'],'evidence_count':1,'trace_sha256':'a'*64})+'))')
    with pytest.raises(ValueError,match='replay outcome'):
        replay_saved_trace(catalog,saved,'q',node=sys.executable,script=fake)
    document.write_text('changed source')
    with pytest.raises(ValueError,match='source'):
        replay_saved_trace(catalog,saved,'q',node=node,script=replay)


def test_replay_saved_trace_rejects_wrong_catalog_without_writing(tmp_path):
    from quix_knowledge.switch_replay import replay_saved_trace
    catalog=tmp_path/'missing.db'; report=tmp_path/'report.json'; report.write_text('{}')
    with pytest.raises(ValueError):
        replay_saved_trace(catalog,report,'missing',node='/usr/bin/false',script='/tmp/missing')
    assert not catalog.exists()


def test_bounded_switch_trace_replays_with_recorded_choice_mode(tmp_path):
    from quix_knowledge.switch_replay import replay_saved_trace
    node=shutil.which('node');root=Path(__file__).resolve().parents[1]
    compare=root/'experiments/switch-navigation/src/compare.ts';replay=root/'experiments/switch-navigation/src/replay.ts'
    if not node or not (compare.parents[1]/'node_modules/@osolmaz/switch').exists(): pytest.skip('node or switch unavailable')
    document=tmp_path/'source.txt';document.write_text('retry after timeout')
    catalog=tmp_path/'catalog.db';db=open_catalog(catalog);ingest(db,document)
    tasks=[{'id':'q','query':'retry','role':'reviewer','role_version':'1'}]
    report=run_switch_comparison(db,tasks,switch_runner=NodeSwitchRunner(node,compare,mode='fixture'),packet_tokens=2000,count_tokens=len,tokenizer_name='fixture',limit=3,include_proposed=True,switch_choice_mode='bounded-v1')
    db.close();saved=tmp_path/'report.json';saved.write_text(json.dumps(report))
    assert replay_saved_trace(catalog,saved,'q',node=node,script=replay)['model_calls']==0
