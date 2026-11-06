"""Deterministic bounded lexical retrieval with exact character offsets."""
import math
import re

STOP=frozenset('a an and are as at be by can does for from has how in is it its of on or that the their these this to was what when where which who why with'.split())

def terms(text):
    return {word for word in re.findall(r'(?<![\w.])\d+(?:\.\d+)+(?:[a-z][a-z0-9]*)?(?!\w|\.\d)|[\w]+',text.casefold()) if len(word)>1 and word not in STOP}

def spans(source,max_chars=1200):
    if not 100 <= max_chars <= 5000: raise ValueError('Invalid span size')
    for match in re.finditer(r'\S(?:.*?\S)?(?=(?:\r\n|\r(?!\n)|\n)[^\S\r\n]*(?:\r\n|\r(?!\n)|\n)|\Z)',source,re.DOTALL):
        start,end=match.span()
        while start < end:
            stop=min(end,start+max_chars)
            if stop < end:
                boundary=source.rfind(' ',start+max_chars//2,stop)
                if boundary>start: stop=boundary
            if source[start:stop].strip(): yield {'start':start,'end':stop,'text':source[start:stop]}
            start=stop

def search(source, query, limit=3, max_chars=1200, exclude=frozenset(), boundaries=None):
    if not 1<=limit<=20: raise ValueError('Invalid retrieval limit')
    query_terms=terms(query)
    if not query_terms: return []
    items=list(spans(source,max_chars))
    # A reStructuredText directive names the indented paragraph after its blank line.
    # Preserve that local binding only when both parts fit within one source member.
    directive_ends={m.end():m.start() for m in re.finditer(
        r'(?<![^\r\n])\.\. (?:function|method|class|data|attribute)::[^\r\n]+(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)[ \t]+',source)}
    version_annotation=re.compile(r'(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)[ \t]+\.\. (?:versionadded|versionchanged|deprecated)::[^\r\n]+')
    for item in items:
        start=directive_ends.get(item['start'])
        if start is not None and item['end']-start<=max_chars and (boundaries is None or any(a<=start and item['end']<=b for a,b in boundaries)):
            item['start']=start;item['text']=source[start:item['end']]
            while True:
                annotation=version_annotation.match(source,item['end'])
                if not annotation or annotation.end()-start>max_chars or (boundaries is not None and not any(a<=start and annotation.end()<=b for a,b in boundaries)):
                    break
                item['end']=annotation.end();item['text']=source[start:item['end']]
    # A joined passage subsumes its directive-only paragraph; count it once.
    widest={}
    for item in items:
        if item['start'] not in widest or item['end']>widest[item['start']]['end']:
            widest[item['start']]=item
    items=[]; covered_end=-1
    for item in sorted(widest.values(),key=lambda x:(x['start'],-x['end'])):
        if item['end']<=covered_end: continue
        items.append(item);covered_end=max(covered_end,item['end'])
    docs=[terms(item['text']) for item in items]
    counts={term:sum(term in words for words in docs) for term in query_terms}
    scored=[]
    for item,words in zip(items,docs):
        if (item['start'],item['end']) in exclude: continue
        matched=query_terms & words
        if not matched: continue
        score=sum(math.log((1+len(items))/(1+counts[w]))+1 for w in matched)
        scored.append({**item,'score':round(score,6),'matched_terms':sorted(matched)})
    return sorted(scored,key=lambda x:(-x['score'],x['start']))[:limit]

def exposed_quote(quote, evidence_spans, source=None, source_start=None):
    if not isinstance(quote,str) or not quote.strip(): return False
    if source is None:
        return any(quote in span['text'] for span in evidence_spans)
    if not isinstance(source,str): return False
    intervals=[]
    for span in evidence_spans:
        start,end=span.get('start'),span.get('end')
        if (isinstance(start,int) and not isinstance(start,bool) and isinstance(end,int) and not isinstance(end,bool)
                and 0<=start<end<=len(source) and source[start:end]==span.get('text')):
            intervals.append((start,end))
    if source_start is not None:
        if not isinstance(source_start,int) or isinstance(source_start,bool) or source_start<0 or source[source_start:source_start+len(quote)]!=quote: return False
        return all(char.isspace() or any(a<=source_start+i<b for a,b in intervals) for i,char in enumerate(quote))
    start=source.find(quote)
    while start>=0:
        if all(char.isspace() or any(a<=start+i<b for a,b in intervals) for i,char in enumerate(quote)):
            return True
        start=source.find(quote,start+1)
    return False
