"""Bounded, optional OpenRouter research adapters; no catalog writes."""
import copy
import json
import math
from urllib.request import Request, urlopen


class OpenRouterResearchTransport:
    def __init__(self, api_key, timeout=30):
        if not api_key or not 0 < timeout <= 60: raise ValueError('invalid transport')
        self._api_key=api_key; self.timeout=timeout
    def __call__(self, path, payload):
        if path not in ('/rerank','/embeddings','/alpha/extractions'): raise ValueError('unsupported endpoint')
        base='https://openrouter.ai/api'+('' if path.startswith('/alpha/') else '/v1')
        data=json.dumps(payload,ensure_ascii=False).encode()
        if len(data)>2_000_000: raise ValueError('request too large')
        req=Request(base+path,data=data,headers={'Authorization':'Bearer '+self._api_key,'Content-Type':'application/json'},method='POST')
        with urlopen(req,timeout=self.timeout) as response:
            raw=response.read(5_000_001)
            if len(raw)>5_000_000: raise ValueError('response too large')
            return json.loads(raw)


def _number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def rerank_candidates(task, role, purpose, candidates, transport, *, model='cohere/rerank-5-pro'):
    if not all(isinstance(x,str) and x.strip() for x in (task,role,purpose,model)) or not isinstance(candidates,list) or len(candidates)>100:
        raise ValueError('invalid rerank input')
    if any(not isinstance(x,dict) or not all(isinstance(x.get(k),str) and x[k] for k in ('id','title','body')) for x in candidates) or len({x['id'] for x in candidates})!=len(candidates): raise ValueError('invalid candidates')
    original=copy.deepcopy(candidates)
    if not original: return {'status':'ok','candidates':[],'usage':None,'model':model}
    payload={'model':model,'query':f'Role: {role}. Purpose: {purpose}. Task: {task}',
        'documents':[x['title']+'\n'+x['body'] for x in original],'top_n':len(original)}
    response={}
    try:
        response=transport('/rerank',payload)
        rows=response['results']
        if not isinstance(rows,list) or len(rows)!=len(original): raise ValueError('incomplete results')
        indices=[r['index'] for r in rows]
        if any(type(i) is not int or not 0<=i<len(original) for i in indices) or len(set(indices))!=len(original): raise ValueError('invalid indices')
        if any(not _number(r.get('relevance_score')) or not 0<=r['relevance_score']<=1 for r in rows): raise ValueError('invalid score')
        ordered=[]
        for row in rows:
            item=copy.deepcopy(original[row['index']]); item['rerank_score']=row['relevance_score']; ordered.append(item)
        return {'status':'ok','candidates':ordered,'usage':response.get('usage'),'model':response.get('model',model)}
    except Exception as exc:
        return {'status':'fallback','candidates':original,'usage':response.get('usage') if isinstance(response,dict) else None,'model':response.get('model',model) if isinstance(response,dict) else model,'error_type':type(exc).__name__}


def embed_texts(texts, *, input_type, transport, dimensions=256, model='cohere/embed-5-pro'):
    if input_type not in ('search_query','search_document') or not isinstance(texts,list) or not 1<=len(texts)<=100 or any(not isinstance(t,str) or not t for t in texts) or dimensions not in (256,512,1024,1536,2048): raise ValueError('invalid embedding input')
    response={}
    try:
        response=transport('/embeddings',{'model':model,'input':texts,'input_type':input_type,'dimensions':dimensions})
        data=response['data'];
        if not isinstance(data,list) or len(data)!=len(texts): raise ValueError('wrong vector count')
        indices=[r['index'] for r in data]
        if any(type(i) is not int for i in indices) or set(indices)!=set(range(len(texts))): raise ValueError('wrong vector indices')
        data=sorted(data,key=lambda x:x['index']); vectors=[x['embedding'] for x in data]
        if any(not isinstance(v,list) or len(v)!=dimensions or any(not _number(x) for x in v) or not any(x!=0 for x in v) for v in vectors): raise ValueError('invalid vectors')
        return {'status':'ok','vectors':vectors,'usage':response.get('usage'),'model':response.get('model',model),'input_type':input_type,'dimensions':dimensions}
    except Exception as exc:
        return {'status':'unknown','usage':response.get('usage') if isinstance(response,dict) else None,'error_type':type(exc).__name__}


def extract_metadata(text, fields, transport, *, model='cloudflare/clairic'):
    if not isinstance(text,str) or not text or not isinstance(fields,dict) or not fields or len(fields)>20: raise ValueError('invalid extraction input')
    response={}
    try:
        response=transport('/alpha/extractions',{'model':model,'state':text,'fields':fields})
        answers=response['answers']
        if not isinstance(answers,dict) or set(answers)!=set(fields): raise ValueError('invalid extraction fields')
        for name,answer in answers.items():
            if not isinstance(answer,dict) or answer.get('type')!=fields[name].get('type') or 'value' not in answer: raise ValueError('invalid field')
            for key in ('confidence','p_null'):
                if key in answer and (not _number(answer[key]) or not 0<=answer[key]<=1): raise ValueError('invalid uncertainty')
            if answer['type']=='text' and answer['value'] is not None:
                span=answer.get('span')
                if not isinstance(span,list) or len(span)!=2 or any(type(i) is not int for i in span) or not 0<=span[0]<=span[1]<=len(text) or text[span[0]:span[1]]!=answer['value']: raise ValueError('text span mismatch')
        return {'status':'ok','fields':copy.deepcopy(answers),'usage':response.get('usage'),'model':response.get('model',model),'truncated':response.get('truncated')}
    except Exception as exc:
        return {'status':'unknown','usage':response.get('usage') if isinstance(response,dict) else None,'error_type':type(exc).__name__}


class CohereSearchEmbedder:
    """Use distinct query and document embedding types in the existing hybrid ranker."""
    def __init__(self, transport, dimensions=256):
        self.transport=transport;self.dimensions=dimensions;self.receipts=[]
        self.metadata={'name':'cohere/embed-5-pro','dimensions':dimensions,'input_policy':'query and document input types; provider limits apply'}
    def encode(self,texts):
        if not texts: return []
        query=embed_texts([texts[0]],input_type='search_query',transport=self.transport,dimensions=self.dimensions)
        self.receipts.append({k:v for k,v in query.items() if k!='vectors'})
        if query['status']!='ok': raise ValueError('query embedding unavailable')
        if len(texts)==1:return query['vectors']
        docs=embed_texts(texts[1:],input_type='search_document',transport=self.transport,dimensions=self.dimensions)
        self.receipts.append({k:v for k,v in docs.items() if k!='vectors'})
        if docs['status']!='ok': raise ValueError('document embeddings unavailable')
        return query['vectors']+docs['vectors']
