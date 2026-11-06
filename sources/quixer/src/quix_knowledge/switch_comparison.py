"""Matched context-packet experiment with a bounded switch runner."""
import math
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from .context import build_context_packet, serialize_packet
from .evaluate import evaluate
from .experiment import run_experiment
from .hitm import _check_sources
from .store import corpus_fingerprint
from .switch_snapshot import build_snapshot


class NodeSwitchRunner:
    """Invoke the configured local switch adapter without a shell or credentials in argv."""
    def __init__(self, node, script, *, mode, env_file='/Volumes/WS4TB/QUIX/.env', model_slot=2, timeout=60, model=None):
        if mode not in ('fixture','openrouter') or type(model_slot) is not int or model_slot not in (1,2,3,4) or not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0 < timeout <= 60:
            raise ValueError('invalid switch runner configuration')
        if model is not None and (not isinstance(model,str) or not model.strip()): raise ValueError('invalid decision model')
        self.model=model
        self.node, self.script, self.mode = str(node),str(Path(script).resolve()),mode
        self.env_file, self.model_slot, self.timeout = str(env_file),model_slot,timeout

    def __call__(self, snapshot):
        payload=json.dumps(snapshot,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        if len(payload)>24_000_000:
            raise ValueError('switch snapshot exceeds input limit')
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'QUIX_OPENROUTER_ENV':self.env_file,'QUIX_MODEL_SLOT':str(self.model_slot)}
        if self.model is not None: env['QUIX_DECISION_MODEL']=self.model
        with tempfile.TemporaryFile() as output:
            result=subprocess.run([self.node,self.script,self.mode],input=payload,stdout=output,stderr=subprocess.DEVNULL,env=env,timeout=self.timeout,check=False)
            if result.returncode != 0 or output.tell()>24_000_000:
                raise RuntimeError('switch process failed or exceeded output limit')
            output.seek(0)
            parsed=json.load(output)
        if not isinstance(parsed,dict):
            raise ValueError('invalid switch response')
        return parsed


def _selected_rows(snapshot, result, limit):
    if not isinstance(result,dict) or result.get('status') != 'complete':
        return None
    evidence = (result.get('state') or {}).get('evidence')
    if not isinstance(evidence,list) or not evidence or len(evidence)>limit:
        return None
    candidates = {item['id']:item for item in snapshot['candidates']}
    seen, rows = set(), []
    for item in evidence:
        if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not isinstance(item.get('text'),str) or not item['text'] or type(item.get('truncated')) is not bool:
            return None
        candidate = candidates.get(item['id'])
        if candidate is None or item['id'] in seen or not candidate['body'].startswith(item['text']):
            return None
        if candidate['record_type'] == 'agent_record' and (candidate['unsupported'] or candidate['evidence_status'] != 'current'):
            return None
        seen.add(item['id'])
        row = dict(candidate,body=item['text'],context_truncated=item['truncated'] or item['text'] != candidate['body'])
        annotation = candidate.get('role_annotation')
        if annotation:
            row.update(role_score=annotation['score'],role_score_status=annotation['status'],role_score_method=annotation['method'],role_score_model=annotation['model'],role_score_scope=annotation['scope'])
        rows.append(row)
    return rows


def _usage(receipts):
    if not isinstance(receipts,list):
        return None
    values = [(receipt.get('usage') or {}).get('cost') if isinstance(receipt,dict) else None for receipt in receipts]
    if not values or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0 for x in values):
        return None
    return sum(values)


def run_switch_comparison(db, tasks, *, switch_runner, packet_tokens, count_tokens, tokenizer_name, limit=3, provider=None, include_proposed=False, ranking='bm25', label_provenance=None, switch_view_characters=5000, switch_max_steps=5, switch_max_model_calls=10, switch_choice_mode=None):
    if not callable(switch_runner):
        raise ValueError('a switch runner is required')
    report = run_experiment(db,tasks,provider=provider,context_chars=None,packet_tokens=packet_tokens,count_tokens=count_tokens,tokenizer_name=tokenizer_name,limit=limit,include_proposed=include_proposed,ranking=ranking,label_provenance=label_provenance,matched_candidates=True)
    fingerprint = report['manifest']['corpus_revision']
    report['manifest']['switch'] = {'view_characters':switch_view_characters,'max_steps':switch_max_steps,'max_model_calls':switch_max_model_calls,'fallback':'baseline','packet_budget_matches':True,'full_model_prompt_budget_matches':False,'choice_mode':switch_choice_mode or 'legacy'}
    labels = {task['id']:task.get('labels') for task in tasks}
    queries, results = {}, {}
    for task in tasks:
        snapshot = build_snapshot(db,task=task['query'],role=task['role'],role_version=task['role_version'],max_steps=switch_max_steps,max_model_calls=switch_max_model_calls,max_characters=switch_view_characters,include_proposed=include_proposed,matched_candidates=True,choice_mode=switch_choice_mode)
        if snapshot['catalog_fingerprint'] != fingerprint:
            raise RuntimeError('catalog changed during experiment')
        started = time.monotonic()
        try:
            result = switch_runner(snapshot)
        except Exception:
            result = {'status':'insufficient_evidence','reason':'runner_error','state':{'evidence':[]},'receipts':None}
        _check_sources(db)
        if corpus_fingerprint(db) != fingerprint:
            raise RuntimeError('catalog changed during experiment')
        rows = _selected_rows(snapshot,result,limit)
        fallback = None
        if rows is None:
            fallback = 'invalid_switch_result' if isinstance(result,dict) and result.get('status') == 'complete' else 'switch_insufficient_evidence'
            packet = report['variants']['baseline']['queries'][task['id']]['context_packet']
        else:
            packet = build_context_packet(task['query'],task['role'],task['role_version'],rows,budget=packet_tokens,count_tokens=count_tokens,tokenizer_name=tokenizer_name,catalog_fingerprint=fingerprint)
        receipts = result.get('receipts') if isinstance(result,dict) else None
        results[task['id']] = packet['results']
        queries[task['id']] = {'results':packet['results'],'context_packet':packet,'packet_token_count':count_tokens(serialize_packet(packet)),
            'elapsed_seconds':time.monotonic()-started,'fallback_reason':fallback,'switch_status':result.get('status') if isinstance(result,dict) else None,
            'switch_reason':result.get('reason') if isinstance(result,dict) else None,'physical_requests':len(receipts) if isinstance(receipts,list) else None,'reported_cost':_usage(receipts),
            'switch_provider':result.get('provider') if isinstance(result,dict) else None,'switch_decision_detail':result.get('decision_detail') if isinstance(result,dict) else None,
            'switch_logical_calls':result.get('logical_calls') if isinstance(result,dict) else None,
            'switch_trace':result.get('trace') if isinstance(result,dict) else None,'switch_model_requests':result.get('model_requests') if isinstance(result,dict) else None,'switch_receipts':receipts,
            'missing_label_ids':report['variants']['baseline']['queries'][task['id']]['missing_label_ids'],
            'unavailable_label_ids':report['variants']['baseline']['queries'][task['id']]['unavailable_label_ids']}
    missing = {key for key,q in queries.items() if q['missing_label_ids']}
    unavailable = {key for key,q in queries.items() if q['unavailable_label_ids']}
    split_metrics = {}
    for split in sorted({task.get('split','unassigned') for task in tasks}):
        ids = {task['id'] for task in tasks if task.get('split','unassigned') == split}
        split_metrics[split] = evaluate({key:labels[key] for key in ids},{key:results[key] for key in ids},missing & ids,unavailable & ids)
    report['variants']['switch'] = {'metrics':evaluate(labels,results,missing,unavailable),'metrics_by_split':split_metrics,'queries':queries}
    common = report['common_comparison']
    ids = common['eligible_task_ids']
    common['metrics']['switch'] = evaluate({key:labels[key] for key in ids},{key:results[key] for key in ids})
    for split in common['by_split'].values():
        split_ids = split['task_ids']
        split['metrics']['switch'] = evaluate({key:labels[key] for key in split_ids},{key:results[key] for key in split_ids})
    return report
