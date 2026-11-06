import pytest


def test_rerank_preserves_source_candidates_and_falls_back_on_invalid_indices():
    from quix_knowledge.research_providers import rerank_candidates
    candidates=[{'id':'a','title':'Alpha','body':'first','revision':'1'},{'id':'b','title':'Beta','body':'second','revision':'2'}]
    def service(path,payload):
        assert path=='/rerank' and 'reviewer' in payload['query']
        return {'model':'cohere/rerank-5-pro','results':[{'index':1,'relevance_score':0.9},{'index':0,'relevance_score':0.2}],'usage':{'cost':0.01}}
    result=rerank_candidates('task','reviewer','verify evidence',candidates,service)
    assert [x['id'] for x in result['candidates']]==['b','a']
    assert result['candidates'][0]['revision']=='2'
    bad=rerank_candidates('task','reviewer','verify evidence',candidates,lambda *_:{'results':[{'index':1,'relevance_score':0.9},{'index':1,'relevance_score':0.2}],'usage':{'cost':0.02}})
    assert bad['status']=='fallback' and bad['candidates']==candidates and bad['usage']['cost']==0.02
    missing=rerank_candidates('task','reviewer','verify evidence',candidates,lambda *_:{'results':[{'index':0,'relevance_score':0.5}]})
    assert missing['status']=='fallback' and missing['candidates']==candidates


def test_embedding_uses_query_document_types_and_rejects_wrong_dimensions():
    from quix_knowledge.research_providers import embed_texts
    seen=[]
    def service(path,payload):
        seen.append(payload)
        return {'model':'embed-v5.0-pro','data':[{'index':i,'embedding':[1.0]*256} for i,_ in enumerate(payload['input'])],'usage':{'cost':0.01}}
    result=embed_texts(['a','b'],input_type='search_document',transport=service,dimensions=256)
    assert result['status']=='ok' and seen[0]['input_type']=='search_document' and len(result['vectors'])==2
    bad=embed_texts(['q'],input_type='search_query',transport=lambda *_:{'data':[{'index':0,'embedding':[float('nan')]*256}]},dimensions=256)
    assert bad['status']=='unknown'


def test_clairic_retains_null_and_span_without_promoting_guess():
    from quix_knowledge.research_providers import extract_metadata
    answers={'author':{'type':'text','value':None,'guess':'A','confidence':0.99,'p_null':0.99,'span':[0,1]}}
    result=extract_metadata('A source',{'author':{'type':'text','instructions':'author'}},lambda *_:{'model':'cloudflare/clairic','answers':answers,'usage':{'cost':0.1}})
    assert result['status']=='ok' and result['fields']['author']['value'] is None
    assert result['fields']['author']['guess']=='A'
    assert extract_metadata('A',{'author':{'type':'text'}},lambda *_: {'answers':{'author':{'value':'invented','type':'text','span':[0,1]}}})['status']=='unknown'
