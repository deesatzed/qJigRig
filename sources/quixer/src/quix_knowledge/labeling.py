"""Prepare blind source-bound review packets and validate returned labels."""
from datetime import date, datetime, timezone
import hashlib
import json

from .store import corpus_fingerprint, validate_retrievable_ids

_TASK_FIELDS = ('id','query','role','role_version','split')


def _task_hash(tasks):
    raw = json.dumps([{key:task[key] for key in _TASK_FIELDS} for task in tasks],sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def _candidates(db, include_proposed, candidate_scope='variant_specific'):
    validate_retrievable_ids(db)
    rows = db.execute("""SELECT s.id,'section' AS record_type,s.title,s.body,s.source_id,s.start_line,s.end_line,
        p.page_start,p.page_end,src.path,src.revision,src.status AS source_status
        FROM sections s JOIN sources src ON src.id=s.source_id LEFT JOIN section_pages p ON p.section_id=s.id
        WHERE src.status='current' ORDER BY s.id""").fetchall()
    candidates = [dict(row) for row in rows]
    statuses = ('accepted','proposed') if include_proposed else ('accepted',)
    rows = [] if candidate_scope == 'sections_and_records' else db.execute("""SELECT g.id,'generated_index' AS record_type,g.title,g.body,g.section_id AS source_section_id,
        g.start_offset,g.end_offset,g.status AS index_status,s.source_id,p.page_start,p.page_end,src.path,src.revision,src.status AS source_status
        FROM generated_index g JOIN sections s ON s.id=g.section_id JOIN sources src ON src.id=s.source_id
        LEFT JOIN section_pages p ON p.section_id=s.id WHERE src.status='current' AND g.status IN (%s) ORDER BY g.id""" % ','.join('?'*len(statuses)),statuses).fetchall()
    candidates.extend(dict(row) for row in rows)
    for row in db.execute("SELECT id,kind AS title,body,status,producer,output_ref FROM records WHERE status IN ('current','proposed') ORDER BY id"):
        item = dict(row)
        refs = db.execute('SELECT e.section_id,src.status FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources src ON src.id=s.source_id WHERE e.record_id=? ORDER BY e.section_id',(item['id'],)).fetchall()
        item['record_type'] = 'agent_record'
        item['output_ref_status'] = 'unverified' if item['output_ref'] else None
        item['evidence'] = [ref['section_id'] for ref in refs]
        item['evidence_status'] = 'unsupported' if not refs else 'stale' if any(ref['status'] != 'current' for ref in refs) else 'current'
        candidates.append(item)
    return sorted(candidates,key=lambda item:item['id'])


def prepare_review(db, tasks, *, include_proposed=False, candidate_scope='variant_specific'):
    if not isinstance(tasks,list) or not tasks:
        raise ValueError('a nonempty task list is required')
    if candidate_scope not in ('variant_specific','sections_and_records'):
        raise ValueError('invalid candidate scope')
    prepared = []
    for task in tasks:
        if not isinstance(task,dict) or any(not isinstance(task.get(k),str) or not task[k].strip() for k in ('id','query','role','role_version')):
            raise ValueError('task ID, query, role and role version are required')
        split = task.get('split','unassigned')
        if split not in ('train','development','held_out','unassigned'):
            raise ValueError('invalid task split')
        prepared.append({'id':task['id'],'query':task['query'],'role':task['role'],'role_version':task['role_version'],'split':split,'labels':None,'reviewed':False,'missing_reason':None})
    if len({task['id'] for task in prepared}) != len(prepared):
        raise ValueError('task IDs must be unique')
    return {'schema':'quix-blind-review-v1','corpus_revision':corpus_fingerprint(db),'task_contract_sha256':_task_hash(prepared),'include_proposed':include_proposed,'candidate_scope':candidate_scope,'reviewer':None,'candidates':_candidates(db,include_proposed,candidate_scope),'tasks':prepared}


def compile_review(db, packet):
    if not isinstance(packet,dict) or packet.get('schema') != 'quix-blind-review-v1':
        raise ValueError('invalid review packet')
    if packet.get('corpus_revision') != corpus_fingerprint(db):
        raise ValueError('catalog changed since packet preparation')
    reviewer = packet.get('reviewer')
    if not isinstance(reviewer,str) or not reviewer.strip():
        raise ValueError('reviewer is required')
    tasks = packet.get('tasks')
    if not isinstance(tasks,list) or not tasks or any(not isinstance(task,dict) or any(key not in task for key in _TASK_FIELDS) for task in tasks):
        raise ValueError('invalid task contract')
    if _task_hash(tasks) != packet.get('task_contract_sha256'):
        raise ValueError('task contract changed')
    if type(packet.get('include_proposed')) is not bool:
        raise ValueError('invalid proposal setting')
    scope = packet.get('candidate_scope','variant_specific')
    if scope not in ('variant_specific','sections_and_records'):
        raise ValueError('invalid candidate scope')
    expected = _candidates(db,packet['include_proposed'],scope)
    if packet.get('candidates') != expected:
        raise ValueError('candidate material changed')
    valid_ids = {item['id'] for item in expected}
    compiled = []
    dated = undated = 0
    for task in tasks:
        labels = task.get('labels')
        reviewed_at=task.get('reviewed_at')
        if type(task.get('reviewed')) is not bool:
            raise ValueError('each task needs a reviewed flag')
        if not task['reviewed']:
            if labels is not None or reviewed_at is not None:
                raise ValueError('unreviewed tasks must have null labels and review date')
        else:
            if not isinstance(labels,list) or any(not isinstance(x,str) or not x for x in labels) or len(set(labels)) != len(labels):
                raise ValueError('reviewed labels must be unique IDs')
            if not set(labels).issubset(valid_ids):
                raise ValueError('unknown candidate ID')
            if not labels and (not isinstance(task.get('missing_reason'),str) or not task['missing_reason'].strip()):
                raise ValueError('unanswerable task requires a reason')
            if reviewed_at is None:
                undated+=1
            else:
                try:
                    if not isinstance(reviewed_at,str) or date.fromisoformat(reviewed_at).isoformat()!=reviewed_at:
                        raise ValueError
                except ValueError:
                    raise ValueError('invalid review date') from None
                dated+=1
        compiled.append({key:task[key] for key in _TASK_FIELDS} | {'labels':labels,'missing_reason':task.get('missing_reason'),'reviewed_at':reviewed_at})
    return {'schema':'quix-reviewed-labels-v1','corpus_revision':packet['corpus_revision'],'include_proposed':packet['include_proposed'],'candidate_scope':scope,'tasks':compiled,'label_provenance':{'reviewer':reviewer.strip(),'compiled_at':datetime.now(timezone.utc).isoformat(),'identity_independence':'self-reported; not verified','reviewed_with_date':dated,'reviewed_without_date':undated,'review_date_semantics':'provided in packet; not independently verified'}}
