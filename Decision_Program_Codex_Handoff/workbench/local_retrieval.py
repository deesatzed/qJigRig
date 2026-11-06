"""Experimental predicate retrieval and typed support evaluation."""
from . import retrieval
from .local_judge import probe_pairs, support_decision, combine_support

def packet(spans):
    return '\n\n'.join(x['text'] for x in sorted(spans,key=lambda x:x['start']))

def followup_selection(expression, state, targeted):
    from .core import predicate_relevant
    ids=[item['predicate']['id'] for item in state]
    values={item['predicate']['id']:{'true':True,'false':False}.get(item['outcome']) for item in state}
    return [i for i,item in enumerate(state) if item['outcome']=='unknown' and
            (not targeted or predicate_relevant(expression,ids,values,ids[i]))]

def evaluate(source, predicates, threshold, expression, targeted=True, extra_search=True, boundaries=None):
    state=[]
    for p in predicates:
        hits=retrieval.search(source,p['question'],limit=3,boundaries=boundaries)
        state.append({'predicate':p,'spans':hits,'rounds':[{'query':p['question'],'hits':len(hits)}], 'outcome':'unknown'})
    batches=[]
    def score(indices):
        pairs=[]
        for i in indices:
            item=state[i]; context=packet(item['spans']); p=item['predicate']
            pairs.extend([(context,p['positive_claim']),(context,p['negative_claim'])])
        if not pairs: return
        batch=probe_pairs(pairs); batches.append({k:v for k,v in batch.items() if k!='results'})
        for offset,i in enumerate(indices):
            positive,negative=batch['results'][offset*2:offset*2+2]
            state[i]['positive_support']=positive; state[i]['negative_support']=negative
            state[i]['outcome']=combine_support(support_decision(positive,threshold),support_decision(negative,threshold))
    score([i for i,x in enumerate(state) if x['spans']])
    unresolved=[]
    selected=followup_selection(expression,state,targeted) if extra_search else []
    for i in selected:
        item=state[i]
        p=item['predicate']; query=' '.join([p['evidence_requirement'],p['positive_claim'],p['negative_claim']])
        exclude={(s['start'],s['end']) for s in item['spans']}
        extra=retrieval.search(source,query,limit=2,exclude=exclude,boundaries=boundaries)
        item['spans'].extend(extra); item['rounds'].append({'query':query,'hits':len(extra)})
        if extra: unresolved.append(i)
    score(unresolved)
    trace=[]
    for item in state:
        trace.append({'predicate':item['predicate'],'outcome':item['outcome'], 'quote':'',
            'evidence_spans':item['spans'],'retrieval_rounds':item['rounds'],
            'followup_status':('searched' if len(item['rounds'])>1 else ('disabled' if item['outcome']=='unknown' and not extra_search else ('irrelevant_to_expression' if item['outcome']=='unknown' and targeted else 'not_needed'))),
            'positive_support':item.get('positive_support'),'negative_support':item.get('negative_support'),
            'reason':'Lexically retrieved excerpts are incomplete; no match is not evidence of absence.'})
    return trace,batches
