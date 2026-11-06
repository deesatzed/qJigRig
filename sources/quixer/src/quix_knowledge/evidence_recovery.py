"""Select source-verified evidence with explicit exclusions and fallback."""
import copy
import hashlib
from pathlib import Path


class EvidenceRejected(ValueError):
    pass


def _source(source):
    if not isinstance(source,dict) or source.get('source_status')!='current': raise EvidenceRejected('stale_evidence')
    path=source.get('path');revision=source.get('revision')
    if not isinstance(path,str) or not path or not isinstance(revision,str) or len(revision)!=64: raise EvidenceRejected('source_unavailable')
    p=Path(path)
    try:
        text=None if p.suffix.lower()=='.pdf' else p.read_text(encoding='utf-8')
        content=p.read_bytes() if text is None else text.encode('utf-8')
    except (OSError,UnicodeError): raise EvidenceRejected('source_unavailable') from None
    if hashlib.sha256(content).hexdigest()!=revision: raise EvidenceRejected('source_changed')
    start,end=source.get('start_line'),source.get('end_line'); ps,pe=source.get('page_start'),source.get('page_end')
    if text is None:
        if type(ps) is not int or type(pe) is not int or ps<1 or pe<ps: raise EvidenceRejected('invalid_anchor')
    elif type(start) is not int or type(end) is not int or start<1 or end<start or end>len(text.splitlines()): raise EvidenceRejected('invalid_anchor')
    return text


def verify_evidence_candidate(item):
    if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not isinstance(item.get('body'),str) or not item['body']: raise EvidenceRejected('invalid_candidate')
    kind=item.get('record_type')
    if kind=='agent_record':
        if item.get('source_status') not in ('current','proposed'): raise EvidenceRejected('stale_evidence')
        if item.get('evidence_status')=='stale': raise EvidenceRejected('stale_evidence')
        refs=item.get('evidence'); sources=item.get('evidence_sources')
        if item.get('unsupported') is not False or item.get('evidence_status')!='current' or not isinstance(refs,list) or not refs or not isinstance(sources,list) or len(sources)!=len(refs) or any(not isinstance(x,str) or not x for x in refs) or len(set(refs))!=len(refs): raise EvidenceRejected('unsupported_evidence')
        if any(not isinstance(s,dict) for s in sources) or {s.get('section_id') for s in sources}!=set(refs): raise EvidenceRejected('unsupported_evidence')
        for source in sources:_source(source)
        return
    if kind not in ('section','generated_index'): raise EvidenceRejected('invalid_candidate')
    if kind=='generated_index' and item.get('index_status') not in ('proposed','accepted'):raise EvidenceRejected('stale_evidence')
    text=_source(item)
    if text is not None:
        span='\n'.join(text.splitlines()[item['start_line']-1:item['end_line']])
        if kind=='generated_index':
            start,end=item.get('start_offset'),item.get('end_offset')
            if type(start) is not int or type(end) is not int or start<0 or end<=start or end>len(span):raise EvidenceRejected('invalid_anchor')
            span=span[start:end]
        if item.get('body_truncated') or item.get('context_truncated'):
            if not span.startswith(item['body']):raise EvidenceRejected('source_span_mismatch')
        elif span!=item['body']:raise EvidenceRejected('source_span_mismatch')


def recover_evidence(preferred, alternatives, *, limit):
    """Inspect in order, replace rejected items, and leave original records intact."""
    if not isinstance(preferred,list) or not isinstance(alternatives,list) or type(limit) is not int or not 1<=limit<=100 or len(preferred)+len(alternatives)>200:raise ValueError('invalid recovery request')
    seen=set();accepted=[];excluded=[]
    for row in preferred+alternatives:
        if len(accepted)>=limit:break
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']:raise ValueError('invalid candidate ID')
        if row['id'] in seen:continue
        seen.add(row['id'])
        try:verify_evidence_candidate(row)
        except EvidenceRejected as exc:
            excluded.append({'id':row['id'],'reason':str(exc)});continue
        accepted.append(copy.deepcopy(row))
    limitations=set()
    for item in accepted:
        if item.get('record_type')=='agent_record':
            limitations.add('agent_claim_not_verified')
            sources=item.get('evidence_sources',[])
        else:sources=[item]
        if any(str(source.get('path','')).lower().endswith('.pdf') for source in sources):limitations.add('pdf_text_not_independently_verified')
    return {'status':'insufficient_evidence' if not accepted else 'recovered' if excluded else 'ok','results':accepted,'excluded':excluded,'shortfall_count':max(0,limit-len(accepted)),'inspected_count':len(seen),'verification_limitations':sorted(limitations)}


def add_recovery_notice(request, recovery):
    """Give the agent a bounded factual notice while preserving request/packet agreement."""
    if not isinstance(request,dict) or not isinstance(request.get('query'),str) or not isinstance(request.get('context'),dict) or not isinstance(recovery,dict) or not isinstance(recovery.get('excluded'),list):raise ValueError('invalid recovery notice')
    result=copy.deepcopy(request); excluded=recovery['excluded']
    if excluded:
        allowed={'unsupported_evidence','stale_evidence','source_unavailable','source_changed','source_span_mismatch','invalid_anchor','invalid_candidate'}
        if any(not isinstance(x,dict) or not isinstance(x.get('id'),str) or not x['id'] or x.get('reason') not in allowed for x in excluded):raise ValueError('invalid exclusion')
        shown=[f"{x['id'][:80]} ({x['reason']})" for x in excluded[:2]]
        notice=' Evidence excluded: '+', '.join(shown)+f'. Additional exclusions: {max(0,len(excluded)-len(shown))}. Treat agent findings as unverified claims.'
        result['query']+=notice
    shortfall=recovery.get('shortfall_count',0)
    if type(shortfall) is not int or shortfall<0:raise ValueError('invalid shortfall')
    if shortfall: result['query']+=f' Fewer verified evidence items than requested: {shortfall} missing.'
    if excluded or shortfall: result['context']['task']=result['query']
    return result


def prepare_recovery_request(task, preferred, alternatives, *, fingerprint, limit, body_characters, role_purpose):
    """Produce a source-checked request or an explicit no-evidence result."""
    from .agent_context import make_agent_packet
    if not isinstance(task,dict) or any(not isinstance(task.get(k),str) or not task[k].strip() for k in ('id','query','role','role_version')) or not isinstance(role_purpose,str) or not role_purpose.strip() or not isinstance(fingerprint,str) or not fingerprint:raise ValueError('invalid task or role')
    recovery=recover_evidence(preferred,alternatives,limit=limit)
    if recovery['status']=='insufficient_evidence':return {'status':'insufficient_evidence','recovery':recovery,'request':None}
    packet=make_agent_packet(task,recovery['results'],fingerprint=fingerprint,body_characters=body_characters,result_limit=limit)
    omitted=len(recovery['results'])-len(packet['results'])
    recovery['packet_omitted_count']=omitted
    recovery['shortfall_count']+=omitted
    if not packet['results']:return {'status':'insufficient_evidence','recovery':recovery,'request':None}
    request={'task_id':task['id'],'query':task['query'],'role':task['role'],'role_version':task['role_version'],'role_purpose':role_purpose,'context':packet,'max_input_characters':12000}
    return {'status':recovery['status'],'recovery':recovery,'request':add_recovery_notice(request,recovery)}


def retrieve_recovered_context(db, task, *, role_purpose, limit=3, body_characters=100):
    """Rank catalog-bound candidates and verify each before creating a request.

    Call verify_recovered_sources immediately before use; the source files may
    change after this function returns. An empty match makes no planner request.
    """
    from .switch_snapshot import build_snapshot
    from .retrieve import search
    from .store import corpus_fingerprint
    snapshot=build_snapshot(db,task=task['query'],role=task['role'],role_version=task['role_version'],max_steps=5,max_characters=12000,matched_candidates=True,verify_all_sources=False)
    rows=search(db,task['query'],variant='baseline',limit=100,ranking='bm25',include_generated=False)
    bound={row['id']:row for row in snapshot['candidates']}
    preferred=[bound[row['id']] for row in rows if row['id'] in bound]
    if corpus_fingerprint(db)!=snapshot['catalog_fingerprint']:raise EvidenceRejected('catalog_changed')
    result=prepare_recovery_request(task,preferred,[],fingerprint=snapshot['catalog_fingerprint'],limit=limit,body_characters=body_characters,role_purpose=role_purpose)
    result['catalog_fingerprint']=snapshot['catalog_fingerprint']
    verify_recovered_sources(db,result)
    return result


def verify_recovered_sources(db, result):
    """Recheck accepted sources and catalog identity immediately before use."""
    from .store import corpus_fingerprint
    if corpus_fingerprint(db)!=result['catalog_fingerprint']:raise EvidenceRejected('catalog_changed')
    for row in result['recovery']['results']:verify_evidence_candidate(row)
    if corpus_fingerprint(db)!=result['catalog_fingerprint']:raise EvidenceRejected('catalog_changed')
