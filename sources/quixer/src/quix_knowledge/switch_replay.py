"""Reconstruct and replay a saved switch trace against a read-only catalog."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from .hitm import _check_sources
from .store import corpus_fingerprint
from .switch_snapshot import build_snapshot


def replay_saved_trace(catalog,report_path,task_id,*,node,script,timeout=30):
    if not isinstance(task_id,str) or not task_id or not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0 < timeout <= 60:
        raise ValueError('invalid replay request')
    try:
        raw=Path(report_path).read_bytes()
        if len(raw)>24_000_000: raise ValueError('report exceeds input limit')
        report=json.loads(raw)
        manifest=report['manifest']; config=manifest['switch']
        tasks=[task for task in manifest['tasks'] if task['id']==task_id]
        if len(tasks)!=1: raise ValueError('task is not unique')
        task=tasks[0]; query=report['variants']['switch']['queries'][task_id]
        trace=query['switch_trace']
        scope=manifest['candidate_scope']
        if scope not in ('sections_and_records','variant_specific') or type(manifest['include_proposed']) is not bool or not isinstance(trace,list) or not trace:
            raise ValueError('unsupported replay scope or missing trace')
        db=sqlite3.connect(Path(catalog).resolve().as_uri()+'?mode=ro',uri=True)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON')
            if db.execute('PRAGMA user_version').fetchone()[0]!=7 or corpus_fingerprint(db)!=manifest['corpus_revision']:
                raise ValueError('catalog differs from recorded corpus')
            snapshot=build_snapshot(db,task=task['query'],role=task['role'],role_version=task['role_version'],
                max_steps=config['max_steps'],max_model_calls=config['max_model_calls'],max_characters=config['view_characters'],
                include_proposed=manifest['include_proposed'],matched_candidates=scope=='sections_and_records',
                choice_mode=None if config.get('choice_mode','legacy')=='legacy' else config.get('choice_mode'))
            payload=json.dumps({'snapshot':snapshot,'trace':trace},ensure_ascii=False,separators=(',',':')).encode()
            if len(payload)>24_000_000: raise ValueError('replay input exceeds limit')
            env={'PATH':os.environ.get('PATH','/usr/bin:/bin')}
            with tempfile.TemporaryFile() as output:
                result=subprocess.run([str(node),str(Path(script).resolve())],input=payload,stdout=output,stderr=subprocess.DEVNULL,env=env,timeout=timeout,check=False)
                if result.returncode!=0 or output.tell()>100_000: raise ValueError('recorded trace could not be replayed')
                output.seek(0); receipt=json.load(output)
            _check_sources(db)
            if corpus_fingerprint(db)!=manifest['corpus_revision']:
                raise ValueError('catalog changed during replay')
            if (not isinstance(receipt,dict) or type(receipt.get('model_calls')) is not int or receipt['model_calls']!=0 or receipt.get('catalog_fingerprint')!=manifest['corpus_revision']
                    or receipt.get('status')!=query.get('switch_status') or receipt.get('reason')!=query.get('switch_reason')):
                raise ValueError('replay outcome differs from recorded trace')
            return receipt
        finally:
            db.close()
    except (OSError,sqlite3.Error,KeyError,TypeError,json.JSONDecodeError,subprocess.TimeoutExpired) as exc:
        raise ValueError('saved replay inputs unavailable or invalid') from exc
