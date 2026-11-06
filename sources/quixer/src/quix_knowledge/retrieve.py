"""Deterministic lexical retrieval with optional topic and role ranking."""
import re
import json
from .decisions import judge, decision_metadata
from .store import validate_retrievable_ids, corpus_fingerprint

def tokens(text):
    return set(re.findall(r'[\w]+',text.lower()))

def _singular_tokens(text):
    result = set()
    for token in tokens(text):
        if len(token) > 4 and token.endswith('ies'):
            token = token[:-3] + 'y'
        elif len(token) > 4 and token.endswith('s') and not token.endswith(('ss','us','is')):
            token = token[:-1]
        result.add(token)
    return result

def search(db, query, variant='baseline', role=None, role_version=None, provider=None, limit=10, context_chars=None, include_proposed=False, context_tokens=None, count_tokens=None, ranking='overlap', embedder=None, include_generated=True):
    validate_retrievable_ids(db)
    if variant not in {'baseline','topic','decision','role'}:
        raise ValueError('unknown retrieval variant')
    if ranking not in ('overlap','bm25','hybrid'):
        raise ValueError('unknown ranking method')
    if limit < 0:
        raise ValueError('limit must be nonnegative')
    if context_chars is not None and context_chars < 0:
        raise ValueError('context_chars must be nonnegative')
    if context_tokens is not None and (context_tokens < 0 or count_tokens is None or context_chars is not None):
        raise ValueError('token budget requires a counter and excludes character budget')
    if ranking == 'hybrid' and embedder is None:
        raise ValueError('hybrid ranking requires an explicit embedder')
    if limit == 0:
        return []
    before_embedding = corpus_fingerprint(db) if ranking == 'hybrid' else None
    query_tokens = tokens(query)
    rows = db.execute("SELECT sections.*,sources.path,sources.revision,sources.status AS source_status,section_pages.page_start,section_pages.page_end FROM sections JOIN sources ON sources.id=sections.source_id LEFT JOIN section_pages ON sections.id=section_pages.section_id WHERE sources.status='current'").fetchall()
    results = []
    broadened = []
    candidates = [dict(row, record_type='section', evidence=[], unsupported=False) for row in rows]
    warning_pages = {}
    for row in db.execute('SELECT source_id,page FROM extraction_warnings ORDER BY page'):
        warning_pages.setdefault(row['source_id'],[]).append(row['page'])
    for item in candidates:
        item['source_warning_pages'] = warning_pages.get(item['source_id'],[])
    if variant != 'baseline' and include_generated:
        statuses = ('accepted','proposed') if include_proposed else ('accepted',)
        entries = db.execute("SELECT g.*,s.source_id,s.start_line,s.end_line,s.generated,src.path,src.revision,src.status AS source_status,p.page_start,p.page_end FROM generated_index g JOIN sections s ON s.id=g.section_id JOIN sources src ON src.id=s.source_id LEFT JOIN section_pages p ON p.section_id=s.id WHERE src.status='current' AND g.status IN (%s)" % ','.join('?'*len(statuses)), statuses).fetchall()
        for entry in entries:
            item = dict(entry)
            item.update(record_type='generated_index',source_section_id=item.pop('section_id'),index_status=item.pop('status'),evidence=[],unsupported=False,source_warning_pages=warning_pages.get(item['source_id'],[]))
            candidates.append(item)
    for record in db.execute("SELECT * FROM records WHERE status IN ('current','proposed')").fetchall():
        item = dict(record)
        refs = db.execute('SELECT evidence.section_id,sources.status FROM evidence JOIN sections ON sections.id=evidence.section_id JOIN sources ON sources.id=sections.source_id WHERE evidence.record_id=? ORDER BY evidence.section_id',(item['id'],)).fetchall()
        evidence = [r[0] for r in refs]
        evidence_status = 'unsupported' if not refs else 'stale' if any(r[1] != 'current' for r in refs) else 'current'
        item.update(record_type='agent_record',title=item['kind'],path=None,revision=None,source_status=item['status'],evidence=evidence,unsupported=not evidence,evidence_status=evidence_status,output_ref_status='unverified' if item['output_ref'] else None)
        candidates.append(item)
    dense_scores = [None] * len(candidates)
    if ranking in ('bm25','hybrid'):
        from .bm25 import score_documents
        corpus = [item['title']+' '+item['body'] for item in candidates if item['record_type'] != 'generated_index']
        lexical_scores = score_documents(query,[item['title']+' '+item['body'] for item in candidates],corpus=corpus)
    else:
        lexical_scores = [len(query_tokens & tokens(item['title']+' '+item['body'])) for item in candidates]
    if ranking == 'hybrid' and candidates:
        try:
            from .hybrid import similarities
            dense_scores = similarities(embedder,query[:4000],[item['title'][:512]+'\n'+item['body'][:8000] for item in candidates])
        except Exception as exc:
            fallback = search(db,query,variant=variant,role=role,role_version=role_version,provider=provider,limit=limit,context_chars=context_chars,include_proposed=include_proposed,context_tokens=context_tokens,count_tokens=count_tokens,ranking='bm25',include_generated=include_generated)
            if not fallback:
                raise RuntimeError('embedding unavailable and lexical fallback returned no results') from exc
            for item in fallback:
                item['embedding_fallback_reason'] = 'embedding_unavailable'
                item['requested_ranking'] = 'hybrid'
            return fallback
        if corpus_fingerprint(db) != before_embedding:
            raise RuntimeError('catalog changed during embedding')
    lexical_order = sorted((i for i,value in enumerate(lexical_scores) if value > 0),key=lambda i:(-lexical_scores[i],candidates[i]['id']))
    dense_order = sorted((i for i,value in enumerate(dense_scores) if value is not None and value > 0),key=lambda i:(-dense_scores[i],candidates[i]['id']))
    lexical_ranks = {i:rank for rank,i in enumerate(lexical_order,1)}
    dense_ranks = {i:rank for rank,i in enumerate(dense_order,1)}
    zero_vectors = sum(value is None for value in dense_scores) if ranking == 'hybrid' else 0
    for i, (item, lexical) in enumerate(zip(candidates,lexical_scores)):
        column = 'record_id' if item['record_type'] == 'agent_record' else 'section_id'
        annotation_id = item['source_section_id'] if item['record_type'] == 'generated_index' else item['id']
        allowed_statuses = ('accepted','proposed') if include_proposed and variant != 'baseline' else ('accepted',)
        condition = '(generated_index_id IS NULL OR generated_index_id=?)' if item['record_type'] == 'generated_index' else 'generated_index_id IS NULL'
        parameters = (annotation_id,*allowed_statuses,item['id']) if item['record_type'] == 'generated_index' else (annotation_id,*allowed_statuses)
        query_topics = f"SELECT id,topic,status,method,generated_index_id FROM topic_links WHERE {column}=? AND status IN ({','.join('?'*len(allowed_statuses))}) AND {condition} ORDER BY id"
        topic_annotations = [dict(r) for r in db.execute(query_topics,parameters)]
        topics = [r['topic'] for r in topic_annotations]
        if item['record_type'] == 'generated_index':
            topics.append(item['title'])
            topic_annotations.append({'id':None,'topic':item['title'],'status':item['index_status'],'method':item['method'],'generated_index_id':item['id']})
        topic = len(query_tokens & tokens(' '.join(topics))) if variant != 'baseline' else 0
        broad_text = item['title']+' '+item['body']+(' '+' '.join(topics) if variant != 'baseline' else '')
        broad_score = len(_singular_tokens(query) & _singular_tokens(broad_text))
        if not lexical and not topic and not broad_score and i not in dense_ranks:
            continue
        item.update(lexical_score=lexical,topic_score=topic,topics=topics,topic_annotations=topic_annotations,ranking_method=ranking,dense_similarity=dense_scores[i],embedding_metadata=getattr(embedder,'metadata',None) if ranking == 'hybrid' else None,role_score=None,role_score_status=None,role_score_method=None,role_score_model=None,role_score_scope=None,decision=None)
        if ranking == 'hybrid':
            item['embedding_issue'] = 'zero_document_vector' if dense_scores[i] is None else None
            item['embedding_zero_vector_count'] = zero_vectors
            item['embedding_text_truncated'] = len(item['title']) > 512 or len(item['body']) > 8000
            item['embedding_query_truncated'] = len(query) > 4000
            item['embedding_may_token_truncate'] = bool((item['embedding_metadata'] or {}).get('max_input_tokens'))
        if variant == 'role' and role and role_version:
            annotation = None
            scope = 'record' if item['record_type'] == 'agent_record' else 'section'
            if item['record_type'] == 'generated_index':
                annotation = db.execute("SELECT score,status,method,model FROM index_role_annotations WHERE entry_id=? AND role=? AND role_version=? AND source_revision=? AND status IN ('accepted','proposed') ORDER BY id DESC LIMIT 1",(item['id'],role,role_version,item['revision'])).fetchone()
                if annotation:
                    scope = 'generated_index'
            if annotation is None:
                annotation = db.execute(f"SELECT score,status,method,model FROM role_annotations WHERE {column}=? AND role=? AND role_version=? AND source_revision IS ? AND status IN ('accepted','proposed') ORDER BY id DESC LIMIT 1",(annotation_id,role,role_version,item['revision'])).fetchone()
            if annotation:
                item['role_score'] = annotation['score']
                item['role_score_status'] = annotation['status']
                item['role_score_method'] = annotation['method']
                item['role_score_model'] = annotation['model']
                item['role_score_scope'] = scope
        if ranking == 'hybrid':
            base = (1/(60+lexical_ranks[i]) if i in lexical_ranks else 0) + (1/(60+dense_ranks[i]) if i in dense_ranks else 0) + 0.003*min(topic,3)
        else:
            base = lexical + (0.05*topic if ranking == 'bm25' else topic)
        role_boost = (min(0.25,0.1*base) if ranking in ('bm25','hybrid') else 0.25) * item['role_score'] if item['role_score'] is not None else 0
        item['score'] = base + role_boost
        if lexical or topic or i in dense_ranks:
            results.append(item)
        else:
            item['score'] += broad_score
            item['fallback_reason'] = 'lexical_broadened'
            broadened.append(item)
    if not results:
        results = broadened
    if ranking == 'hybrid' and candidates and not results and zero_vectors:
        raise RuntimeError('embedding produced incomplete document vectors and search returned no results')
    results = sorted(results,key=lambda x:(-x['score'],x['id']))[:limit]
    if variant in {'decision','role'} and provider is not None:
        source_changed = False
        for item in results:
            item['decision'] = judge(provider, {'query':query,'title':item['title'],'text':item['body'][:4000], 'text_truncated':len(item['body']) > 4000}, 'relevant')
            decision = item['decision']
            if item['record_type'] == 'agent_record':
                current = db.execute("SELECT 1 FROM records WHERE id=? AND status IN ('current','proposed')",(item['id'],)).fetchone()
                refs = db.execute('SELECT sources.status FROM evidence JOIN sections ON sections.id=evidence.section_id JOIN sources ON sources.id=sections.source_id WHERE evidence.record_id=?',(item['id'],)).fetchall()
                evidence_status = 'unsupported' if not refs else 'stale' if any(r[0] != 'current' for r in refs) else 'current'
                source_changed = current is None or evidence_status != item['evidence_status']
            else:
                current = db.execute("SELECT 1 FROM sources WHERE id=? AND status='current' AND revision=?",(item['source_id'],item['revision'])).fetchone()
                source_changed = current is None
                if item['record_type'] == 'generated_index':
                    source_changed = source_changed or db.execute("SELECT 1 FROM generated_index WHERE id=? AND status IN ('accepted','proposed')",(item['id'],)).fetchone() is None
            if source_changed:
                decision = item['decision'] = dict(decision,outcome='unknown',reason='source changed during decision')
            adjustment = {'supported':1,'unsuitable':-1}.get(decision['outcome'],0)
            item['score'] += adjustment * (min(0.1,0.1*item['score']) if ranking in ('bm25','hybrid') else 0.1)
            db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(decision.get('provider','unknown'),decision.get('model'),decision['outcome'],json.dumps({'item_id':item['id'],'query':query,**decision_metadata(decision)})))
            if source_changed:
                break
        outcomes = [item['decision']['outcome'] for item in results if item['decision'] is not None]
        if source_changed or any(outcome in ('unknown','unclear') for outcome in outcomes):
            reason = 'source_changed' if source_changed else 'decision_unknown' if 'unknown' in outcomes else 'decision_unclear'
            baseline = search(db,query,variant='baseline',limit=limit,ranking=ranking,embedder=embedder)
            decisions = {item['id']:item['decision'] for item in results}
            results = baseline if source_changed else baseline or results
            for item in results:
                item['decision'] = decisions.get(item['id'])
                if item.get('fallback_reason') == 'lexical_broadened':
                    item['lexical_fallback_reason'] = 'lexical_broadened'
                item['fallback_reason'] = reason if baseline else reason + '_baseline_empty'
    db.commit()
    results = sorted(results,key=lambda x:(-x['score'],x['id']))
    if context_tokens is not None:
        def count_text(text):
            count = count_tokens(text)
            if isinstance(count,bool) or not isinstance(count,int) or count < 0:
                raise ValueError('token counter must return nonnegative integers')
            return count
        if count_text('') != 0:
            raise ValueError('token counter must return zero for empty text')
        remaining = context_tokens
        bounded = []
        for item in results:
            if remaining <= 0:
                break
            original = item['body']
            count = count_text(original)
            if count > remaining:
                lo, hi = 0, len(original)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if count_text(original[:mid]) <= remaining:
                        lo = mid
                    else:
                        hi = mid-1
                item['body'] = original[:lo]
                count = count_text(item['body'])
            item['context_token_count'] = count
            item['context_truncated'] = len(item['body']) < len(original)
            remaining -= count
            bounded.append(item)
        return bounded
    if context_chars is not None:
        remaining = context_chars
        bounded = []
        for item in results:
            if remaining <= 0:
                break
            original = item['body']
            item['body'] = original[:remaining]
            item['context_truncated'] = len(item['body']) < len(original)
            remaining -= len(item['body'])
            bounded.append(item)
        return bounded
    return results
