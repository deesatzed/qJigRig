"""Export bounded, source-bound candidates for the isolated switch prototype."""
from .hitm import _check_sources
from .retrieve import tokens
from .store import corpus_fingerprint, validate_retrievable_ids


def build_snapshot(db, *, task, role, role_version, max_steps, max_characters, max_model_calls=20, include_proposed=False, matched_candidates=False, choice_mode=None, verify_all_sources=True):
    if not all(isinstance(x,str) and x.strip() for x in (task,role,role_version)):
        raise ValueError('task, role and role version are required')
    if len(task)>1000 or len(role)>200 or len(role_version)>100:
        raise ValueError('request text exceeds snapshot limits')
    if type(max_steps) is not int or not 1 <= max_steps <= 20 or type(max_model_calls) is not int or not 1 <= max_model_calls <= 60 or type(max_characters) is not int or not 256 <= max_characters <= 100000 or type(include_proposed) is not bool or type(matched_candidates) is not bool:
        raise ValueError('invalid snapshot budget or proposal scope')
    if type(verify_all_sources) is not bool: raise ValueError('invalid source verification policy')
    if choice_mode not in (None,'bounded-v1'):
        raise ValueError('invalid switch choice mode')
    if verify_all_sources: _check_sources(db)
    validate_retrievable_ids(db)
    fingerprint = corpus_fingerprint(db)
    statuses = ('accepted','proposed') if include_proposed else ('accepted',)
    placeholders = ','.join('?'*len(statuses))
    candidates = []

    def finish_candidate(item, topic_rows):
        original_body = item['body']
        original_title = item['title']
        item['body'] = original_body[:48000]
        item['title'] = original_title[:400]
        item['body_truncated'] = len(original_body)>len(item['body'])
        item['title_truncated'] = len(original_title)>len(item['title'])
        item['topic_annotations'] = [dict(row) for row in topic_rows]
        item['topics'] = list(dict.fromkeys(row['topic'] for row in topic_rows))
        annotation = None
        scope = 'record' if item['record_type'] == 'agent_record' else 'section'
        if item['record_type'] == 'generated_index':
            annotation = db.execute(f"SELECT score,status,method,model,source_revision FROM index_role_annotations WHERE entry_id=? AND role=? AND role_version=? AND source_revision=? AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",(item['id'],role,role_version,item['revision'],*statuses)).fetchone()
            if annotation:
                scope = 'generated_index'
        if annotation is None and item.get('evidence_status') != 'stale':
            column = 'record_id' if item['record_type'] == 'agent_record' else 'section_id'
            target = item.get('source_section_id',item['id'])
            annotation = db.execute(f"SELECT score,status,method,model,source_revision FROM role_annotations WHERE {column}=? AND role=? AND role_version=? AND source_revision IS ? AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",(target,role,role_version,item.get('revision'),*statuses)).fetchone()
        item['role_annotation'] = dict(annotation,scope=scope) if annotation else None
        if not item['body'] or not item['title'] or len(item['topics']) > 50:
            raise ValueError('candidate cannot be represented within snapshot limits')
        item['tier'] = 'initial' if tokens(task) & tokens(item['title']+' '+item['body']+' '+' '.join(item['topics'])) else 'broadened'
        candidates.append(item)

    sections = db.execute('''SELECT s.id,s.title,s.body,s.start_line,s.end_line,x.path,x.revision,x.status AS source_status,
        p.page_start,p.page_end FROM sections s JOIN sources x ON x.id=s.source_id
        LEFT JOIN section_pages p ON p.section_id=s.id WHERE x.status='current' ORDER BY s.id''').fetchall()
    for section in sections:
        topics = db.execute(f"SELECT topic,status,method FROM topic_links WHERE section_id=? AND generated_index_id IS NULL AND status IN ({placeholders}) ORDER BY id",(section['id'],*statuses)).fetchall()
        finish_candidate(dict(section,record_type='section'),topics)
    entries = [] if matched_candidates else db.execute(f'''SELECT g.id,g.title,g.body,g.status AS index_status,g.start_offset,g.end_offset,s.id AS source_section_id,
        s.start_line,s.end_line,x.path,x.revision,x.status AS source_status,p.page_start,p.page_end
        FROM generated_index g JOIN sections s ON s.id=g.section_id JOIN sources x ON x.id=s.source_id
        LEFT JOIN section_pages p ON p.section_id=s.id WHERE x.status='current' AND g.status IN ({placeholders}) ORDER BY g.id''',statuses).fetchall()
    for entry in entries:
        topics = db.execute(f"SELECT topic,status,method FROM topic_links WHERE section_id=? AND (generated_index_id IS NULL OR generated_index_id=?) AND status IN ({placeholders}) ORDER BY id",(entry['source_section_id'],entry['id'],*statuses)).fetchall()
        finish_candidate(dict(entry,record_type='generated_index'),topics)
    records = db.execute("SELECT id,kind,body,producer,status,output_ref FROM records WHERE status IN ('current','proposed') ORDER BY id").fetchall()
    for record in records:
        sources = [dict(row) for row in db.execute('''SELECT s.id AS section_id,x.path,x.revision,x.status AS source_status,s.start_line,s.end_line,p.page_start,p.page_end
            FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id
            LEFT JOIN section_pages p ON p.section_id=s.id WHERE e.record_id=? ORDER BY s.id''',(record['id'],))]
        topics = db.execute(f"SELECT topic,status,method FROM topic_links WHERE record_id=? AND status IN ({placeholders}) ORDER BY id",(record['id'],*statuses)).fetchall()
        item = dict(id=record['id'],title=record['kind'],body=record['body'],producer=record['producer'],record_type='agent_record',source_status=record['status'],output_ref=record['output_ref'],
            evidence=[s['section_id'] for s in sources],evidence_sources=sources,unsupported=not sources,
            evidence_status='unsupported' if not sources else 'stale' if any(s['source_status'] != 'current' for s in sources) else 'current')
        finish_candidate(item,topics)
    if len(candidates)>100:
        raise ValueError('catalog exceeds 100 candidate snapshot limit')
    if verify_all_sources: _check_sources(db)
    if corpus_fingerprint(db) != fingerprint:
        raise ValueError('catalog changed during snapshot')
    result=dict(version=1,task=task,role=role,role_version=role_version,catalog_fingerprint=fingerprint,max_steps=max_steps,max_model_calls=max_model_calls,max_characters=max_characters,candidate_scope='sections_and_records' if matched_candidates else 'variant_specific',candidates=candidates)
    if choice_mode is not None: result['choice_mode']=choice_mode
    if not verify_all_sources: result['source_verification']='deferred_per_candidate'
    return result
