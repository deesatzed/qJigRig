"""Frozen, label-free evaluation inputs and paired exploratory reporting."""
import datetime as dt
import hashlib
import json
import math
import statistics
import uuid
import fcntl
from . import core, compare

MAX_CASES = 100
MAX_CALLS_PER_CASE = 15  # Fresh path up to eleven calls; direct and frontier up to two calls each.

def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def freeze(title, cases):
    if not isinstance(title,str) or not title.strip(): raise ValueError('Dataset title is required')
    if not isinstance(cases,list) or not 1 <= len(cases) <= MAX_CASES: raise ValueError(f'Dataset requires 1–{MAX_CASES} cases')
    allowed={'case_id','question','snapshot_id','scope','as_of','historical_as_known'}
    normalized=[]; seen=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)-allowed: raise ValueError('Cases may contain only case_id, question, snapshot_id, scope, as_of, and historical_as_known; labels must be kept separate')
        cid=case.get('case_id'); question=case.get('question'); sid=case.get('snapshot_id'); scope=case.get('scope',''); as_of=case.get('as_of','')
        if not isinstance(cid,str) or not cid.strip() or cid in seen: raise ValueError('Case IDs must be nonempty and unique')
        if not isinstance(question,str) or not question.strip() or not isinstance(scope,str) or not isinstance(as_of,str): raise ValueError('Invalid question, scope or date')
        known=case.get('historical_as_known',False)
        if not isinstance(known,bool) or (known and not as_of): raise ValueError('Historical-as-known requires a boolean and as-of date')
        as_of=core.canonical_date(as_of)
        source=core.load('snapshots',sid)
        from .collections import require_member_metadata
        require_member_metadata(source)
        if scope and source['scope'] and scope != source['scope']: raise ValueError('Source outside case scope')
        if not core.source_covers_date(source,as_of): raise ValueError('Source outside case date')
        seen.add(cid); normalized.append({'case_id':cid,'question':question,'snapshot_id':sid,'scope':scope,'as_of':as_of,'snapshot_sha256':source['sha256'],'snapshot_metadata_sha256':core.source_metadata_sha256(source),**({'historical_as_known':True} if known else {})})
    digest=hashlib.sha256(json.dumps(normalized,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return core.save('datasets',{'id':uuid.uuid4().hex,'title':title,'schema_version':1,'created_at':timestamp(), 'sha256':digest,'cases':normalized, 'labels':'not included'})

def load_frozen(dataset_id):
    dataset=core.load('datasets',dataset_id)
    digest=hashlib.sha256(json.dumps(dataset['cases'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if digest != dataset['sha256']: raise ValueError('Dataset integrity check failed')
    return dataset

def verify_case_source(case):
    source=core.load('snapshots',case['snapshot_id'])
    from .collections import require_member_metadata
    require_member_metadata(source)
    if source['sha256']!=case['snapshot_sha256']: raise ValueError('Pinned dataset source changed')
    if not case.get('snapshot_metadata_sha256'): raise ValueError('Legacy dataset lacks a pinned source metadata fingerprint; freeze a new dataset')
    if core.source_metadata_sha256(source)!=case['snapshot_metadata_sha256']: raise ValueError('Pinned dataset source metadata changed')
    return source

def prepare(dataset_id, consent, max_calls, judge_backend='remote', local_threshold=None, stage='shared-evidence', allow_web=False, targeted=True, extra_search=True, accept_unenforced_budget=False):
    dataset=load_frozen(dataset_id)
    cases=dataset['cases']; required=len(cases)*MAX_CALLS_PER_CASE
    if not isinstance(targeted,bool): raise ValueError('targeted must be boolean')
    if not isinstance(extra_search,bool): raise ValueError('extra_search must be boolean')
    if not targeted and judge_backend=='local' and stage not in ('shared-corpus','practical'): raise ValueError('Local shared-evidence predicates already run in an exhaustive batch; this control is not applicable')
    if consent is not True: raise ValueError('Source-sharing consent is required')
    if not isinstance(max_calls,int) or isinstance(max_calls,bool) or max_calls < required:
        raise ValueError(f'Maximum call budget must be at least {required}; worst case is {MAX_CALLS_PER_CASE} per case')
    if stage not in ('shared-evidence','shared-corpus','practical'): raise ValueError('Unsupported comparison stage')
    if stage in ('shared-corpus','practical') and judge_backend!='local': raise ValueError('Shared-corpus fresh arm requires local evaluator')
    web_tool_budget=None
    if stage=='practical':
        if any(case.get('historical_as_known',False) for case in cases): raise ValueError('Practical web research cannot verify historical knowledge cutoffs')
        if allow_web is not True or accept_unenforced_budget is not True: raise ValueError('Practical comparison requires web authorization and acknowledgment of an unenforced spending limit')
        from .web_research import parse_tool_budget
        web_tool_budget=parse_tool_budget(core.config().get('OPENROUTER_WEB_TOOL_BUDGET_USD'))
    if judge_backend not in ('remote','local'): raise ValueError('Unknown answer-check backend')
    local_environment=None
    if judge_backend == 'local':
        from .local_judge import support_decision, inspect_worker_environment
        support_decision({'choice':'false','probabilities':{'true':0.0,'false':1.0}},local_threshold)
        local_environment=inspect_worker_environment()
    from .experiments import freeze_config
    frozen=freeze_config(core.config())
    # Validate every pinned input before starting a paid call.
    for case in cases:
        verify_case_source(case)
    run=core.save('dataset_runs',{'id':uuid.uuid4().hex,'created_at':timestamp(),'dataset_id':dataset_id,
        'dataset_sha256':dataset['sha256'],'stage':stage,'max_provider_calls':max_calls,'model_config':frozen,
        'max_calls_per_case':MAX_CALLS_PER_CASE,'journal_version':1,'retrieval_policy_version':1,'targeted':targeted,'extra_search':extra_search,'answer_check_backend':judge_backend,'local_support_threshold':local_threshold,'local_worker_environment':local_environment,'web_authorized':bool(allow_web) if stage=='practical' else False,'accept_unenforced_budget':bool(accept_unenforced_budget) if stage=='practical' else False,'web_tool_budget_usd':web_tool_budget,'case_count':len(cases),'status':'started'})
    return run

def launch(dataset_id, consent, max_calls, judge_backend='remote', local_threshold=None, stage='shared-evidence', allow_web=False, targeted=True, extra_search=True, accept_unenforced_budget=False, on_started=None):
    run=prepare(dataset_id,consent,max_calls,judge_backend,local_threshold,stage,allow_web,targeted,extra_search,accept_unenforced_budget)
    try:
        if on_started is not None: on_started(run)
        return resume(run['id'],consent=True)
    except Exception as exc:
        raise ValueError(f'Dataset run {run["id"]} stopped: {exc}. Inspect saved records before resuming.') from exc

def _case_id(run_id,index,kind):
    return hashlib.sha256(f'{run_id}:{index}:{kind}'.encode()).hexdigest()[:32]

def record_intent(run_id,index,case_id):
    return core.save('dataset_intents',{'id':_case_id(run_id,index,'intent'),
        'dataset_run_id':run_id,'index':index,'case_id':case_id,
        'comparison_id':_case_id(run_id,index,'comparison'),'created_at':timestamp()})

def check_practical_continuation(comparison):
    frontier=next(item for item in comparison['items'] if item['arm']=='frontier')
    result=core.load('runs',frontier['run_id'])['result']
    if result.get('status')=='failed' or result.get('search_requests')!=1:
        raise ValueError('Practical web usage failed or was not confirmed; inspect saved records before further cases')

def _verify_completed(comparison,run,case):
    expected={'question':case['question'],'scope':case['scope'],'as_of':case['as_of'],
              'snapshot_id':case['snapshot_id'],'snapshot_sha256':case['snapshot_sha256'],
              'stage':run['stage'],'model_config':run['model_config'],
              'answer_check_backend':run['answer_check_backend'],'local_support_threshold':run['local_support_threshold'], 'historical_as_known':case.get('historical_as_known',False), 'targeted':run.get('targeted',True), 'extra_search':run.get('extra_search',True)}
    if any(comparison.get(k,False if k=='historical_as_known' else (True if k in ('targeted','extra_search') else None))!=v for k,v in expected.items()): raise ValueError('Saved comparison does not match the frozen dataset case')
    if run['stage']=='practical' and (comparison.get('web_authorized') is not True or comparison.get('accept_unenforced_budget') is not True or comparison.get('web_tool_budget_usd')!=run.get('web_tool_budget_usd')): raise ValueError('Saved practical authorization or budget mismatch')
    if case.get('snapshot_metadata_sha256') and comparison.get('snapshot_metadata_sha256')!=case['snapshot_metadata_sha256']: raise ValueError('Saved comparison source metadata does not match frozen case')
    items=comparison.get('items',[])
    if len(items)!=3 or {x.get('arm') for x in items}!=set(compare.ARMS) or len({x.get('run_id') for x in items})!=3 or len({x.get('review_id') for x in items})!=3: raise ValueError('Saved comparison arms are incomplete')
    for item in items:
        arm=core.load('runs',item['run_id'])
        if run['stage']=='practical' and item['arm']=='frontier':
            request=arm.get('request',{})
            if arm.get('mode')!='frontier-web' or arm.get('requested_model')!=run['model_config']['frontier_model'] or arm.get('requested_tool_budget_usd')!=run.get('web_tool_budget_usd') or any(request.get(k)!=case[k] for k in ('question','scope','as_of')) or not isinstance(arm.get('result'),dict): raise ValueError('Saved web arm does not match frozen dataset case')
            continue
        if case.get('snapshot_metadata_sha256') and arm.get('source_metadata_sha256')!=case['snapshot_metadata_sha256']: raise ValueError('Saved arm source metadata does not match frozen case')
        request=arm.get('request',{})
        model=run['model_config']['frontier_model'] if item['arm']=='frontier' else run['model_config']['small_model']
        evidence_mode='lexical' if run['stage'] in ('shared-corpus','practical') else 'shared'
        if arm.get('mode')!=item['arm'] or arm.get('requested_model')!=model or arm.get('source_sha256')!=case['snapshot_sha256'] or arm.get('evidence_mode')!=evidence_mode or arm.get('extra_search',True)!=run.get('extra_search',True) or request.get('historical_as_known',False)!=case.get('historical_as_known',False) or any(request.get(k)!=case[k] for k in ('question','scope','as_of','snapshot_id')) or not isinstance(arm.get('result'),dict):
            raise ValueError('Saved arm does not match the frozen dataset case')
        backend=run['answer_check_backend'] if item['arm']=='fresh' else 'not_applicable'
        if item['arm']=='fresh' and arm.get('answer_check_backend') is not None and arm['answer_check_backend']!=backend:
            raise ValueError('Saved arm evaluator conflicts with the frozen dataset case')
        if item['arm']=='fresh' and 'local_support_threshold' in arm and arm['local_support_threshold']!=run.get('local_support_threshold'):
            raise ValueError('Saved arm threshold conflicts with the frozen dataset case')
        targeted=run.get('targeted',True); extra=run.get('extra_search',True)
        policy=('not_applicable' if item['arm']!='fresh' else
                (('batch_no_extra_search' if not extra else ('batch_targeted_retrieval' if targeted else 'batch_exhaustive_retrieval'))
                 if backend=='local' and evidence_mode=='lexical' else
                 ('exhaustive_batch' if backend=='local' else ('targeted' if targeted else 'exhaustive'))))
        if arm.get('execution_policy') is not None and arm['execution_policy']!=policy:
            raise ValueError('Saved arm execution policy conflicts with the frozen dataset case')
        if item['arm']=='fresh' and run.get('answer_check_backend')=='local' and run.get('local_worker_environment'):
            from .local_judge import validate_recorded_environment
            validate_recorded_environment(arm,run['local_worker_environment'])

def resume(run_id,consent=False):
    if consent is not True: raise ValueError('Source-sharing consent is required to resume')
    run=core.load('dataset_runs',run_id)
    if run.get('journal_version')!=1: raise ValueError('Legacy dataset run has no recovery journal and cannot be resumed safely')
    if 'targeted' not in run: raise ValueError('Legacy dataset run lacks a frozen stopping policy and cannot be resumed safely')
    if run.get('stage')=='shared-corpus' and run.get('answer_check_backend')=='local' and run.get('retrieval_policy_version')!=1: raise ValueError('Legacy dataset run lacks a frozen follow-up retrieval policy and cannot be resumed safely')
    if run.get('stage')=='shared-corpus' and 'extra_search' not in run: raise ValueError('Legacy dataset run lacks a frozen extra-search control and cannot be resumed safely')
    lock_dir=core.DATA/'locks'; lock_dir.mkdir(parents=True,exist_ok=True)
    with (lock_dir/(run_id+'.lock')).open('a') as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Dataset run is already active') from None
        from .experiments import validate_config
        validate_config(run['model_config'])
        def check_local_environment():
            if run.get('answer_check_backend')=='local':
                from .local_judge import inspect_worker_environment
                if not run.get('local_worker_environment'): raise ValueError('Frozen local judge environment is missing')
                if inspect_worker_environment()!=run['local_worker_environment']: raise ValueError('Local judge environment changed since launch')
        check_local_environment()
        dataset=load_frozen(run['dataset_id'])
        if dataset['sha256']!=run['dataset_sha256'] or len(dataset['cases'])!=run['case_count']: raise ValueError('Frozen dataset mismatch')
        reserved=run.get('max_calls_per_case'); budget=run.get('max_provider_calls')
        if (not isinstance(reserved,int) or isinstance(reserved,bool) or reserved<MAX_CALLS_PER_CASE
                or not isinstance(budget,int) or isinstance(budget,bool) or budget<len(dataset['cases'])*reserved):
            raise ValueError('Saved call budget is missing or insufficient for the current per-case reservation')
        for case in dataset['cases']:
            verify_case_source(case)
        for index,case in enumerate(dataset['cases']):
            check_local_environment()
            receipt_path=core.DATA/'dataset_receipts'/(_case_id(run_id,index,'receipt')+'.json')
            if receipt_path.exists():
                receipt=core.load('dataset_receipts',_case_id(run_id,index,'receipt'))
                if receipt['dataset_run_id']!=run_id or receipt['index']!=index or receipt['case_id']!=case['case_id'] or receipt['comparison_id']!=_case_id(run_id,index,'comparison'): raise ValueError('Dataset receipt mismatch')
                _verify_completed(core.load('comparisons',receipt['comparison_id']),run,case)
                if run['stage']=='practical' and index<len(dataset['cases'])-1: check_practical_continuation(core.load('comparisons',receipt['comparison_id']))
                continue
            intent_id=_case_id(run_id,index,'intent'); intent_path=core.DATA/'dataset_intents'/(intent_id+'.json')
            if intent_path.exists():
                intent=core.load('dataset_intents',intent_id)
                if intent['dataset_run_id']!=run_id or intent['index']!=index or intent['case_id']!=case['case_id'] or intent['comparison_id']!=_case_id(run_id,index,'comparison'): raise ValueError('Dataset intent mismatch')
                try: comparison=core.load('comparisons',intent['comparison_id'])
                except FileNotFoundError: raise ValueError(f'Case {case["case_id"]} has an uncertain in-flight comparison; inspect saved runs before starting another') from None
                _verify_completed(comparison,run,case)
            else:
                intent=record_intent(run_id,index,case['case_id'])
                comparison=compare.create(case['question'],case['snapshot_id'],case['scope'],case['as_of'],True,
                    judge_backend=run['answer_check_backend'],local_threshold=run['local_support_threshold'],
                    stage=run['stage'],allow_web=run.get('web_authorized',False),model_config=run['model_config'],
                    comparison_id=intent['comparison_id'],historical_as_known=case.get('historical_as_known',False),targeted=run.get('targeted',True),extra_search=run.get('extra_search',True),expected_source_metadata=case['snapshot_metadata_sha256'],accept_unenforced_budget=run.get('accept_unenforced_budget',False),web_tool_budget=run.get('web_tool_budget_usd'),expected_local_environment=run.get('local_worker_environment'))
                _verify_completed(comparison,run,case)
            core.save('dataset_receipts',{'id':_case_id(run_id,index,'receipt'),'dataset_run_id':run_id,
                'index':index,'case_id':case['case_id'],'comparison_id':comparison['id'],'created_at':timestamp()})
            if run['stage']=='practical' and index<len(dataset['cases'])-1: check_practical_continuation(comparison)
            if index<len(dataset['cases'])-1 and all(core.load('runs',item['run_id'])['result'].get('status')=='failed' for item in comparison['items']):
                raise ValueError(f'All comparison arms failed for case {case["case_id"]}; inspect saved results before resuming')
    return status(run_id)

def status(run_id):
    run=core.load('dataset_runs',run_id)
    receipts=sorted((x for x in core.records('dataset_receipts') if x['dataset_run_id']==run_id),key=lambda x:x['index'])
    complete=(len(receipts)==run['case_count'] and {x['index'] for x in receipts}==set(range(run['case_count'])) and len({x['comparison_id'] for x in receipts})==run['case_count'])
    running=False; lock_path=core.DATA/'locks'/(run_id+'.lock')
    if lock_path.exists():
        with lock_path.open('a') as lock:
            try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: running=True
            else: fcntl.flock(lock.fileno(),fcntl.LOCK_UN)
    receipt_indices={x['index'] for x in receipts}
    pending=[]
    for intent in core.records('dataset_intents'):
        if intent['dataset_run_id']==run_id and intent['index'] not in receipt_indices:
            present=(core.DATA/'comparisons'/(intent['comparison_id']+'.json')).exists()
            pending.append({'index':intent['index'],'case_id':intent['case_id'],
                            'comparison_id':intent['comparison_id'],
                            'state':'comparison_saved' if present else ('active_or_unresolved' if running else 'uncertain')})
    return {**run,'status':'running' if running else ('awaiting adjudication' if complete else 'incomplete'),
            'receipts':receipts,'pending_cases':pending}

def score_category(row,answerability=None):
    outcome=row['status']
    if outcome=='failed': return 'incorrect'
    if answerability=='uncertain': return 'unresolved'
    if answerability is None and outcome=='deferred' and row['verdict']=='correct': return 'unresolved'
    if answerability=='answerable' and outcome=='deferred': return 'incorrect'
    if answerability=='unanswerable' and outcome=='decided': return 'incorrect'
    if row['verdict']=='unresolved' or (outcome=='decided' and row['evidence_support']=='unclear'): return 'unresolved'
    if outcome in ('decided','deferred') and row['verdict']=='correct' and (outcome=='deferred' or row['evidence_support']=='supported'): return 'correct'
    return 'incorrect'

def score(run_id):
    run=status(run_id)
    if run['status']=='running': raise ValueError('Dataset run is running; scoring is unavailable')
    if run['status']=='incomplete': raise ValueError('Dataset run is incomplete; scoring is unavailable')
    dataset=load_frozen(run['dataset_id'])
    if dataset['sha256'] != run['dataset_sha256']: raise ValueError('Dataset does not match run')
    if len(dataset['cases'])!=run['case_count']: raise ValueError('Dataset case count does not match run')
    reports=[]
    for receipt in run['receipts']:
        case=dataset['cases'][receipt['index']]
        if receipt.get('case_id')!=case['case_id']: raise ValueError('Receipt case does not match frozen dataset')
        if run.get('journal_version')==1:
            _verify_completed(core.load('comparisons',receipt['comparison_id']),run,case)
        report=compare.report(receipt['comparison_id'],include_outputs=False)
        reports.append({'case_id':receipt['case_id'],'comparison_id':receipt['comparison_id'],'case_assessment':report.get('case_assessment'),'rows':report['rows']})
    arms={}
    for report in reports:
        for row in report['rows']:
            a=arms.setdefault(row['arm'], {'assigned':0,'correct_supported_or_justified':0,'incorrect':0,'unresolved':0,'decided':0,'deferred':0,'failed':0,'provider_cost_usd':0.0,'cost_complete':True,'elapsed_seconds':0.0})
            a['assigned']+=1
            outcome=row['status']
            if outcome in ('decided','deferred','failed'): a[outcome]+=1
            assessment=report.get('case_assessment')
            answerability=assessment.get('answerability') if assessment else None
            if answerability=='answerable':
                a.setdefault('answerable_cases_assessed',0); a['answerable_cases_assessed']+=1
                a.setdefault('decisions_on_answerable',0); a['decisions_on_answerable']+=int(outcome=='decided')
            a.setdefault('unknown_or_legacy_answerability',0); a['unknown_or_legacy_answerability']+=int(answerability in (None,'uncertain'))
            category=score_category(row,answerability)
            if category=='correct': a['correct_supported_or_justified']+=1
            else: a[category]+=1
            a.setdefault('latencies',[]).append(row['elapsed_seconds'])
            a.setdefault('provider_calls',0); a['provider_calls']+=row['provider_calls']
            a.setdefault('source_searches',0); a['source_searches']+=row['source_searches']
            if run.get('stage')=='practical':
                a.setdefault('observed_web_search_requests',None)
                a.setdefault('web_search_count_complete',True)
                observed=row.get('observed_web_search_requests')
                if observed is not None: a['observed_web_search_requests']=(a['observed_web_search_requests'] or 0)+observed
                if row.get('web_search_usage_status')=='incomplete': a['web_search_count_complete']=False
                a.setdefault('observed_server_tool_calls_executed',None)
                a.setdefault('server_tool_count_complete',True)
                observed_tools=row.get('observed_server_tool_calls_executed')
                if observed_tools is not None: a['observed_server_tool_calls_executed']=(a['observed_server_tool_calls_executed'] or 0)+observed_tools
                if row.get('server_tool_usage_status')=='incomplete': a['server_tool_count_complete']=False
            work=row.get('predicate_work',{})
            for key in ('evaluated','skipped','unresolved_without_evaluation'):
                field='predicates_'+key; a.setdefault(field,0); a[field]+=work.get(key,0)
            a['elapsed_seconds']+=row['elapsed_seconds']
            if row['cost_status']=='provider reported': a['provider_cost_usd']+=row['cost_usd']
            else: a['cost_complete']=False
            if row.get('observed_provider_cost_usd') is not None:
                a.setdefault('observed_provider_cost_usd',0.0); a['observed_provider_cost_usd']+=row['observed_provider_cost_usd']
    for a in arms.values():
        # Unresolved reviews are explicit and included in the assigned denominator.
        a['correct_fraction_all_assigned']=a['correct_supported_or_justified']/a['assigned']
        a['decision_rate_all_assigned']=a['decided']/a['assigned']
        denominator=a.get('answerable_cases_assessed',0)
        a['coverage_on_assessed_answerable']=a.get('decisions_on_answerable',0)/denominator if denominator else None
        latencies=sorted(a.pop('latencies'))
        a['latency_median_seconds']=statistics.median(latencies)
        a['latency_p95_seconds']=latencies[math.ceil(0.95*len(latencies))-1]
        if not a['cost_complete']: a['provider_cost_usd']=None
        if run.get('stage')=='practical':
            a['web_search_requests']=a['observed_web_search_requests'] if a['web_search_count_complete'] else None
            a['server_tool_calls_executed']=a['observed_server_tool_calls_executed'] if a['server_tool_count_complete'] else None
    paired=[]
    for left,right in (('fresh','frontier'),('fresh','direct')):
        counts={'left_correct_right_incorrect':0,'left_incorrect_right_correct':0,'both_correct':0,'both_incorrect':0,'unresolved_pairs':0}
        for case in reports:
            by_arm={row['arm']:row for row in case['rows']}
            if left not in by_arm or right not in by_arm: continue
            answerability=(case.get('case_assessment') or {}).get('answerability')
            l,r=score_category(by_arm[left],answerability),score_category(by_arm[right],answerability)
            if 'unresolved' in (l,r): counts['unresolved_pairs']+=1
            elif l=='correct' and r=='incorrect': counts['left_correct_right_incorrect']+=1
            elif l=='incorrect' and r=='correct': counts['left_incorrect_right_correct']+=1
            elif l==r=='correct': counts['both_correct']+=1
            else: counts['both_incorrect']+=1
        paired.append({'left':left,'right':right,**counts})
    result={'dataset_run_id':run_id,'dataset_id':run['dataset_id'],'dataset_sha256':run['dataset_sha256'],
        'stage':run.get('stage','shared-evidence'),'targeted':run.get('targeted'),'extra_search':run.get('extra_search'),'answer_check_backend':run.get('answer_check_backend'),'local_support_threshold':run.get('local_support_threshold'),'model_config':run.get('model_config'),'interpretation':'Exploratory adjudication summary; unresolved cases remain unresolved. Not a confirmatory accuracy or non-inferiority claim.',
        'arms':arms,'paired':paired,'cases':reports}
    if run.get('stage')=='practical':
        result['requested_web_tool_budget_usd']=run.get('web_tool_budget_usd')
        result['web_budget_interpretation']='Requested tool-loop stop per web request; not a guaranteed cap on total charges.'
    return result

def render_markdown(result):
    reviewers=set()
    for case in result.get('cases',[]):
        assessment=case.get('case_assessment') or {}
        if assessment.get('reviewer'): reviewers.add(assessment['reviewer'])
        reviewers.update(row['reviewer'] for row in case.get('rows',[]) if row.get('reviewer'))
    attribution=', '.join(sorted(json.dumps(name,ensure_ascii=False) for name in reviewers)) or 'not recorded'
    def state(value): return 'enabled' if value is True else ('disabled' if value is False else 'not recorded')
    model_config=result.get('model_config') or {}
    lines=['# Exploratory comparison report','',f"Dataset run: `{result['dataset_run_id']}`",
           f"Dataset SHA-256: `{result.get('dataset_sha256') or 'not recorded'}`",
           f"Stage: {result['stage']}",
           f"Models: small `{model_config.get('small_model','not recorded')}`, frontier `{model_config.get('frontier_model','not recorded')}`",
           f"Fresh evaluator: {result.get('answer_check_backend') or 'not recorded'}; local support threshold: {result.get('local_support_threshold') if result.get('local_support_threshold') is not None else 'not recorded'}",
           f"Targeted policy: {state(result.get('targeted'))}; extra search: {state(result.get('extra_search'))}",'',result['interpretation'],'',
           f'Recorded reviewers: {attribution}. Reviewer independence is not verified.', '',
           'Latency includes assigned failures and deferrals; cold/warm state was not recorded. Local resource costs are unobserved.',
           '', '| Arm | Assigned | Correct and supported / justified | Incorrect | Unresolved | Decided | Deferred | Failed | Median s | P95 s | Provider cost USD |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm,a in sorted(result['arms'].items()):
        cost='unobserved' if a['provider_cost_usd'] is None else f"{a['provider_cost_usd']:.6f}"
        lines.append(f"| {arm} | {a['assigned']} | {a['correct_supported_or_justified']} | {a['incorrect']} | {a['unresolved']} | {a['decided']} | {a['deferred']} | {a['failed']} | {a['latency_median_seconds']:.3f} | {a['latency_p95_seconds']:.3f} | {cost} |")
    lines.extend(['','Work recorded per arm:'])
    if result.get('stage')=='practical':
        lines.append(f"- Requested web tool-loop budget per request: ${result.get('requested_web_tool_budget_usd')}; not a guaranteed cap on total charges.")
    for arm,a in sorted(result['arms'].items()):
        rows=[row for case in result.get('cases',[]) for row in case.get('rows',[]) if row.get('arm')==arm]
        counts=[row.get('local_inferences') for row in rows]
        complete=(len(rows)==a['assigned'] and all(isinstance(n,int) and not isinstance(n,bool) and n>=0 for n in counts))
        local_total=str(sum(counts)) if complete else 'unknown'
        lines.append(f"- {arm}: {a.get('provider_calls', 'unavailable')} provider calls; {a.get('source_searches', 'unavailable')} source searches; local inferences: {local_total}.")
        if result.get('stage')=='practical':
            count=a.get('web_search_requests'); subtotal=a.get('observed_web_search_requests')
            lines.append(f"  Web searches: {count if count is not None else 'unknown'}; observed provider-reported subtotal: {subtotal if subtotal is not None else 'unknown'}.")
            tools=a.get('server_tool_calls_executed'); tool_subtotal=a.get('observed_server_tool_calls_executed')
            lines.append(f"  Server-tool executions: {tools if tools is not None else 'unknown'}; observed provider-reported subtotal: {tool_subtotal if tool_subtotal is not None else 'unknown'}.")
        if a.get('observed_provider_cost_usd') is not None and not a.get('cost_complete',False):
            lines.append(f"  Observed provider-reported cost: ${a['observed_provider_cost_usd']:.6f}; total is incomplete.")
    lines.extend(['','Decision rate uses all assigned cases. Coverage below is restricted to assessed answerable cases; uncertain and legacy cases are reported separately. No confidence interval or non-inferiority conclusion is provided.',''])
    for arm,a in sorted(result['arms'].items()):
        coverage=a.get('coverage_on_assessed_answerable')
        value='unavailable' if coverage is None else f'{coverage:.1%}'
        lines.append(f"- {arm}: answerable cases {a.get('answerable_cases_assessed',0)}, issued decisions {a.get('decisions_on_answerable',0)}, coverage {value}, uncertain or legacy cases {a.get('unknown_or_legacy_answerability',0)}.")
    lines.extend(['','## Paired adjudications',''])
    for pair in result['paired']:
        lines.append(f"- {pair['left']} vs {pair['right']}: left-only correct {pair['left_correct_right_incorrect']}, right-only correct {pair['left_incorrect_right_correct']}, both correct {pair['both_correct']}, both incorrect {pair['both_incorrect']}, unresolved {pair['unresolved_pairs']}.")
    return '\n'.join(lines)+'\n'
