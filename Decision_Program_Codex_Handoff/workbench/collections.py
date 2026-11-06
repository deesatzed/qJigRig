"""Pinned multi-source snapshots and exact source-level citation mapping."""
import datetime as dt
import hashlib
import re
import uuid
from . import core

def resolve_whitespace_quote(source, quote):
    """Resolve only whitespace differences, requiring a unique source span."""
    if not isinstance(quote,str) or not quote.strip() or len(quote)>10000: raise ValueError('Invalid citation')
    parts=re.split(r'(\s+)',quote)
    pattern=''.join(r'\s+' if part.isspace() else re.escape(part) for part in parts)
    matches=list(re.finditer('(?=('+pattern+'))',source))
    if len(matches)!=1: raise ValueError('Whitespace-normalized citation missing or ambiguous')
    return matches[0].group(1)

def create(title, member_ids):
    if not isinstance(title,str) or not title.strip(): raise ValueError('Collection title is required')
    if not isinstance(member_ids,list) or not 1 <= len(member_ids) <= 20 or len(set(member_ids)) != len(member_ids):
        raise ValueError('Collection requires 1–20 distinct source IDs')
    sources=[core.load('snapshots',ident) for ident in member_ids]
    if any('members' in s for s in sources): raise ValueError('Nested collections are not supported')
    metadata=[(s['scope'],s['effective_from'],s['effective_to']) for s in sources]
    if len(set(metadata)) != 1: raise ValueError('Collection sources must share exact scope and effective dates')
    chunks=[]; members=[]; position=0
    for source in sources:
        if chunks: chunks.append('\n\n'); position+=2
        start=position; chunks.append(source['text']); position+=len(source['text'])
        members.append({'source_id':source['id'],'source_sha256':source['sha256'],
                        'source_metadata_sha256':core.source_metadata_sha256(source),
                        'title':source['title'],'origin':source.get('origin',''),
                        'observed_at':source.get('observed_at',''),'start':start,'end':position})
    text=''.join(chunks); scope,begin,end=metadata[0]
    return core.save('snapshots',{'id':uuid.uuid4().hex,'title':title,'text':text,'scope':scope,
        'effective_from':begin,'effective_to':end,'origin':'pinned collection',
        'sha256':hashlib.sha256(text.encode()).hexdigest(),'members':members,
        'created_at':dt.datetime.now(dt.timezone.utc).isoformat()})

def validate_collection(snapshot, seen=None):
    if 'members' not in snapshot: return
    previous=0
    for n,member in enumerate(snapshot['members']):
        source=core.load('snapshots',member['source_id'],_seen=seen)
        if 'members' in source: raise ValueError('Nested collection not allowed')
        start=member['start']; end=member['end']
        if start != previous+(2 if n else 0) or end != start+len(source['text']): raise ValueError('Invalid collection member offsets')
        if source['title'] != member['title'] or source['sha256'] != member['source_sha256'] or source['text'] != snapshot['text'][start:end]: raise ValueError('Pinned collection source mismatch')
        if source.get('observed_at','') != member.get('observed_at',''): raise ValueError('Pinned collection observation date changed')
        if 'origin' in member and source.get('origin','')!=member['origin']: raise ValueError('Pinned collection source metadata changed')
        if 'source_metadata_sha256' in member and core.source_metadata_sha256(source)!=member['source_metadata_sha256']: raise ValueError('Pinned collection source metadata changed')
        if (source['scope'],source['effective_from'],source['effective_to']) != (snapshot['scope'],snapshot['effective_from'],snapshot['effective_to']): raise ValueError('Pinned collection source scope or dates changed')
        if n and snapshot['text'][previous:start] != '\n\n': raise ValueError('Invalid collection separator')
        previous=end
    if not snapshot['members'] or previous != len(snapshot['text']): raise ValueError('Invalid collection members')

def require_member_metadata(snapshot):
    if any('origin' not in member or 'source_metadata_sha256' not in member for member in snapshot.get('members',[])):
        raise ValueError('Collection member metadata is not pinned; create a new collection before a new experiment')

def span_ref(snapshot,start,end):
    if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(snapshot['text']): raise ValueError('Invalid evidence offsets')
    members=snapshot.get('members') or [{'source_id':snapshot['id'],'source_sha256':snapshot['sha256'],'title':snapshot['title'],'observed_at':snapshot.get('observed_at',''),'start':0,'end':len(snapshot['text'])}]
    for member in members:
        if member['start']<=start and end<=member['end']:
            return {'source_id':member['source_id'],'source_sha256':member['source_sha256'],
                    'source_title':member['title'],'observed_at':member.get('observed_at',''),'source_start':start-member['start'],'source_end':end-member['start']}
    raise ValueError('Evidence crosses a source boundary')

def quote_ref(snapshot, quote):
    if not isinstance(quote,str) or not quote.strip(): raise ValueError('Citation must contain non-whitespace text')
    found=[]; start=0
    while True:
        position=snapshot['text'].find(quote,start)
        if position<0: break
        try: found.append(span_ref(snapshot,position,position+len(quote)))
        except ValueError: pass
        start=position+1
    if len(found)!=1: raise ValueError('Citation missing, ambiguous, or crosses a source boundary')
    return found[0]
