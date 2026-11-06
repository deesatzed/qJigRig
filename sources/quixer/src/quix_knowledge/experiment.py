"""Reproducible comparative runs over an immutable catalog snapshot."""
from datetime import datetime, timezone
import json
import time

from .evaluate import evaluate
from .retrieve import search
from .store import corpus_fingerprint

_VARIANTS = ('baseline', 'topic', 'decision', 'role')


def _indexing_receipts(db, receipt_ids):
    if receipt_ids is None:
        return None
    if len(set(receipt_ids)) != len(receipt_ids):
        raise ValueError('duplicate indexing receipt IDs')
    receipts = []
    for receipt_id in receipt_ids:
        row = db.execute('SELECT * FROM decision_receipts WHERE id=?',(receipt_id,)).fetchone()
        if row is None:
            raise ValueError('missing indexing receipt')
        receipt = dict(row)
        detail = json.loads(receipt['detail'])
        if 'source_id' in detail:
            source = db.execute('SELECT status FROM sources WHERE id=?',(detail['source_id'],)).fetchone()
        elif 'section_id' in detail:
            source = db.execute('SELECT sources.status FROM sections JOIN sources ON sections.source_id=sources.id WHERE sections.id=?',(detail['section_id'],)).fetchone()
        elif 'generated_index_id' in detail:
            source = db.execute('SELECT sources.status FROM generated_index JOIN sections ON generated_index.section_id=sections.id JOIN sources ON sections.source_id=sources.id WHERE generated_index.id=?',(detail['generated_index_id'],)).fetchone()
        elif 'record_id' in detail:
            source = db.execute("""SELECT 'current' AS status FROM records r WHERE r.id=? AND r.status IN ('proposed','current') AND NOT EXISTS
                (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""",(detail['record_id'],)).fetchone()
        else:
            raise ValueError('receipt is not an indexing decision')
        if source is None or source['status'] != 'current':
            raise ValueError('indexing receipt does not refer to a current source')
        receipts.append(receipt)
    details = [json.loads(row['detail']) for row in receipts]
    def total(key):
        values = [(d.get('usage') or {}).get(key) for d in details]
        return sum(values) if values and all(isinstance(v,(int,float)) and not isinstance(v,bool) and v >= 0 for v in values) else None
    return {'decision_calls':len(receipts),'unknown_decisions':sum(r['outcome']=='unknown' for r in receipts),'reported_cost':total('cost'),'input_tokens':total('input_tokens'),'receipts':receipts}


def run_experiment(db, tasks, *, provider=None, context_chars=4000, context_tokens=None, packet_tokens=None, count_tokens=None, tokenizer_name=None, limit=10, label_provenance=None, configuration=None, include_proposed=False, indexing_receipt_ids=None, ranking='overlap', embedder=None, matched_candidates=False):
    if not tasks or limit < 0 or (context_chars is not None and context_chars < 0):
        raise ValueError('tasks and nonnegative budgets are required')
    if context_tokens is not None and (context_chars is not None or context_tokens < 0 or count_tokens is None or not tokenizer_name):
        raise ValueError('token budget requires a named counter and excludes character budget')
    if packet_tokens is not None and (context_chars is not None or context_tokens is not None or packet_tokens < 0 or count_tokens is None or not tokenizer_name):
        raise ValueError('packet token budget requires a named counter and excludes other budgets')
    if context_tokens is None and context_chars is None and packet_tokens is None:
        raise ValueError('a context budget is required')
    if ranking == 'hybrid' and embedder is None:
        raise ValueError('hybrid ranking requires an explicit embedder')
    ids = [task.get('id') for task in tasks]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('task IDs must be nonempty and unique')
    if any(not isinstance(task.get('query'),str) or not task['query'].strip() for task in tasks):
        raise ValueError('each task needs a query')
    if packet_tokens is not None and any(not isinstance(t.get('role'),str) or not t['role'].strip() or not isinstance(t.get('role_version'),str) or not t['role_version'].strip() for t in tasks):
        raise ValueError('packet tasks require role and role_version')
    if any(t.get('labels') is not None and (not isinstance(t['labels'],list) or any(not isinstance(x,str) or not x for x in t['labels'])) for t in tasks):
        raise ValueError('labels must be null or a list of nonempty IDs')
    if any(t.get('split','unassigned') not in ('train','development','held_out','unassigned') for t in tasks):
        raise ValueError('task split must be train, development, held_out or unassigned')
    fingerprint = corpus_fingerprint(db)
    indexing = _indexing_receipts(db,indexing_receipt_ids)
    labels = {t['id']:t.get('labels') for t in tasks}
    available = {row[0] for row in db.execute("SELECT sections.id FROM sections JOIN sources ON sections.source_id=sources.id WHERE sources.status='current'")}
    available.update(row[0] for row in db.execute("SELECT id FROM records WHERE status IN ('current','proposed')"))
    available.update(row[0] for row in db.execute("SELECT generated_index.id FROM generated_index JOIN sections ON generated_index.section_id=sections.id JOIN sources ON sections.source_id=sources.id WHERE sources.status='current' AND generated_index.status IN ('accepted','proposed')"))
    missing = {task['id']:sorted(set(task['labels'])-available) for task in tasks if task.get('labels')}
    missing = {key:value for key,value in missing.items() if value}
    generated = {row['id']:row['status'] for row in db.execute("SELECT generated_index.id,generated_index.status FROM generated_index JOIN sections ON generated_index.section_id=sections.id JOIN sources ON sections.source_id=sources.id WHERE sources.status='current' AND generated_index.status IN ('accepted','proposed')")}
    variants = {}
    for variant in _VARIANTS:
        unavailable = {task['id']:sorted(label for label in set(task['labels']) if label in generated and (matched_candidates or variant == 'baseline' or (generated[label] == 'proposed' and not include_proposed))) for task in tasks if task.get('labels')}
        unavailable = {key:value for key,value in unavailable.items() if value}
        queries, results = {}, {}
        for task in tasks:
            if corpus_fingerprint(db) != fingerprint:
                raise RuntimeError('catalog changed during experiment')
            previous = db.execute('SELECT COALESCE(MAX(id),0) FROM decision_receipts').fetchone()[0]
            started = time.monotonic()
            rows = search(db, task['query'], variant=variant, role=task.get('role'), role_version=task.get('role_version'), provider=provider, limit=limit, context_chars=context_chars, context_tokens=context_tokens,count_tokens=count_tokens,include_proposed=include_proposed,ranking=ranking,embedder=embedder,include_generated=not matched_candidates)
            packet = None
            packet_count = None
            if packet_tokens is not None:
                from .context import build_context_packet, serialize_packet
                packet = build_context_packet(task['query'],task['role'],task['role_version'],rows,budget=packet_tokens,count_tokens=count_tokens,tokenizer_name=tokenizer_name,catalog_fingerprint=fingerprint)
                packet_count = count_tokens(serialize_packet(packet))
                rows = packet['results']
            elapsed = time.monotonic() - started
            receipts = [dict(row) for row in db.execute('SELECT * FROM decision_receipts WHERE id>? ORDER BY id',(previous,))]
            details = [json.loads(r['detail']) for r in receipts]
            costs = [(d.get('usage') or {}).get('cost') for d in details]
            cost = sum(costs) if costs and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in costs) else None
            results[task['id']] = rows
            queries[task['id']] = {'elapsed_seconds': elapsed, 'decision_calls':len(receipts), 'decision_failures':sum(r['outcome']=='unknown' for r in receipts), 'reported_cost':cost, 'returned_body_chars':sum(len(r['body']) for r in rows), 'returned_body_tokens':sum(count_tokens(r['body']) for r in rows) if context_tokens is not None or packet_tokens is not None else None, 'packet_token_count':packet_count,'context_packet':packet, 'missing_label_ids':missing.get(task['id'],[]), 'unavailable_label_ids':unavailable.get(task['id'],[]), 'receipts':receipts, 'results':rows}
        by_split = {}
        for split in sorted({task.get('split','unassigned') for task in tasks}):
            split_ids = {task['id'] for task in tasks if task.get('split','unassigned') == split}
            by_split[split] = evaluate({key:labels[key] for key in split_ids},{key:results[key] for key in split_ids},set(missing) & split_ids,set(unavailable) & split_ids)
        variants[variant] = {'metrics':evaluate(labels,results,missing,unavailable), 'metrics_by_split':by_split, 'queries':queries}
    if corpus_fingerprint(db) != fingerprint:
        raise RuntimeError('catalog changed during experiment')
    eligible = sorted(task['id'] for task in tasks if task.get('labels') is not None and task['id'] not in missing and all(not variant['queries'][task['id']]['unavailable_label_ids'] for variant in variants.values()))
    def common_metrics(task_ids):
        return {name:evaluate({key:labels[key] for key in task_ids},{key:variant['queries'][key]['results'] for key in task_ids}) for name,variant in variants.items()}
    by_split = {}
    for split in sorted({task.get('split','unassigned') for task in tasks}):
        split_ids = [task['id'] for task in tasks if task.get('split','unassigned') == split and task['id'] in eligible]
        split_ids.sort()
        by_split[split] = {'task_ids':split_ids,'metrics':common_metrics(split_ids)}
    common_comparison = {'eligible_task_ids':eligible,'excluded_task_ids':sorted(set(ids)-set(eligible)),'metrics':common_metrics(eligible),'by_split':by_split}
    provider_info = None
    if provider is not None:
        provider_info = {'adapter':type(provider).__name__,'configured_model':getattr(getattr(provider,'settings',None),'model',None),'thresholds':getattr(provider,'thresholds',None),'prompt_version':getattr(provider,'prompt_version',None),'stability_trials':getattr(provider,'trials',None)}
    return {'manifest':{'created_at':datetime.now(timezone.utc).isoformat(), 'corpus_revision':fingerprint, 'tasks':tasks, 'label_provenance':label_provenance, 'provider_configured':provider is not None, 'provider':provider_info, 'limit':limit, 'ranking':ranking, 'embedding':getattr(embedder,'metadata',None), 'context_chars':context_chars, 'context_tokens':context_tokens, 'packet_tokens':packet_tokens, 'tokenizer':tokenizer_name, 'include_proposed':include_proposed, 'candidate_scope':'sections_and_records' if matched_candidates else 'variant_specific', 'indexing':indexing, 'configuration':configuration}, 'variants':variants, 'common_comparison':common_comparison}

def run_reviewed_experiment(db, reviewed, **kwargs):
    if not isinstance(reviewed,dict) or reviewed.get('schema') != 'quix-reviewed-labels-v1':
        raise ValueError('invalid reviewed-label artifact')
    if reviewed.get('corpus_revision') != corpus_fingerprint(db):
        raise ValueError('reviewed labels do not match the current catalog')
    if 'label_provenance' in kwargs or 'include_proposed' in kwargs:
        raise ValueError('review provenance and proposal scope come from the reviewed artifact')
    if type(reviewed.get('include_proposed')) is not bool or not isinstance(reviewed.get('label_provenance'),dict):
        raise ValueError('invalid reviewed-label provenance or proposal scope')
    scope = reviewed.get('candidate_scope','variant_specific')
    if scope not in ('variant_specific','sections_and_records'):
        raise ValueError('invalid reviewed-label candidate scope')
    if scope == 'sections_and_records' and kwargs.get('matched_candidates') is not True:
        raise ValueError('reviewed labels require matched candidates')
    return run_experiment(db,reviewed['tasks'],label_provenance=reviewed['label_provenance'],include_proposed=reviewed['include_proposed'],**kwargs)
