"""Shared-evidence comparison and blinded, independently entered adjudications.

This module does not generate labels and never sends review data to providers.
"""
import datetime as dt
import hashlib
import math
import uuid
from . import core

ARMS = ('fresh', 'direct', 'frontier')

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def create(question, snapshot_id, scope='', as_of='', consent=False, arms=ARMS, judge_backend='remote', local_threshold=None, stage='shared-evidence', allow_web=False, model_config=None, comparison_id=None, historical_as_known=False, targeted=True, extra_search=True, expected_source_metadata=None, accept_unenforced_budget=False, web_tool_budget=None, expected_local_environment=None):
    as_of=core.canonical_date(as_of)
    if not isinstance(targeted,bool): raise ValueError('targeted must be boolean')
    if not isinstance(extra_search,bool): raise ValueError('extra_search must be boolean')
    if not targeted and judge_backend=='local' and stage not in ('shared-corpus','practical'): raise ValueError('Local shared-evidence predicates already run in an exhaustive batch; this control is not applicable')
    if not isinstance(historical_as_known,bool) or (historical_as_known and not as_of): raise ValueError('Historical-as-known requires an as-of date')
    if consent is not True:
        raise ValueError('Consent is required for each comparison')
    if not isinstance(arms, (list, tuple)) or not arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        raise ValueError('Choose distinct supported arms')
    if stage not in ('shared-evidence','shared-corpus','practical'): raise ValueError('Unsupported comparison stage')
    if stage in ('shared-corpus','practical') and judge_backend!='local': raise ValueError('Shared-corpus fresh arm requires local evaluator')
    if stage=='practical':
        if historical_as_known: raise ValueError('Practical web research cannot verify historical knowledge cutoffs')
        if allow_web is not True or accept_unenforced_budget is not True: raise ValueError('Practical comparison requires web authorization and acknowledgment of an unenforced spending limit')
        from .web_research import parse_tool_budget
        web_tool_budget=parse_tool_budget(web_tool_budget if web_tool_budget is not None else core.config().get('OPENROUTER_WEB_TOOL_BUDGET_USD'))
    if judge_backend not in ('remote','local'): raise ValueError('Unknown answer-check backend')
    if judge_backend == 'local':
        from .local_judge import support_decision, inspect_worker_environment
        support_decision({'choice':'false','probabilities':{'true':0.0,'false':1.0}},local_threshold)
        if 'fresh' in arms: inspect_worker_environment()
    from .experiments import freeze_config,validate_config
    frozen=validate_config(model_config) if model_config is not None else freeze_config(core.config())
    # Validate the snapshot before creating or paying for any arm.
    source = core.load('snapshots', snapshot_id)
    from .collections import require_member_metadata
    require_member_metadata(source)
    metadata_hash=core.source_metadata_sha256(source)
    if expected_source_metadata is not None and expected_source_metadata!=metadata_hash: raise ValueError('Pinned source metadata changed before comparison')
    ident=comparison_id or uuid.uuid4().hex
    if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident): raise ValueError('Invalid comparison ID')
    if (core.DATA/'comparisons'/(ident+'.json')).exists(): raise ValueError('Comparison ID already exists')
    comparison = {'id': ident, 'schema_version': 2, 'created_at': now(),
        'stage': stage, 'question': question, 'scope': scope, 'as_of': as_of,
        'snapshot_id': snapshot_id, 'snapshot_sha256': source['sha256'], 'snapshot_metadata_sha256':metadata_hash, 'model_config':frozen, 'historical_as_known':historical_as_known, 'targeted':targeted, 'extra_search':extra_search,
        'status': 'awaiting adjudication', 'answer_check_backend':judge_backend, 'local_support_threshold':local_threshold, 'web_authorized':bool(allow_web) if stage=='practical' else False, 'items': []}
    if stage=='practical': comparison.update({'accept_unenforced_budget':True,'web_tool_budget_usd':web_tool_budget})
    try:
        core.save('comparison_intents',{**comparison,'status':'started','arms':list(arms)})
    except FileExistsError:
        raise ValueError('Comparison ID already has an intent; inspect saved arms before retrying') from None
    for arm in arms:
        arm_id=hashlib.sha256((ident+':'+arm).encode()).hexdigest()[:32]
        core.save('comparison_arm_intents',{'id':arm_id,'comparison_id':ident,'arm':arm,'created_at':now()})
        # Each arm receives the original request and source only, not earlier results.
        if stage=='practical' and arm=='frontier':
            from .web_research import run as web_run
            run=web_run(question,scope,as_of,allow_web=allow_web,acknowledge_unenforced_limit=accept_unenforced_budget,model=frozen['frontier_model'],tool_budget_override=web_tool_budget)
        else:
            run = core.run(question, snapshot_id, scope, as_of, arm, consent, model=frozen['small_model'],frontier_model=frozen['frontier_model'],judge_backend=judge_backend if arm=='fresh' else 'remote', local_threshold=local_threshold if arm=='fresh' else None, evidence_mode='lexical' if stage in ('shared-corpus','practical') else 'shared',historical_as_known=historical_as_known,targeted=targeted,extra_search=extra_search,expected_source_metadata=metadata_hash)
        item={'review_id': uuid.uuid4().hex, 'arm': arm, 'run_id': run['id']}
        core.save('comparison_arm_receipts',{'id':arm_id,'comparison_id':ident,'created_at':now(),**item})
        comparison['items'].append(item)
        if arm=='fresh' and judge_backend=='local' and expected_local_environment is not None:
            from .local_judge import validate_recorded_environment
            validate_recorded_environment(run,expected_local_environment)
    return core.save('comparisons', comparison)

def review_source(comp):
    source=core.load('snapshots',comp['snapshot_id'])
    if comp.get('snapshot_sha256') and source['sha256']!=comp['snapshot_sha256']: raise ValueError('Comparison source text changed since execution')
    if comp.get('snapshot_metadata_sha256') and core.source_metadata_sha256(source)!=comp['snapshot_metadata_sha256']: raise ValueError('Comparison source metadata changed since execution')
    return source

def validate_arm_source(comp,item,run,source):
    if comp.get('stage')=='practical' and item.get('arm')=='frontier': return
    request=run.get('request',{})
    if comp.get('snapshot_metadata_sha256') and (not run.get('source_sha256') or not run.get('source_metadata_sha256') or not request.get('snapshot_id')):
        raise ValueError('Saved arm source binding is missing')
    if ((run.get('source_sha256') and run['source_sha256']!=source['sha256'])
            or (run.get('source_metadata_sha256') and run['source_metadata_sha256']!=core.source_metadata_sha256(source))
            or (request.get('snapshot_id') and request['snapshot_id']!=source['id'])):
        raise ValueError('Saved arm source does not match comparison source')

def validate_review_bindings(comp):
    source=review_source(comp)
    for item in comp['items']:
        validate_arm_source(comp,item,core.load('runs',item['run_id']),source)

def citation_integrity(comp,item,run):
    if comp.get('stage')=='practical' and item['arm']=='frontier':
        return 'unavailable; web citations not independently verified'
    from .verify_run import verify
    verification=verify(run['id'])
    return 'failed' if verification['source']=='failed' else verification['citations']

def review_evidence(trace):
    evidence=[]
    for item in trace:
        metadata={'predicate_question':(item.get('predicate') or {}).get('question',''),
                  'usable_outcome':item.get('outcome'),
                  'reported_outcome':item.get('reported_outcome'),
                  'quote_scope':item.get('quote_scope','')}
        if item.get('quote'):
            evidence.append({'text':item['quote'],'source_ref':item.get('source_ref'),
                             'kind':'predicate quotation',**metadata})
        for span in item.get('evidence_spans',[]):
            if span.get('text'):
                evidence.append({'text':span['text'],'source_ref':span.get('source_ref'),
                                 'kind':'retrieved context',**metadata})
    return evidence

def blind(comparison_id):
    comp = core.load('comparisons', comparison_id)
    source=review_source(comp)
    assessment_saved=get_case_assessment(comparison_id) is not None
    members=[]
    for member in source.get('members',[]):
        saved=core.load('snapshots',member['source_id'])
        members.append({**member,'origin':saved.get('origin',''),
                        'parent_snapshot_id':saved.get('parent_snapshot_id'),
                        'intervention_reason':saved.get('intervention_reason'),
                        'metadata_binding':('pinned to comparison' if member.get('source_metadata_sha256') and comp.get('snapshot_metadata_sha256') else
                                            'member fingerprint checked; comparison metadata not pinned' if member.get('source_metadata_sha256') else 'not pinned')})
    # Sort opaque random IDs, not the fixed arm order.
    items=[]
    saved_reviews={x['review_id'] for x in core.records('adjudications') if x.get('comparison_id')==comparison_id}
    for item in sorted(comp['items'], key=lambda x: x['review_id']):
        run=core.load('runs',item['run_id'])
        validate_arm_source(comp,item,run,source)
        result=run['result']
        trace=run.get('trace',[])
        integrity=citation_integrity(comp,item,run)
        # Provider identity, timestamps, prompt, trace, and usage can reveal the arm.
        visible_reason=result.get('reason','') if result.get('status')=='deferred' else ('Technical failure' if result.get('status')=='failed' else '')
        items.append({'review_id':item['review_id'], 'review_saved':item['review_id'] in saved_reviews, 'citation_integrity':integrity, 'result':{'status':result.get('status'), 'answer':result.get('answer'), 'quote':result.get('quote',''), 'source_ref':result.get('source_ref'), 'quotes':result.get('quotes',[]), 'source_refs':result.get('source_refs',[]), 'reason':visible_reason, 'citations':result.get('citations',[])},
                      'unresolved_questions':[t.get('predicate',{}).get('question','') for t in trace if t.get('outcome') in ('unknown','conflict')],
                      'evidence_scope':'Full source context; not a localized supporting span.' if any(t.get('quote_scope') for t in trace) else '',
                      'review_evidence':review_evidence(trace),
                      'evidence_spans':[{'text':span['text'],'source_ref':span.get('source_ref')} for t in trace for span in t.get('evidence_spans',[]) if span.get('text')],
                      'evidence_quotes':[t.get('quote') for t in trace if t.get('quote')]+[span['text'] for t in trace for span in t.get('evidence_spans',[]) if span.get('text')]})
    return {'comparison_id':comp['id'], 'stage':comp['stage'], 'question':comp['question'],
            'scope':comp['scope'], 'as_of':comp['as_of'], 'historical_as_known':comp.get('historical_as_known',False),
            'source':{'id':source['id'], 'title':source['title'], 'origin':source.get('origin',''), 'text':source['text'], 'sha256':source['sha256'], 'observed_at':source.get('observed_at',''), 'effective_from':source.get('effective_from',''), 'effective_to':source.get('effective_to',''), 'parent_snapshot_id':source.get('parent_snapshot_id'), 'intervention_reason':source.get('intervention_reason'), 'metadata_binding':'pinned to comparison' if comp.get('snapshot_metadata_sha256') else 'not pinned', 'members':members},
            'case_assessment_saved':assessment_saved, 'case_assessment_required':comp.get('schema_version',1)>=2,
            'items':items if assessment_saved or comp.get('schema_version',1)<2 else []}

def adjudicate(comparison_id, review_id, reviewer, verdict, evidence_support, notes):
    comp=core.load('comparisons',comparison_id)
    if comp.get('snapshot_sha256'): validate_review_bindings(comp)
    if comp.get('schema_version',1)>=2 and get_case_assessment(comparison_id) is None:
        raise ValueError('Case answerability assessment is required before reviewing items')
    if review_id not in {x['review_id'] for x in comp['items']}:
        raise ValueError('Review item does not belong to comparison')
    if verdict not in ('correct', 'incorrect', 'unresolved'):
        raise ValueError('Verdict must be correct, incorrect, or unresolved')
    if evidence_support not in ('supported','unsupported','unclear'):
        raise ValueError('Evidence support must be supported, unsupported, or unclear')
    if evidence_support=='supported':
        item=next(x for x in comp['items'] if x['review_id']==review_id)
        if citation_integrity(comp,item,core.load('runs',item['run_id']))=='failed':
            raise ValueError('Citation integrity failed; it cannot be marked supported')
    if not reviewer.strip() or not notes.strip():
        raise ValueError('Reviewer and rationale are required')
    if any(x['comparison_id']==comparison_id and x['review_id']==review_id for x in core.records('adjudications')):
        raise ValueError('An adjudication already exists for this item')
    try:
        return core.save('adjudications',{'id':hashlib.sha256((comparison_id+review_id).encode()).hexdigest()[:32],'created_at':now(),
            'comparison_id':comparison_id,'review_id':review_id,'reviewer':reviewer,
            'verdict':verdict,'evidence_support':evidence_support,'notes':notes})
    except FileExistsError as exc:
        raise ValueError('An adjudication already exists for this item') from exc

def assess_case(comparison_id, reviewer, answerability, rationale, references=''):
    comp=core.load('comparisons',comparison_id)
    if comp.get('snapshot_sha256'): validate_review_bindings(comp)
    if answerability not in ('answerable','unanswerable','uncertain'): raise ValueError('Invalid answerability')
    if not isinstance(reviewer,str) or not reviewer.strip() or not isinstance(rationale,str) or not rationale.strip(): raise ValueError('Reviewer and rationale are required')
    if answerability!='uncertain' and (not isinstance(references,str) or not references.strip()): raise ValueError('Reference evidence is required')
    ident=hashlib.sha256((comparison_id+':case-assessment').encode()).hexdigest()[:32]
    try:
        return core.save('case_assessments',{'id':ident,'comparison_id':comparison_id,'created_at':now(),
            'reviewer':reviewer,'answerability':answerability,'rationale':rationale,'references':references,
            'note':'Human-provided assessment; independence and reference validity are not automatically verified.'})
    except FileExistsError as exc:
        raise ValueError('Case assessment already exists for this comparison') from exc

def get_case_assessment(comparison_id):
    ident=hashlib.sha256((comparison_id+':case-assessment').encode()).hexdigest()[:32]
    try: return core.load('case_assessments',ident)
    except FileNotFoundError: return None

def ensure_dataset_reviews_complete(comparison_id):
    receipts=core.records('dataset_receipts')
    dataset_ids={r['dataset_run_id'] for r in receipts if r['comparison_id']==comparison_id}
    dataset_ids.update(r['dataset_run_id'] for r in core.records('dataset_intents') if r['comparison_id']==comparison_id)
    all_reviews=core.records('adjudications')
    for dataset_id in dataset_ids:
        dataset_run=core.load('dataset_runs',dataset_id)
        members=[r for r in receipts if r['dataset_run_id']==dataset_id]
        if len(members)!=dataset_run['case_count'] or {r['index'] for r in members}!=set(range(dataset_run['case_count'])) or len({r['comparison_id'] for r in members})!=dataset_run['case_count']:
            raise ValueError('All dataset cases must finish before unblinding')
        for member in members:
            comp=core.load('comparisons',member['comparison_id'])
            expected={x['review_id'] for x in comp['items']}
            actual={r['review_id'] for r in all_reviews if r['comparison_id']==comp['id']}
            if expected!=actual:
                raise ValueError('All dataset cases must be adjudicated before unblinding')
            if comp.get('schema_version',1)>=2 and get_case_assessment(comp['id']) is None:
                raise ValueError('All dataset cases require answerability assessments before unblinding')

def predicate_work(run):
    evaluated=skipped=unresolved=0
    for item in run.get('trace',[]):
        if item.get('outcome')=='skipped': skipped+=1
        elif item.get('outcome')=='error' or (run.get('answer_check_backend')=='local' and not item.get('positive_support')): unresolved+=1
        else: evaluated+=1
    return {'evaluated':evaluated,'skipped':skipped,'unresolved_without_evaluation':unresolved}

def export_bundle(comparison_id):
    """Export only after the same review gates as the unblinded report."""
    summary=report(comparison_id)
    comp=core.load('comparisons',comparison_id)
    source=review_source(comp)
    members=[core.load('snapshots',m['source_id']) for m in source.get('members',[])]
    return {'format':'decision-workbench-comparison-v1',
            'notice':'Contains source text, model responses, and human review details; handle accordingly.',
            'comparison':comp,'source':source,'source_members':members,
            'runs':[{'arm':item['arm'],'record':core.load('runs',item['run_id'])} for item in comp['items']],
            'adjudications':[x for x in core.records('adjudications') if x['comparison_id']==comparison_id],
            'report':summary}

def report(comparison_id, include_outputs=True):
    comp=core.load('comparisons',comparison_id)
    ensure_dataset_reviews_complete(comparison_id)
    assessment=get_case_assessment(comparison_id)
    if comp.get('schema_version',1)>=2 and assessment is None: raise ValueError('Case answerability assessment is required before unblinding')
    reviews={r['review_id']:r for r in core.records('adjudications') if r['comparison_id']==comparison_id}
    if set(reviews) != {x['review_id'] for x in comp['items']}:
        raise ValueError('All items must be adjudicated before unblinding')
    source=review_source(comp)
    rows=[]
    for item in comp['items']:
        run=core.load('runs',item['run_id']); review=reviews[item['review_id']]
        validate_arm_source(comp,item,run,source)
        if review.get('evidence_support')=='supported' and citation_integrity(comp,item,run)=='failed':
            raise ValueError('Citation integrity failed for a supported judgment')
        usage=[call.get('usage') or {} for call in run['calls']]
        search_counts=[]
        for u in usage:
            counts=[v for key in ('server_tool_use_details','server_tool_use') if isinstance(u.get(key),dict)
                    for v in [u[key].get('web_search_requests')] if isinstance(v,int) and not isinstance(v,bool) and v>=0]
            search_counts.append(max(counts) if counts else None)
        observed_search_counts=[v for v in search_counts if v is not None]
        search_complete=len(observed_search_counts)==len(search_counts)
        costs=[u.get('cost') for u in usage]
        valid_costs=[x for x in costs if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>=0]
        answer_check=run.get('answer_check')
        answer_check=answer_check if isinstance(answer_check,dict) else {}
        batches=run.get('local_predicate_batches')
        batch=run.get('local_predicate_batch')
        def recorded_count(value):
            return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
        if run.get('answer_check_backend')=='local' and run['result']['status']=='failed':
            local_count=None
        elif isinstance(batches,list):
            counts=[recorded_count(b.get('inference_count')) if isinstance(b,dict) else None for b in batches]
            local_count=sum(counts) if all(x is not None for x in counts) else None
        elif isinstance(batch,dict): local_count=recorded_count(batch.get('inference_count'))
        elif run.get('answer_check_backend')=='local' and run.get('trace'): local_count=None
        else: local_count=0
        if local_count is not None and answer_check.get('backend')=='local Unsloth MLX': local_count+=1
        rows.append({'arm':item['arm'],'run_id':run['id'],'status':run['result']['status'],
          'verdict':review['verdict'],'evidence_support':review['evidence_support'],
          'reviewer':review['reviewer'],'notes':review['notes'],
          'elapsed_seconds':run['elapsed_seconds'],'calls':len(run['calls']), 'provider_calls':len(run['calls']), 'predicate_work':predicate_work(run), 'execution_policy':run.get('execution_policy','unrecorded'),
          'evidence_mode':run.get('evidence_mode','shared'), 'source_searches':(int('planning_evidence' in run)+int(bool(run.get('targeted_search',{}).get('query')))+sum(len(t.get('retrieval_rounds',[])) for t in run.get('trace',[]))+int('answer_check_evidence' in run)),
          'web_search_requests':sum(observed_search_counts) if search_complete else None,
          'observed_web_search_requests':sum(observed_search_counts) if observed_search_counts else (0 if not search_counts else None),
          'web_search_usage_status':'no provider calls' if not search_counts else ('provider reported' if search_complete else 'incomplete'),
          'local_inferences':local_count, 'local_resource_cost_status':'unobserved' if run.get('answer_check_backend')=='local' else 'not applicable',
          'observed_provider_cost_usd':sum(valid_costs) if valid_costs else None,
          'cost_usd':sum(valid_costs) if run['result']['status'] != 'failed' and costs and len(valid_costs)==len(costs) else None,
          'cost_status':'provider reported' if run['result']['status'] != 'failed' and costs and len(valid_costs)==len(costs) else 'incomplete'})
        if comp['stage']=='practical':
            execution_counts=[]
            for u in usage:
                counts=[v for key in ('server_tool_use_details','server_tool_use') if isinstance(u.get(key),dict)
                        for v in [u[key].get('tool_calls_executed')] if isinstance(v,int) and not isinstance(v,bool) and v>=0]
                execution_counts.append(max(counts) if counts else None)
            observed=[v for v in execution_counts if v is not None]
            complete=len(observed)==len(execution_counts)
            rows[-1]['server_tool_calls_executed']=sum(observed) if complete else None
            rows[-1]['observed_server_tool_calls_executed']=sum(observed) if observed else (0 if not execution_counts else None)
            rows[-1]['server_tool_usage_status']='no provider calls' if not execution_counts else ('provider reported' if complete else 'incomplete')
        if include_outputs:
            rows[-1]['answer']=run['result'].get('answer')
            rows[-1]['reason']=run['result'].get('reason','')
            rows[-1]['source_refs']=run['result'].get('source_refs',[])
            rows[-1]['citations']=run['result'].get('citations',[])
    result={'comparison_id':comparison_id,'stage':comp['stage'], 'status':'adjudicated',
            'interpretation':'Single-case exploratory review; not a benchmark or a research claim.',
            'question':comp['question'],'snapshot_id':comp['snapshot_id'], 'case_assessment':assessment, 'historical_as_known':comp.get('historical_as_known',False), 'targeted':comp.get('targeted'), 'extra_search':comp.get('extra_search'), 'model_config':comp.get('model_config'), 'answer_check_backend':comp.get('answer_check_backend','remote'), 'local_support_threshold':comp.get('local_support_threshold'), 'rows':rows}
    if comp['stage']=='practical':
        result['requested_web_tool_budget_usd']=comp.get('web_tool_budget_usd')
        result['web_budget_interpretation']='Requested tool-loop stop; not a guaranteed cap on total charges.'
    if include_outputs:
        answers=[row['answer'] for row in rows if row['status']=='decided' and isinstance(row['answer'],str)]
        result['answer_texts_differ']=len(set(answers))>1 if len(answers)>1 else None
        result['answer_difference_interpretation']='Exact text comparison only; not a semantic judgment of agreement or correctness.'
    return result
