"""Propose source-linked topics and record bounded structure decisions."""
import json
import hashlib
import re
import time

from .decisions import assess_topic, assess_generated_topic, assess_record_topic, judge, decision_metadata
from .ingest import ingest
from .store import validate_retrievable_ids


def _finish_index(db, result, before, started):
    receipts = db.execute('SELECT id,detail FROM decision_receipts WHERE id>? ORDER BY id',(before,)).fetchall()
    usage = [json.loads(row['detail']).get('usage') or {} for row in receipts]
    def complete_sum(key):
        values = [u.get(key) for u in usage]
        return sum(values) if values and all(isinstance(value,(int,float)) and not isinstance(value,bool) for value in values) else None
    result.update(elapsed_seconds=time.monotonic()-started,receipt_ids=[row['id'] for row in receipts],reported_cost=complete_sum('cost'),input_tokens=complete_sum('input_tokens'))
    return result


def _paragraphs(text, max_chars=1200):
    """Extract source spans, splitting long paragraphs without inventing text."""
    for match in re.finditer(r'\S.*?(?=\n[ \t]*\n|\Z)', text, flags=re.DOTALL):
        start, end = match.span()
        while start < end:
            stop = min(end, start + max_chars)
            if stop < end:
                boundary = text.rfind(' ',start,stop)
                if boundary > start:
                    stop = boundary
            while start < stop and text[start].isspace():
                start += 1
            if start < stop:
                yield start, stop
            start = stop


def _propose_generated(db, section, provider, decision_budget):
    created = calls = 0
    for start, end in _paragraphs(section['body']):
        body = section['body'][start:end]
        title_body = re.sub(r'^\s*#{1,6}\s+[^\n]*\n', '', body, count=1)
        title = re.split(r'(?<=[.!?])\s|\n', title_body, maxsplit=1)[0].strip()[:120]
        if not title:
            continue
        entry_id = hashlib.sha256(f"index-v1:{section['id']}:{start}:{end}".encode()).hexdigest()
        existing = db.execute('SELECT status FROM generated_index WHERE id=?',(entry_id,)).fetchone()
        if existing and existing['status'] in ('accepted','rejected'):
            continue
        if existing and existing['status'] == 'stale':
            with db:
                db.execute("UPDATE generated_index SET status='proposed' WHERE id=?",(entry_id,))
            existing = None  # recreate the assessment but retain the existing row
            restored = True
        else:
            restored = False
        if existing:
            assessed = db.execute("SELECT 1 FROM decision_receipts WHERE json_valid(detail) AND json_extract(detail,'$.generated_index_id')=? AND outcome != 'unknown' LIMIT 1",(entry_id,)).fetchone()
            if assessed or provider is None or calls >= decision_budget:
                continue
        judgment = None
        if provider is not None and calls < decision_budget:
            judgment = judge(provider, {'title':title, 'text':body, 'topic':title}, 'topic supported')
            calls += 1
        current = db.execute("SELECT 1 FROM sections JOIN sources ON sections.source_id=sources.id WHERE sections.id=? AND sources.status='current'",(section['id'],)).fetchone()
        if current is None:
            if judgment:
                judgment = dict(judgment,outcome='unknown',reason='source changed during decision')
                with db:
                    db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(judgment.get('provider','unknown'),judgment.get('model'),judgment['outcome'],json.dumps({'section_id':section['id'],'generated_index_id':entry_id,'question':'topic supported',**decision_metadata(judgment)})))
            break
        status = 'rejected' if judgment and judgment['outcome'] == 'unsuitable' else 'proposed'
        with db:
            if existing or restored:
                db.execute('UPDATE generated_index SET status=? WHERE id=?',(status,entry_id))
            else:
                db.execute('INSERT INTO generated_index VALUES (?,?,?,?,?,?,?,?)',(entry_id,section['id'],title,body,start,end,status,'extractive-paragraph-v1'))
            if judgment:
                db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(judgment.get('provider','unknown'),judgment.get('model'),judgment['outcome'],json.dumps({'generated_index_id':entry_id,'question':'topic supported',**decision_metadata(judgment)})))
        created += not bool(existing) and not restored
    return created, calls


def review_generated_entry(db, entry_id, decision, reviewer):
    """Record a named review of a current proposed entry, never a model verdict."""
    if decision not in ('accepted','rejected') or not reviewer or not reviewer.strip():
        raise ValueError('accepted/rejected and a named reviewer are required')
    with db:
        updated = db.execute("UPDATE generated_index SET status=? WHERE id=? AND status='proposed' AND section_id IN (SELECT sections.id FROM sections JOIN sources ON sources.id=sections.source_id WHERE sources.status='current')",(decision,entry_id))
        if updated.rowcount != 1:
            raise ValueError('entry is not a current proposal')
        if decision == 'rejected':
            db.execute("UPDATE topic_links SET status='stale' WHERE generated_index_id=?",(entry_id,))
            db.execute("UPDATE index_role_annotations SET status='stale' WHERE entry_id=?",(entry_id,))
        db.execute('INSERT INTO generated_index_reviews(entry_id,reviewer,decision) VALUES (?,?,?)',(entry_id,reviewer.strip(),decision))


def index_source(db, path, provider=None, max_decisions=10):
    if max_decisions < 0:
        raise ValueError('max_decisions must be nonnegative')
    started = time.monotonic()
    before = db.execute('SELECT COALESCE(MAX(id),0) FROM decision_receipts').fetchone()[0]
    source_id = ingest(db, path)
    if source_id is None:
        return {'source_id': None, 'structure_judgment': None, 'topic_candidates': 0, 'generated_entries': 0, 'decision_calls': 0, 'elapsed_seconds': time.monotonic()-started, 'receipt_ids': [], 'reported_cost': None, 'input_tokens': None}
    sections = db.execute('SELECT * FROM sections WHERE source_id=? ORDER BY start_line', (source_id,)).fetchall()
    result = {'source_id': source_id, 'structure_judgment': None, 'topic_candidates': 0, 'generated_entries': 0, 'decision_calls': 0}
    if provider is not None and max_decisions:
        # A compact structure sample is not a complete document-quality assessment.
        state = {'sections': [{'title': s['title'], 'generated': bool(s['generated']), 'text': s['body'][:1000]} for s in sections[:5]], 'section_count': len(sections)}
        judgment = judge(provider, state, 'structure usable')
        current = db.execute("SELECT 1 FROM sources WHERE id=? AND status='current'",(source_id,)).fetchone()
        if current is None:
            judgment = dict(judgment,outcome='unknown',reason='source changed during decision')
        result['structure_judgment'] = judgment
        result['decision_calls'] += 1
        with db:
            db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)', (judgment.get('provider','unknown'), judgment.get('model'), judgment['outcome'], json.dumps({'source_id': source_id, 'question': 'structure usable', **decision_metadata(judgment)})))
        if current is None:
            result['status'] = 'source_changed'
            return _finish_index(db,result,before,started)
    for section in sections:
        if db.execute("SELECT 1 FROM sources WHERE id=? AND status='current'",(source_id,)).fetchone() is None:
            result['status'] = 'source_changed'
            break
        if section['generated']:
            created, calls = _propose_generated(db, section, provider, max_decisions-result['decision_calls'])
            result['generated_entries'] += created
            result['decision_calls'] += calls
            if db.execute("SELECT 1 FROM sources WHERE id=? AND status='current'",(source_id,)).fetchone() is None:
                result['status'] = 'source_changed'
                break
            continue
        if not section['title'].strip():
            continue
        existing = db.execute('SELECT id,method,status FROM topic_links WHERE section_id=? AND topic=? AND status != ? ORDER BY id DESC LIMIT 1', (section['id'],section['title'],'stale')).fetchone()
        if existing:
            if existing['status'] == 'proposed' and existing['method'] == 'heading' and provider is not None and result['decision_calls'] < max_decisions:
                assess_topic(db, section['id'], section['title'], provider, proposal_id=existing['id'])
                result['decision_calls'] += 1
        else:
            result['topic_candidates'] += 1
            if provider is not None and result['decision_calls'] < max_decisions:
                assess_topic(db, section['id'], section['title'], provider)
                result['decision_calls'] += 1
            else:
                with db:
                    db.execute('INSERT INTO topic_links(section_id,topic,method,status) VALUES (?,?,?,?)', (section['id'], section['title'], 'heading', 'proposed'))
        if db.execute("SELECT 1 FROM sources WHERE id=? AND status='current'",(source_id,)).fetchone() is None:
            result['status'] = 'source_changed'
            break
        structure_rejected = (result['structure_judgment'] or {}).get('outcome') == 'unsuitable'
        if structure_rejected or sum(1 for _ in _paragraphs(section['body'])) > 1:
            created, calls = _propose_generated(db, section, provider, max_decisions-result['decision_calls'])
            result['generated_entries'] += created
            result['decision_calls'] += calls
        if db.execute("SELECT 1 FROM sources WHERE id=? AND status='current'",(source_id,)).fetchone() is None:
            result['status'] = 'source_changed'
            break
    return _finish_index(db,result,before,started)


def map_topics(db, topics, provider, *, max_decisions, include_proposed=False):
    """Assess user-supplied topics across source and agent records with a hard call cap."""
    if provider is None or not callable(provider):
        raise ValueError('a decision provider is required')
    if isinstance(max_decisions,bool) or not isinstance(max_decisions,int) or max_decisions < 0:
        raise ValueError('max_decisions must be a nonnegative integer')
    if not isinstance(topics,list) or not topics or any(not isinstance(t,str) or not t.strip() for t in topics):
        raise ValueError('topics must be a nonempty list of strings')
    topics = [topic.strip() for topic in topics]
    if len({topic.casefold() for topic in topics}) != len(topics):
        raise ValueError('topics must be unique ignoring case')
    validate_retrievable_ids(db)
    targets = [('section',r[0]) for r in db.execute("SELECT sections.id FROM sections JOIN sources ON sources.id=sections.source_id WHERE sources.status='current' ORDER BY sections.id")]
    statuses = ('accepted','proposed') if include_proposed else ('accepted',)
    targets += [('generated_index',r[0]) for r in db.execute("SELECT g.id FROM generated_index g JOIN sections s ON s.id=g.section_id JOIN sources x ON x.id=s.source_id WHERE x.status='current' AND g.status IN (%s) ORDER BY g.id" % ','.join('?'*len(statuses)),statuses)]
    clean_records = """SELECT r.id FROM records r WHERE r.status IN ('proposed','current') AND NOT EXISTS
        (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current') ORDER BY r.id"""
    targets += [('record',r[0]) for r in db.execute(clean_records)]
    excluded = db.execute("""SELECT count(*) FROM records r WHERE r.status IN ('proposed','current') AND EXISTS
        (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""").fetchone()[0]
    pending = []
    skipped = 0
    for kind,target in targets:
        for topic in topics:
            if kind == 'section':
                existing = db.execute("SELECT 1 FROM topic_links WHERE section_id=? AND generated_index_id IS NULL AND topic=? AND status IN ('proposed','accepted','rejected')",(target,topic)).fetchone()
            elif kind == 'generated_index':
                existing = db.execute("SELECT 1 FROM topic_links WHERE generated_index_id=? AND topic=? AND status IN ('proposed','accepted','rejected')",(target,topic)).fetchone()
            else:
                existing = db.execute("SELECT 1 FROM topic_links WHERE record_id=? AND topic=? AND status IN ('proposed','accepted','rejected')",(target,topic)).fetchone()
            if existing:
                skipped += 1
            else:
                pending.append((kind,target,topic))
    started = time.monotonic()
    before = db.execute('SELECT COALESCE(MAX(id),0) FROM decision_receipts').fetchone()[0]
    result = {'decision_calls':0,'remaining_pairs':max(0,len(pending)-max_decisions),'skipped_existing':skipped,'excluded_stale_records':excluded,'target_changed':0,'outcomes':[]}
    functions = {'section':assess_topic,'generated_index':assess_generated_topic,'record':assess_record_topic}
    for kind,target,topic in pending[:max_decisions]:
        try:
            decision = functions[kind](db,target,topic,provider)
        except ValueError:
            result['target_changed'] += 1
            continue
        result['decision_calls'] += 1
        result['outcomes'].append({'target_type':kind,'target_id':target,'topic':topic,'outcome':decision['outcome']})
        if decision.get('reason') in ('source changed during decision','record or evidence changed during decision','index entry or source changed during decision'):
            result['target_changed'] += 1
    return _finish_index(db,result,before,started)
