"""Isolated paired agent-study orchestration; injected functions own all I/O."""
import json
import hashlib
import copy
import math
import random
import time

CONDITIONS=('none','baseline','role','switch')


def run_agent_retrieval_comparison(db, tasks, *, switch_runner, count_tokens, provider):
    """Run the live agent-study retrieval path with an explicit decision provider."""
    if provider is None or not callable(provider):
        raise ValueError('decision provider required for new agent retrieval')
    from .switch_comparison import run_switch_comparison
    return run_switch_comparison(db,tasks,switch_runner=switch_runner,packet_tokens=2000,
        count_tokens=count_tokens,tokenizer_name='cl100k_base',limit=3,provider=provider,
        include_proposed=True,ranking='bm25',switch_choice_mode='bounded-v1',switch_max_steps=20,switch_max_model_calls=20)


def retrieval_provider_provenance(report):
    manifest=report.get('manifest',{}) if isinstance(report,dict) else {}
    configured=manifest.get('provider_configured'); provider=manifest.get('provider')
    if type(configured) is not bool or (configured and not isinstance(provider,dict)) or (not configured and provider is not None):
        raise ValueError('retrieval provider provenance unavailable')
    return {'configured':configured,'provider':copy.deepcopy(provider)}


def validate_agent_manifest(manifest):
    if not isinstance(manifest,dict) or manifest.get('schema')!='quix-agent-study-manifest-v1':
        raise ValueError('invalid agent manifest')
    if manifest.get('conditions')!=list(CONDITIONS):
        raise ValueError('invalid agent study conditions')
    tasks=manifest.get('tasks')
    if not isinstance(tasks,list) or not 1 <= len(tasks) <= 32 or type(manifest.get('seed')) is not int or type(manifest.get('max_input_characters')) is not int or not 1 <= manifest['max_input_characters'] <= 12000:
        raise ValueError('invalid agent study bounds')
    if any(not isinstance(t,dict) or any(not isinstance(t.get(k),str) or not t[k].strip() for k in ('id','query','role','role_version')) for t in tasks):
        raise ValueError('invalid agent tasks')
    if len({t['id'] for t in tasks})!=len(tasks): raise ValueError('duplicate agent tasks')
    if any(t.get('labels') is not None or t.get('review') is not None for t in tasks):
        raise ValueError('agent tasks must not include review labels')


def validate_retrieval_replay(report,tasks,corpus_revision):
    if not isinstance(report,dict) or not isinstance(report.get('manifest'),dict):
        raise ValueError('invalid retrieval replay')
    manifest=report['manifest']
    if manifest.get('corpus_revision') != corpus_revision:
        raise ValueError('retrieval replay corpus mismatch')
    if manifest.get('tasks') != tasks:
        raise ValueError('retrieval replay tasks mismatch')
    expected={'packet_tokens':2000,'tokenizer':'cl100k_base','limit':3,'ranking':'bm25','candidate_scope':'sections_and_records','include_proposed':True}
    if any(manifest.get(k)!=v for k,v in expected.items()):
        raise ValueError('retrieval replay scope mismatch')
    variants=report.get('variants',{})
    ids={t['id'] for t in tasks}
    for name in ('baseline','role','switch'):
        queries=variants.get(name,{}).get('queries',{})
        if set(queries)!=ids or any(not isinstance(q,dict) or not isinstance(q.get('results'),list) for q in queries.values()):
            raise ValueError('retrieval replay queries mismatch')


def validate_replay_evidence(db,report,tasks):
    """Rebind replayed bodies and anchors to the current source-checked catalog."""
    from .switch_snapshot import build_snapshot
    for task in tasks:
        snapshot=build_snapshot(db,task=task['query'],role=task['role'],role_version=task['role_version'],
            max_steps=5,max_model_calls=10,max_characters=5000,include_proposed=True,matched_candidates=True)
        candidates={item['id']:item for item in snapshot['candidates']}
        for variant in ('baseline','role','switch'):
            rows=report['variants'][variant]['queries'][task['id']]['results']
            if len(rows)>3 or len({r.get('id') for r in rows if isinstance(r,dict)})!=len(rows):
                raise ValueError('invalid replay evidence')
            for row in rows:
                candidate=candidates.get(row.get('id')) if isinstance(row,dict) else None
                if not candidate or not isinstance(row.get('body'),str) or not row['body'] or not candidate['body'].startswith(row['body']):
                    raise ValueError('invalid replay evidence body')
                if (row['body']!=candidate['body'] or candidate.get('body_truncated')) and row.get('body_truncated') is not True:
                    raise ValueError('replay evidence truncation not marked')
                fields=('record_type','title','path','revision','source_status','start_line','end_line','page_start','page_end')
                if any(row.get(field)!=candidate.get(field) for field in fields):
                    raise ValueError('invalid replay evidence anchor')
                if candidate['record_type']=='agent_record' and any(row.get(field)!=candidate.get(field) for field in ('evidence','evidence_status','unsupported')):
                    raise ValueError('invalid replay agent evidence')


def run_agent_study(tasks, *, context_provider, agent, seed, max_input_characters=12000, agent_kind='fixture', on_schedule=None, on_result=None, role_definitions=None):
    if not isinstance(tasks,list) or not tasks or type(seed) is not int or type(max_input_characters) is not int or max_input_characters < 1:
        raise ValueError('invalid study configuration')
    fields=('id','query','role','role_version')
    if any(not isinstance(t,dict) or any(not isinstance(t.get(k),str) or not t[k].strip() for k in fields) for t in tasks) or len({t['id'] for t in tasks})!=len(tasks):
        raise ValueError('invalid or duplicate tasks')
    if not callable(context_provider) or not callable(agent) or agent_kind not in ('fixture','actual') or (on_schedule is not None and not callable(on_schedule)) or (on_result is not None and not callable(on_result)):
        raise ValueError('invalid study adapters')
    if role_definitions is not None:
        from .agent_process import validate_role_bindings
        validate_role_bindings(tasks,role_definitions)
        role_definitions=copy.deepcopy(role_definitions)
    rng=random.Random(seed)
    schedule=[]
    for task in tasks:
        conditions=list(CONDITIONS); rng.shuffle(conditions)
        schedule.extend({'task_id':task['id'],'condition':condition} for condition in conditions)
    if on_schedule is not None:
        on_schedule(copy.deepcopy(schedule))
    by_id={task['id']:task for task in tasks}
    runs=[]
    for entry in schedule:
        task=by_id[entry['task_id']]; condition=entry['condition']; started=time.monotonic()
        record={**entry,'status':'error','output':None,'reported_cost':None,'usage':None}
        try:
            context=None if condition=='none' else context_provider(dict(task),condition)
            if isinstance(context,dict):
                serialized=json.dumps(context,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
                record['context_provenance']={'packet_sha256':hashlib.sha256(serialized).hexdigest(),
                    'catalog_fingerprint':context.get('catalog_fingerprint'),'omitted_count':context.get('omitted_count'),
                    'sources':[{key:item.get(key) for key in ('id','revision','path')} for item in context.get('results',[]) if isinstance(item,dict)]}
            if condition!='none' and context is None:
                record['status']='context_unavailable'
            else:
                request={'task_id':task['id'],'query':task['query'],'role':task['role'],'role_version':task['role_version'],
                    'context':context,'max_input_characters':max_input_characters}
                if role_definitions is not None:
                    request['role_purpose']=role_definitions[task['role']]['purpose']
                serialized_request=json.dumps(request,ensure_ascii=False,separators=(',',':'))
                record['study_request_characters']=len(serialized_request)
                record['study_request_sha256']=hashlib.sha256(serialized_request.encode('utf-8')).hexdigest()
                if len(serialized_request) > max_input_characters:
                    record['status']='input_budget_exceeded'
                else:
                    response=agent(request)
                    if isinstance(response,dict) and response.get('status') in {'invalid_request','configuration_missing','agent_failure','intent_too_large','task_mismatch','source_changed','context_invalid','unsupported_or_stale_evidence','role_definition_mismatch','input_budget_exceeded','process_failure','invalid_response','executable_changed'}:
                        record['status']=response['status']; record['call']=response.get('call')
                        cost=(record['call'] or {}).get('costUSD') if isinstance(record['call'],dict) else None
                        if isinstance(cost,(int,float)) and not isinstance(cost,bool) and math.isfinite(cost) and cost>=0:
                            record['reported_cost']=cost
                    elif not isinstance(response,dict) or not isinstance(response.get('output'),str):
                        record['status']='invalid_response'
                    else:
                        record['status']='completed'; record['output']=response['output']; record['usage']=response.get('usage')
                        record['call']=response.get('call')
                        cost=(response.get('usage') or {}).get('cost') if isinstance(response.get('usage'),dict) else None
                        if isinstance(cost,(int,float)) and not isinstance(cost,bool) and math.isfinite(cost) and cost>=0:
                            record['reported_cost']=cost
        except TimeoutError:
            record['status']='timeout'
        except Exception:
            record['status']='adapter_error'
        record['elapsed_seconds']=time.monotonic()-started
        runs.append(record)
        if on_result is not None:
            on_result(copy.deepcopy(record))
    return {'schema':'quix-agent-study-v1','agent_kind':agent_kind,'seed':seed,'max_input_characters':max_input_characters,'schedule':schedule,'runs':runs}
