"""Pair independently reviewed agent outcomes with their recorded run evidence."""
import copy
from collections import Counter
import hashlib
import json
import math

from .agent_review import compile_agent_review, prepare_agent_review
from .agent_process import validate_role_bindings
from .agent_study import CONDITIONS


def _number_or_unknown(value,name):
    if value is None: return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'invalid recorded {name}')
    return value


def validate_recorded_role_definitions(report,tasks,expected_roles):
    """Keep legacy unrecorded role purposes distinct from verified new metadata."""
    manifest=report.get('manifest',{})
    marker=manifest.get('planner_role_purpose_included')
    if marker is None:
        return 'not_recorded'
    if marker is not True or manifest.get('planner_prompt_contract')!='quix-planner-role-purpose-v1' or manifest.get('role_definitions')!=expected_roles:
        raise ValueError('recorded role definitions differ from study')
    validate_role_bindings(tasks,expected_roles)
    return 'recorded'


def validate_study_requests(report,packets,tasks):
    """Reconstruct serialized study requests, including any recorded role purpose."""
    runs=report.get('runs',[])
    if not any('study_request_sha256' in run for run in runs):
        if report.get('manifest',{}).get('planner_role_purpose_included') is True:
            raise ValueError('role-purpose study request hashes are missing')
        return 'not_recorded'
    task_by_id={task['id']:task for task in tasks}
    by_identity={(row['task_id'],row['condition']):row['packet'] for row in packets}
    maximum=report.get('max_input_characters')
    if type(maximum) is not int or maximum<1: raise ValueError('invalid study request budget')
    roles=report.get('manifest',{}).get('role_definitions') if report.get('manifest',{}).get('planner_role_purpose_included') is True else None
    if roles is not None: validate_role_bindings(tasks,roles)
    before_request={'context_unavailable','adapter_error','missing'}
    for run in runs:
        digest=run.get('study_request_sha256')
        if digest is None:
            if run.get('status') not in before_request: raise ValueError('study request record missing')
            continue
        task=task_by_id.get(run.get('task_id')); condition=run.get('condition')
        if task is None or condition not in CONDITIONS: raise ValueError('invalid study request identity')
        context=None if condition=='none' else by_identity.get((task['id'],condition))
        if condition!='none' and context is None: raise ValueError('study request context missing')
        request={'task_id':task['id'],'query':task['query'],'role':task['role'],'role_version':task['role_version'],
            'context':context,'max_input_characters':maximum}
        if roles is not None: request['role_purpose']=roles[task['role']]['purpose']
        encoded=json.dumps(request,ensure_ascii=False,separators=(',',':'))
        if run.get('study_request_characters')!=len(encoded) or digest!=hashlib.sha256(encoded.encode('utf-8')).hexdigest():
            raise ValueError('study request differs from recorded input')
    return 'verified'


def validate_recorded_packets(report,packets,tasks):
    """Check saved request packets against per-run hashes and task/corpus identity."""
    if not isinstance(packets,list): raise ValueError('invalid saved packets')
    task_by_id={task['id']:task for task in tasks}
    revision=report.get('manifest',{}).get('corpus_revision')
    if not isinstance(revision,str) or not revision: raise ValueError('missing packet corpus revision')
    by_identity={}
    for row in packets:
        if not isinstance(row,dict) or row.get('task_id') not in task_by_id or row.get('condition') not in ('baseline','role','switch') or not isinstance(row.get('packet'),dict):
            raise ValueError('invalid saved packet identity')
        identity=(row['task_id'],row['condition']); packet=row['packet']; task=task_by_id[row['task_id']]
        if identity in by_identity or packet.get('catalog_fingerprint')!=revision or any(packet.get(k)!=task.get(k if k!='task' else 'query') for k in ('task','role','role_version')):
            raise ValueError('saved packet identity mismatch')
        if not isinstance(packet.get('results'),list): raise ValueError('invalid saved packet results')
        by_identity[identity]=packet
    for run in report.get('runs',[]):
        provenance=run.get('context_provenance')
        if provenance is None: continue
        identity=(run.get('task_id'),run.get('condition')); packet=by_identity.get(identity)
        if not isinstance(provenance,dict) or packet is None: raise ValueError('missing recorded packet')
        digest=hashlib.sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        try:
            sources=[{key:item.get(key) for key in ('id','revision','path')} for item in packet['results']]
        except AttributeError as exc:
            raise ValueError('invalid recorded packet') from exc
        if provenance.get('packet_sha256')!=digest or provenance.get('catalog_fingerprint')!=revision or provenance.get('sources')!=sources or provenance.get('omitted_count')!=packet.get('omitted_count'):
            raise ValueError('recorded packet differs from run provenance')


def summarize_retrieval_accounting(comparison,preparation):
    """Keep indexing and switch usage separate from planner-call accounting."""
    queries=comparison['variants']['switch']['queries']
    costs=[_number_or_unknown(q.get('reported_cost'),'switch cost') for q in queries.values()]
    requests=[q.get('physical_requests') for q in queries.values()]
    if any(value is not None and (type(value) is not int or value < 0) for value in requests):
        raise ValueError('invalid switch request count')
    known=sum(value for value in costs if value is not None)
    return {'switch':{'known_reported_usd':known,'total_reported_usd':known if all(x is not None for x in costs) else None,
        'unknown_cost_queries':sum(x is None for x in costs),
        'physical_requests':sum(requests) if all(x is not None for x in requests) else None,
        'unknown_request_queries':sum(x is None for x in requests)},
        'role_indexing':copy.deepcopy(preparation.get('role_scoring')),
        'note':'These retrieval and indexing amounts are separate from planner costs; reused retrieval calls are counted once.'}


def analyze_agent_outcomes(packet,key,report,tasks):
    """Preserve per-task reviews, failures and accounting without selecting a winner."""
    compiled=compile_agent_review(packet,key)
    expected,expected_key=prepare_agent_review(report,tasks,seed=key['seed'])
    if key.get('conditions')!=expected_key['conditions'] or key.get('missing')!=expected_key['missing']:
        raise ValueError('review key does not match recorded runs')
    actual_items=[{name:value for name,value in item.items() if name!='review'} for item in packet['items']]
    expected_items=[{name:value for name,value in item.items() if name!='review'} for item in expected['items']]
    if actual_items!=expected_items:
        raise ValueError('reviewed output or task differs from recorded runs')
    reviews={(row['task_id'],row['condition']):row['review'] for row in compiled['outcomes']}
    missing={(row['task_id'],row['condition']):row['status'] for row in compiled['missing']}
    recorded={(row['task_id'],row['condition']):row for row in report['runs']}
    costs=[]; paired=[]
    for task in tasks:
        conditions={}
        for condition in CONDITIONS:
            identity=(task['id'],condition)
            run=recorded.get(identity)
            recorded_status=run.get('status','unknown') if run else 'missing'
            status=missing.get(identity,recorded_status)
            cost=_number_or_unknown(run.get('reported_cost') if run else None,'cost')
            elapsed=_number_or_unknown(run.get('elapsed_seconds') if run else None,'elapsed time')
            costs.append(cost)
            conditions[condition]={'status':status,'recorded_status':recorded_status,'review':copy.deepcopy(reviews.get(identity)),
                'elapsed_seconds':elapsed,'reported_cost_usd':cost,
                'call':copy.deepcopy(run.get('call')) if run else None,
                'context_provenance':copy.deepcopy(run.get('context_provenance')) if run else None}
        paired.append({'task_id':task['id'],'query':task['query'],'role':task['role'],'role_version':task['role_version'],
            'split':task.get('split','unassigned'),'conditions':conditions})
    unknown=sum(value is None for value in costs)
    known=sum(value for value in costs if value is not None)
    condition_counts={}
    for condition in CONDITIONS:
        rows=[task['conditions'][condition] for task in paired]
        reviewed=[row['review'] for row in rows if row['review'] is not None]
        condition_counts[condition]={'scheduled':len(rows),'reviewed':len(reviewed),
            'statuses':dict(Counter(row['status'] for row in rows)),
            **{field:dict(Counter(review[field] for review in reviewed)) for field in ('correctness','source_support','missing_evidence','task_completion')}}
    limitations=['Review independence is self-reported, not authenticated.',
        'No statistical confidence or causal improvement is established by these records.',
        'Missing and failed conditions remain in the paired results.']
    recorded_limits=report.get('manifest',{}).get('limitations')
    if isinstance(recorded_limits,str) and recorded_limits.strip():
        limitations.append('Recorded study limitations: '+recorded_limits)
    return {'schema':'quix-agent-paired-analysis-v1','reviewer':compiled['reviewer'],'reviewed_at':compiled['reviewed_at'],
        'reviewer_independence':compiled['reviewer_independence'],'packet_contract_sha256':compiled['packet_contract_sha256'],
        'complete_pairs':compiled['complete_pairs'],'tasks':paired,'condition_counts':condition_counts,
        'cost':{'known_subtotal_usd':known,'unknown_count':unknown,'total_usd':known if not unknown else None,
            'scope':'planner calls only; retrieval, indexing and local compute are separate'},
        'source_verification':'not checked by this in-memory analysis',
        'limitations':limitations}
