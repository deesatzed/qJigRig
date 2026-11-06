"""Immutable program drafts and explicitly reviewed, narrowly bound revisions."""
import datetime as dt
import uuid
from . import core

def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def draft(run_id):
    run=core.load('runs',run_id)
    if run.get('mode') != 'fresh' or not run.get('plan'):
        raise ValueError('A successfully validated fresh plan is required')
    core.validate_plan(run['plan'])
    return core.save('programs', {'id':uuid.uuid4().hex, 'revision':1, 'status':'draft',
        'created_at':timestamp(), 'source_run_id':run_id, 'plan':run['plan'],
        'binding':run['request'], 'source_sha256':run['source_sha256'], 'source_metadata_sha256':run.get('source_metadata_sha256'),
        'authoring':'fresh model plan', 'parent_id':None})

def revise(program_id, plan, author, rationale):
    old=core.load('programs',program_id)
    if old.get('status')!='draft': raise ValueError('Only a draft can be edited')
    if not isinstance(author,str) or not author.strip() or not isinstance(rationale,str) or not rationale.strip(): raise ValueError('Author and edit rationale are required')
    core.validate_plan(plan)
    source=core.load('snapshots',old['binding']['snapshot_id'])
    if source['sha256']!=old['source_sha256']: raise ValueError('Source snapshot does not match the draft')
    if old.get('source_metadata_sha256') and core.source_metadata_sha256(source)!=old['source_metadata_sha256']: raise ValueError('Source metadata does not match the draft')
    return core.save('programs',{**old,'id':uuid.uuid4().hex,'revision':old['revision']+1,
        'parent_id':old['id'],'created_at':timestamp(),'plan':plan,'authoring':'human-edited draft',
        'edit_author':author,'edit_rationale':rationale})

def review(program_id, reviewer, rationale):
    old=core.load('programs',program_id)
    if old['status'] != 'draft': raise ValueError('Only a draft can be reviewed')
    if not reviewer.strip() or not rationale.strip(): raise ValueError('Reviewer and review rationale are required')
    core.validate_plan(old['plan'])
    source=core.load('snapshots',old['binding']['snapshot_id'])
    if source['sha256'] != old['source_sha256']: raise ValueError('Source snapshot does not match the draft')
    if old.get('source_metadata_sha256') and core.source_metadata_sha256(source)!=old['source_metadata_sha256']: raise ValueError('Source metadata does not match the draft')
    if core.suspicious_instruction_branch(source['text'],old['plan']):
        raise ValueError('Possible source instruction incorporated into a decision branch; inspect and revise the draft before review')
    return core.save('programs', {**old, 'id':uuid.uuid4().hex, 'revision':old['revision']+1,
        'status':'reviewed', 'parent_id':old['id'], 'created_at':timestamp(),
        'reviewer':reviewer, 'review_rationale':rationale,
        'review_scope':'Exact original question, scope, date and snapshot only; manual review does not establish independent validation.'})

def bind(program_id, request, source):
    program=core.load('programs',program_id)
    if program.get('status') != 'reviewed': raise ValueError('Program is not reviewed')
    if program['binding'] != request: raise ValueError('Reviewed program is only applicable to its exact original request and snapshot')
    if program['source_sha256'] != source['sha256']: raise ValueError('Reviewed program source version mismatch')
    if program.get('source_metadata_sha256') and core.source_metadata_sha256(source)!=program['source_metadata_sha256']: raise ValueError('Reviewed program source metadata mismatch')
    core.validate_plan(program['plan'])
    return program

def bind_intervention(program_id, request, source, reason):
    """Bind one controlled source change as an experiment, not a promotion."""
    if not isinstance(reason,str) or not reason.strip(): raise ValueError('Intervention reason is required')
    program=core.load('programs',program_id)
    if program.get('status')!='reviewed': raise ValueError('Program is not reviewed')
    original_request=program['binding']
    if bool(request.get('historical_as_known',False)) != bool(original_request.get('historical_as_known',False)): raise ValueError('Intervention cannot change historical knowledge mode')
    for key in ('question','scope','as_of'):
        if request.get(key)!=original_request.get(key): raise ValueError('Intervention must keep question, scope, and date unchanged')
    if request.get('snapshot_id')!=source['id']: raise ValueError('Intervention snapshot mismatch')
    original=core.load('snapshots',original_request['snapshot_id'])
    if original['sha256']!=program['source_sha256']: raise ValueError('Original program source mismatch')
    if program.get('source_metadata_sha256') and core.source_metadata_sha256(original)!=program['source_metadata_sha256']: raise ValueError('Original program source metadata mismatch')
    if any(original[k]!=source[k] for k in ('scope','effective_from','effective_to')): raise ValueError('Intervention cannot change scope or effective dates')
    if 'members' not in original:
        if 'members' in source or source.get('parent_snapshot_id')!=original['id']: raise ValueError('Intervention must use a direct derived snapshot')
        if source['sha256']==original['sha256']: raise ValueError('Intervention source text did not change')
        change={'kind':'modified','original_source_id':original['id'],'new_source_id':source['id']}
    else:
        if 'members' not in source: raise ValueError('Intervention must use a derived collection')
        original_ids=[m['source_id'] for m in original['members']]
        new_ids=[m['source_id'] for m in source['members']]
        mapped=[]; changed=[]
        for ident in new_ids:
            current=core.load('snapshots',ident)
            ancestor=ident if ident in original_ids else current.get('parent_snapshot_id')
            if ancestor not in original_ids or ancestor in mapped: raise ValueError('Intervention includes an unrelated or duplicated source')
            mapped.append(ancestor)
            if ident!=ancestor:
                if current['sha256']==core.load('snapshots',ancestor)['sha256']: raise ValueError('Intervention source text did not change')
                changed.append((ancestor,ident))
        if mapped!=[ident for ident in original_ids if ident in mapped]: raise ValueError('Intervention must preserve source order')
        removed=[ident for ident in original_ids if ident not in mapped]
        if len(removed)+len(changed)!=1: raise ValueError('Intervention must change or remove exactly one source')
        change=({'kind':'removed','original_source_id':removed[0],'new_source_id':None} if removed else
                {'kind':'modified','original_source_id':changed[0][0],'new_source_id':changed[0][1]})
    core.validate_plan(program['plan'])
    return {'program':program,'change':{**change,'original_snapshot_id':original['id'],
        'intervention_snapshot_id':source['id'],'reason':reason,
        'interpretation':'Controlled experiment; not a reviewed program revision or evidence of applicability.'}}

def execution_comparison(original, intervention):
    keys=('answer_check_backend','evidence_mode','requested_model','execution_policy','extra_search')
    differences={}; unknown=[]
    for key in keys:
        first=original.get(key); second=intervention.get(key)
        if first is None or second is None: unknown.append(key)
        elif first!=second: differences[key]={'original':first,'intervention':second}
    if original.get('answer_check_backend')=='local' or intervention.get('answer_check_backend')=='local':
        a=original.get('local_support_threshold'); b=intervention.get('local_support_threshold')
        if original.get('answer_check_backend')=='local' and intervention.get('answer_check_backend')=='local':
            if a is None or b is None: unknown.append('local_support_threshold')
            elif a!=b: differences['local_support_threshold']={'original':a,'intervention':b}
            def environment(record):
                batches=list(record.get('local_predicate_batches',[]))
                if record.get('local_predicate_batch') is not None: batches.append(record['local_predicate_batch'])
                if record.get('answer_check') is not None: batches.append(record['answer_check'])
                versions=[batch.get('worker_environment') if isinstance(batch,dict) else None for batch in batches]
                if not versions or any(not isinstance(item,dict) or item!=versions[0] for item in versions): return None
                return versions[0]
            a=environment(original); b=environment(intervention)
            if a is None or b is None: unknown.append('local_worker_environment')
            elif a!=b: differences['local_worker_environment']={'original':a,'intervention':b}
    return {'differences':differences,'unknown':unknown,
            'interpretation':'Recorded settings only; matching fields do not establish identical model behavior or causal comparability.'}

def intervention_report(original_run_id, intervention_run_id):
    original=core.load('runs',original_run_id)
    run=core.load('runs',intervention_run_id)
    if run.get('mode')!='intervention' or not run.get('program_id'): raise ValueError('A recorded intervention run is required')
    program=core.load('programs',run['program_id'])
    valid_origin=(original.get('mode')=='fresh' and program.get('source_run_id')==original_run_id) or (original.get('mode')=='reviewed' and original.get('program_id')==program['id'])
    if not valid_origin: raise ValueError('Baseline run does not match the program provenance')
    if original.get('request')!=program['binding'] or original.get('source_sha256')!=program['source_sha256'] or original.get('plan')!=program['plan']: raise ValueError('Baseline run does not match the reviewed program and request')
    if program.get('source_metadata_sha256') and original.get('source_metadata_sha256')!=program['source_metadata_sha256']:
        raise ValueError('Baseline source metadata does not match the reviewed program')
    if run.get('plan')!=program['plan']: raise ValueError('Intervention plan is missing or does not match the reviewed program')
    snapshot=core.load('snapshots',run['request']['snapshot_id'])
    if run.get('source_sha256')!=snapshot['sha256']: raise ValueError('Intervention source hash is missing or does not match the saved snapshot')
    if run.get('source_metadata_sha256') and run['source_metadata_sha256']!=core.source_metadata_sha256(snapshot): raise ValueError('Intervention source metadata does not match the saved snapshot')
    check=bind_intervention(program['id'],run['request'],snapshot,run.get('intervention',{}).get('reason',''))
    if check['change']!=run.get('intervention'): raise ValueError('Intervention provenance mismatch')
    def summary(record):
        return {'run_id':record['id'],'snapshot_id':record['request']['snapshot_id'],
                'result':record['result'],'trace':record.get('trace',[])}
    before=summary(original); after=summary(run)
    return {'interpretation':'Exact status and answer text comparison only; semantic equivalence and causal correctness require review.',
            'execution_comparison':execution_comparison(original,run),
            'change':run['intervention'],'result_changed':(before['result'].get('status'),before['result'].get('answer')) != (after['result'].get('status'),after['result'].get('answer')),
            'original':before,'intervention':after}
