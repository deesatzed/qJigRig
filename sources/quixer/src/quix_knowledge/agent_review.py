"""Make a condition-blind outcome-review packet and a separate local key."""
import random
import hashlib
import json
from datetime import date
from .hitm import _check_sources
from .labeling import prepare_review


def validate_review_sources(db, packet, tasks):
    """Ensure the source material presented to the reviewer matches the catalog."""
    _check_sources(db)
    expected=prepare_review(db,tasks,include_proposed=True,candidate_scope='sections_and_records')
    for key in ('schema','corpus_revision','task_contract_sha256','include_proposed','candidate_scope','candidates'):
        if packet.get(key)!=expected[key]:
            raise ValueError('review source candidate material or catalog changed')


def _contract(packet):
    immutable={key:value for key,value in packet.items() if key not in ('reviewer','reviewed_at','items')}
    immutable['items']=[{key:value for key,value in item.items() if key!='review'} for item in packet['items']]
    return hashlib.sha256(json.dumps(immutable,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _key_contract(key):
    immutable={name:value for name,value in key.items() if name!='key_contract_sha256'}
    return hashlib.sha256(json.dumps(immutable,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def seal_review_packet(packet,key):
    """Bind immutable task, source and output material to the separate local key."""
    key['packet_contract_sha256']=_contract(packet)
    key['key_contract_sha256']=_key_contract(key)


def prepare_agent_review(report, tasks, *, seed):
    if not isinstance(report,dict) or report.get('agent_kind')!='actual' or type(seed) is not int:
        raise ValueError('an actual-agent report and integer seed are required')
    if not isinstance(tasks,list) or any(not isinstance(t,dict) or not isinstance(t.get('id'),str) or not isinstance(t.get('query'),str) for t in tasks):
        raise ValueError('invalid tasks')
    by_id={t['id']:t['query'] for t in tasks}
    if len(by_id)!=len(tasks): raise ValueError('duplicate task')
    runs=report.get('runs')
    if not isinstance(runs,list): raise ValueError('invalid runs')
    seen=set(); completed=[]; missing=[]
    for run in runs:
        if not isinstance(run,dict) or run.get('task_id') not in by_id or run.get('condition') not in ('none','baseline','role','switch'):
            raise ValueError('invalid run identity')
        identity=(run['task_id'],run['condition'])
        if identity in seen: raise ValueError('duplicate run')
        seen.add(identity)
        if run.get('status')=='completed' and isinstance(run.get('output'),str): completed.append(run)
        else:
            status='invalid_output' if run.get('status')=='completed' else run.get('status','unknown')
            missing.append({'task_id':run['task_id'],'condition':run['condition'],'status':status})
    for task_id in by_id:
        for condition in ('none','baseline','role','switch'):
            if (task_id,condition) not in seen:
                missing.append({'task_id':task_id,'condition':condition,'status':'missing'})
    random.Random(seed).shuffle(completed)
    items=[]; conditions={}
    for index,run in enumerate(completed,1):
        blind_id=f'answer-{index:03d}'
        items.append({'blind_id':blind_id,'task_id':run['task_id'],'task':by_id[run['task_id']],'output':run['output'],'review':None})
        conditions[blind_id]={'task_id':run['task_id'],'condition':run['condition']}
    packet={'schema':'quix-agent-outcome-review-v1','reviewer':None,'reviewed_at':None,
             'rubric':{'correctness':'correct, partial, incorrect, or unknown',
                 'source_support':'supported, partial, unsupported, no_citations, or unknown',
                 'missing_evidence':'none, material, or unknown','task_completion':'complete, partial, incomplete, or unknown'},
             'items':items}
    key={'schema':'quix-agent-outcome-key-v1','seed':seed,'conditions':conditions,'missing':missing}
    seal_review_packet(packet,key)
    return packet,key


def compile_agent_review(packet,key):
    """Validate the blinded evidence and completed rubric before unblinding."""
    if not isinstance(packet,dict) or not isinstance(key,dict) or packet.get('schema')!='quix-agent-outcome-review-v1' or key.get('schema')!='quix-agent-outcome-key-v1':
        raise ValueError('invalid review schema')
    try:
        if _contract(packet)!=key.get('packet_contract_sha256'):
            raise ValueError('review contract changed')
        if _key_contract(key)!=key.get('key_contract_sha256'):
            raise ValueError('review key changed')
        reviewer=packet['reviewer']; reviewed_at=packet['reviewed_at']
        if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(reviewed_at,str): raise ValueError('reviewer and date required')
        date.fromisoformat(reviewed_at)
        mapping=key['conditions']; missing=key['missing']; items=packet['items']
        if not isinstance(mapping,dict) or not isinstance(missing,list) or not isinstance(items,list): raise ValueError('invalid review key')
        ids=[item['blind_id'] for item in items]
        if len(ids)!=len(set(ids)) or set(ids)!=set(mapping): raise ValueError('review key mismatch')
        candidates=packet.get('source_candidates')
        valid_sources={item['id'] for item in candidates} if isinstance(candidates,list) else None
        options={'correctness':{'correct','partial','incorrect','unknown'},'source_support':{'supported','partial','unsupported','no_citations','unknown'},
            'missing_evidence':{'none','material','unknown'},'task_completion':{'complete','partial','incomplete','unknown'}}
        outcomes=[]; identities=set()
        for item in items:
            review=item.get('review'); identity=mapping[item['blind_id']]
            if not isinstance(identity,dict) or identity.get('task_id')!=item['task_id'] or identity.get('condition') not in ('none','baseline','role','switch'):
                raise ValueError('review key mismatch')
            pair=(identity['task_id'],identity['condition'])
            if pair in identities: raise ValueError('duplicate review condition')
            identities.add(pair)
            if not isinstance(review,dict) or set(review)!=set(options)|{'explanation','source_ids'} or any(review[k] not in allowed for k,allowed in options.items()):
                raise ValueError('incomplete or invalid review')
            sources=review['source_ids']
            if not isinstance(review['explanation'],str) or not review['explanation'].strip() or not isinstance(sources,list) or any(not isinstance(s,str) or not s for s in sources) or len(set(sources))!=len(sources):
                raise ValueError('incomplete or invalid review')
            if valid_sources is not None and not set(sources)<=valid_sources: raise ValueError('unknown review source')
            outcomes.append({'task_id':pair[0],'condition':pair[1],'blind_id':item['blind_id'],'review':review})
        for entry in missing:
            if not isinstance(entry,dict) or not isinstance(entry.get('task_id'),str) or entry.get('condition') not in ('none','baseline','role','switch') or not isinstance(entry.get('status'),str) or not entry['status']:
                raise ValueError('invalid missing review key')
            pair=(entry['task_id'],entry['condition'])
            if pair in identities: raise ValueError('duplicate review key condition')
            identities.add(pair)
        all_tasks={task for task,_ in identities}
        if any((task,condition) not in identities for task in all_tasks for condition in ('none','baseline','role','switch')):
            raise ValueError('incomplete review key')
        completed_identities={(outcome['task_id'],outcome['condition']) for outcome in outcomes}
        tasks={task for task,_ in completed_identities}
        complete=sorted(task for task in tasks if all((task,c) in completed_identities for c in ('none','baseline','role','switch')))
        return {'schema':'quix-agent-reviewed-outcomes-v1','reviewer':reviewer.strip(),'reviewed_at':reviewed_at,
            'reviewer_independence':'self-reported; not verified','packet_contract_sha256':key['packet_contract_sha256'],
            'outcomes':outcomes,'complete_pairs':complete,'missing':missing}
    except (KeyError,TypeError) as exc:
        raise ValueError('invalid review contract') from exc
