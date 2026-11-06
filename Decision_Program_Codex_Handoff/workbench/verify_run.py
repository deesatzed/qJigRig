"""Recheck saved source bindings and deterministic composition without model calls."""
from . import core


def verify(run_id):
    run=core.load('runs',run_id)
    request=run.get('request',{})
    result={'run_id':run_id,'source':'unavailable','composition':'unavailable',
            'citations':'unavailable','issues':[],
            'interpretation':'Checks recorded data and deterministic logic only; does not rerun models or establish semantic support, correctness, or authenticity.'}
    snapshot_id=request.get('snapshot_id')
    if not snapshot_id:
        result['issues'].append('Run has no pinned source ID')
        return result
    try:
        source=core.load('snapshots',snapshot_id)
        if source['sha256']!=run.get('source_sha256'): raise ValueError('Source text hash differs from recorded run')
        metadata=run.get('source_metadata_sha256')
        if metadata and core.source_metadata_sha256(source)!=metadata: raise ValueError('Source metadata differs from recorded run')
        result['source']='verified' if metadata else 'text verified; metadata not recorded'
        if any('origin' not in member or 'source_metadata_sha256' not in member for member in source.get('members',[])):
            result['source']=('text and collection metadata verified' if metadata else result['source'])+'; member metadata not pinned'
    except (ValueError,KeyError,FileNotFoundError) as exc:
        result['source']='failed'; result['issues'].append(str(exc)); return result
    members={m['source_id']:core.load('snapshots',m['source_id']) for m in source.get('members',[])}
    if not members: members={source['id']:source}
    refs=[]; unbound=[]
    def add(quote,ref,context=False):
        if quote:
            if isinstance(ref,dict): refs.append((quote,ref,context))
            else: unbound.append(quote)
    def add_many(quotes,source_refs):
        if not isinstance(quotes,list) or not isinstance(source_refs,list): raise ValueError('Invalid citation arrays')
        for i,quote in enumerate(quotes): add(quote,source_refs[i] if i<len(source_refs) else None)
        if len(source_refs)>len(quotes): raise ValueError('Citation reference lacks matching text')
    outcome=run.get('result',{})
    try:
        add_many(outcome.get('quotes',[]),outcome.get('source_refs',[]))
        if outcome.get('quotes'):
            if outcome.get('quote') and outcome['quote']!=outcome['quotes'][0]:
                raise ValueError('Single citation conflicts with the citation list')
            if outcome.get('source_ref') and (not outcome.get('source_refs') or outcome['source_ref']!=outcome['source_refs'][0]):
                raise ValueError('Single citation reference conflicts with the citation list')
        if not outcome.get('quotes'): add(outcome.get('quote'),outcome.get('source_ref'))
        check=run.get('answer_check') or {}
        add_many(check.get('quotes',[]),check.get('source_refs',[]))
    except (ValueError,TypeError,AttributeError) as exc:
        result['citations']='failed'; result['issues'].append(str(exc)); return result
    missing_predicate_evidence=False
    for item in run.get('trace',[]):
        if item.get('outcome') in ('true','false') and not item.get('quote') and not any(span.get('text') for span in item.get('evidence_spans',[])):
            missing_predicate_evidence=True
        add(item.get('quote'),item.get('source_ref'),bool(item.get('quote_scope')) or item.get('outcome') not in ('true','false'))
        for span in item.get('evidence_spans',[]): add(span.get('text'),span.get('source_ref'),True)
    if any(not isinstance(quote,str) or not quote.strip() for quote in [q for q,_,_ in refs]+unbound):
        result['citations']='failed'; result['issues'].append('Recorded citation must contain non-whitespace text')
    elif refs:
        result['citations']=('partial; predicate evidence not recorded' if missing_predicate_evidence else
                             'partial; some quotes lack references' if unbound else
                             'context verified; not localized support' if all(context for _,_,context in refs) else 'verified')
        for quote,ref,_ in refs:
            member=members.get(ref.get('source_id')); start=ref.get('source_start'); end=ref.get('source_end')
            if (not member or member['sha256']!=ref.get('source_sha256') or not isinstance(start,int) or isinstance(start,bool)
                    or not isinstance(end,int) or isinstance(end,bool) or not 0<=start<end<=len(member['text']) or member['text'][start:end]!=quote):
                result['citations']='failed'; result['issues'].append('Recorded citation does not match its pinned source and offsets'); break
            if (('source_title' in ref and ref['source_title']!=member.get('title')) or
                    ('observed_at' in ref and ref['observed_at']!=member.get('observed_at',''))):
                result['citations']='failed'; result['issues'].append('Recorded citation attribution does not match its pinned source metadata'); break
            if 'source_title' not in ref or 'observed_at' not in ref:
                result['citations']='partial; citation attribution metadata not recorded'
    elif missing_predicate_evidence:
        result['citations']='unavailable; predicate evidence not recorded'
    elif unbound:
        result['citations']='unavailable; quotes lack references'
    plan=run.get('plan'); trace=run.get('trace',[])
    if plan and trace:
        try:
            core.validate_plan(plan)
            predicates={p['id']:p for p in plan['predicates']}; ids=list(predicates)
            values={}
            for item in trace:
                ident=item['predicate']['id']
                if ident not in ids or ident in values: raise ValueError('Trace contains an unknown or duplicate predicate')
                if item['predicate']!=predicates[ident]: raise ValueError('Trace predicate differs from the recorded plan')
                if item.get('outcome') not in ('true','false','unknown','conflict','skipped','error'): raise ValueError('Invalid trace outcome')
                values[ident]={'true':True,'false':False}.get(item['outcome'])
            value=core.stable_outcome(plan['expression'],ids,values)
            candidate=run.get('candidate_result')
            if candidate is not None:
                expected=plan['true_answer' if value else 'false_answer'] if value is not None else None
                if value is None or candidate.get('answer')!=expected: raise ValueError('Recorded candidate does not match composed predicate outcomes')
                if outcome.get('status')=='decided' and outcome.get('answer')!=candidate.get('answer'): raise ValueError('Final answer does not match recorded candidate')
            result['composition']='verified' if candidate is not None else 'recomputed; no candidate recorded'
            result['recomputed_expression_value']=value
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            result['composition']='failed'; result['issues'].append(str(exc))
    return result
