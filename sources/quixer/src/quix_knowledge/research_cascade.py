"""Isolated escalation policy; proposals never mutate or dispatch."""
import copy
import hashlib
import json

_SIGNALS={'decision_unclear','decision_failed','insufficient_evidence','conflicting_evidence','synthesis_requested'}


def escalate(request, *, signal, planner, max_input_characters=12000, verify_sources=None):
    if signal not in _SIGNALS|{'clear'} or not isinstance(request,dict) or not callable(planner) or type(max_input_characters) is not int or max_input_characters<1:
        raise ValueError('invalid escalation request')
    if signal=='clear': return {'status':'not_needed','signal':signal}
    if any(not isinstance(request.get(k),str) or not request[k].strip() for k in ('task_id','query','role','role_version','role_purpose')) or not isinstance(request.get('context'),dict): raise ValueError('role, purpose, task and context required')
    sent=copy.deepcopy(request)
    sent['query'] += f'\nEscalation reason: {signal}. Address uncertainty and cite only supplied source IDs.'
    if 'task' in sent['context']: sent['context']['task']=sent['query']
    raw=json.dumps(sent,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    receipt={'signal':signal,'request_sha256':hashlib.sha256(raw).hexdigest(),'request_characters':len(raw.decode('utf-8')),'model':'tencent/hy4'}
    if receipt['request_characters']>max_input_characters: return {'status':'input_budget_exceeded',**receipt}
    try:
        if verify_sources: verify_sources()
    except Exception:
        return {'status':'source_changed',**receipt}
    try:
        result=planner(sent)
    except TimeoutError:
        return {'status':'timeout','call':None,**receipt}
    except Exception as exc:
        return {'status':'agent_failure','error_type':type(exc).__name__,'call':None,**receipt}
    if not isinstance(result,dict): return {'status':'invalid_response','call':None,**receipt}
    try:
        if verify_sources: verify_sources()
    except Exception:
        return {'status':'source_changed','call':result.get('call'),**receipt}
    if isinstance(result.get('output'),str) and result['output']:
        return {'status':'completed','output':result['output'],'call':result.get('call'),**receipt}
    return {'status':result.get('status','invalid_response'),'call':result.get('call'),**receipt}


def select_context(condition, baseline, rerank, switch, *, limit=3):
    """Choose source-bound rows without dropping the original fallback pool."""
    if condition not in ('baseline','reflex','rerank','combined') or not isinstance(baseline,list) or type(limit) is not int or limit<1: raise ValueError('invalid condition')
    original=copy.deepcopy(baseline)
    ids=[x.get('id') for x in original]
    if any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)): raise ValueError('invalid baseline IDs')
    rank=original; signals=[]
    if condition in ('rerank','combined'):
        candidates=rerank.get('candidates') if isinstance(rerank,dict) else None
        if isinstance(rerank,dict) and rerank.get('status')=='ok' and isinstance(candidates,list) and len(candidates)==len(original) and {x.get('id') for x in candidates}==set(ids):
            originals={x['id']:x for x in original};rank=[]
            for item in candidates:
                row=copy.deepcopy(originals[item['id']])
                if 'rerank_score' in item: row['rerank_score']=item['rerank_score']
                rank.append(row)
        else: signals.append('rerank_unavailable')
    if condition in ('reflex','combined'):
        selected=switch.get('rows') if isinstance(switch,dict) else None
        selected_ids=[x.get('id') for x in selected] if isinstance(selected,list) else []
        originals={x['id']:x for x in original}
        valid=(isinstance(switch,dict) and switch.get('status')=='complete' and selected_ids and len(selected_ids)==len(set(selected_ids)) and set(selected_ids)<=set(ids) and all(isinstance(x.get('body'),str) and x['body'] and originals[x['id']]['body'].startswith(x['body']) for x in selected))
        if valid:
            trusted=[]
            for row in selected:
                item=copy.deepcopy(originals[row['id']]);item['body']=row['body'];item['context_truncated']=bool(row.get('context_truncated')) or row['body']!=originals[row['id']]['body'];trusted.append(item)
            if condition=='reflex': rank=trusted
            else:
                chosen=set(selected_ids);rank=trusted+[x for x in rank if x['id'] not in chosen]
        else: signals.append('insufficient_evidence')
    return rank[:limit],signals


def propose(request, *, planner, verify_sources, max_input_characters=12000):
    """Run an ordinary proposal with point-in-time checks and retained receipts."""
    if not isinstance(request,dict) or type(max_input_characters) is not int or max_input_characters<1: raise ValueError('invalid proposal request')
    raw=json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    receipt={'request_sha256':hashlib.sha256(raw).hexdigest(),'request_characters':len(raw.decode('utf-8'))}
    if receipt['request_characters']>max_input_characters: return {'status':'input_budget_exceeded',**receipt}
    try: verify_sources()
    except Exception: return {'status':'source_changed','call':None,**receipt}
    try: result=planner(copy.deepcopy(request))
    except TimeoutError: return {'status':'timeout','call':None,**receipt}
    except Exception as exc: return {'status':'agent_failure','error_type':type(exc).__name__,'call':None,**receipt}
    if not isinstance(result,dict): return {'status':'invalid_response','call':None,**receipt}
    try: verify_sources()
    except Exception: return {'status':'source_changed','call':result.get('call'),**receipt}
    if isinstance(result.get('output'),str) and result['output']: return {**result,'status':'completed',**receipt}
    return {**result,'status':result.get('status','invalid_response'),**receipt}


def unrecognized_hashes(output, packet):
    """Find full hex tokens absent from supplied IDs and revisions; not a citation validator."""
    import re
    known=set()
    for item in packet.get('results',[]):
        for value in (item.get('id'),item.get('revision')):
            if isinstance(value,str):known.add(value)
        for source in item.get('evidence_sources',[]):
            for value in (source.get('id'),source.get('section_id'),source.get('revision')):
                if isinstance(value,str):known.add(value)
    return sorted(set(re.findall(r'\b[0-9a-f]{64}\b',output))-known)
