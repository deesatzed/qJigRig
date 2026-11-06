"""Validate provider responses; errors are unknown, never a negative judgment."""
import json
import math
from .store import validate_retrievable_ids

def decision_metadata(result):
    """Retain score semantics and usage without storing authentication data."""
    keys = ('probability','probability_status','legal_mass','stability','usage','request_id','thresholds','prompt_version','reason')
    return {key:result.get(key) for key in keys}

def judge(provider, state, question):
    try:
        result = provider(state, question)
        if not isinstance(result, dict) or result.get('outcome') not in {'supported','unclear','unsuitable'} or not isinstance(result.get('provider'),str):
            return {'outcome':'unknown','provider':'unknown','reason':'invalid response'}
        usage = result.get('usage')
        if usage is not None:
            result = dict(result)
            result['usage'] = {key:value for key,value in usage.items() if key in ('cost','input_tokens','output_tokens') and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value >= 0} if isinstance(usage,dict) else None
        return result
    except Exception as exc:
        return {'outcome':'unknown','provider':'unknown','reason':type(exc).__name__}

def assess_topic(db, section_id, topic, provider, proposal_id=None):
    section = db.execute('SELECT title,body FROM sections WHERE id=?',(section_id,)).fetchone()
    if section is None:
        raise ValueError('unknown section')
    result = judge(provider, {'title':section['title'],'text':section['body'][:4000],'text_truncated':len(section['body']) > 4000,'topic':topic}, 'topic supported')
    # Even supported model proposals require independent acceptance.
    status = 'rejected' if result['outcome'] == 'unsuitable' else 'proposed'
    with db:
        current = db.execute("SELECT 1 FROM sections JOIN sources ON sections.source_id=sources.id WHERE sections.id=? AND sources.status='current'",(section_id,)).fetchone()
        if current is None:
            result = dict(result,outcome='unknown',reason='source changed during decision')
        elif proposal_id is None:
            method = 'heading' if result['outcome'] == 'unknown' else 'decision'
            db.execute('INSERT INTO topic_links(section_id,topic,method,status) VALUES (?,?,?,?)',(section_id,topic,method,status))
        elif current:
            method = 'heading' if result['outcome'] == 'unknown' else 'decision'
            updated = db.execute("UPDATE topic_links SET method=?,status=? WHERE id=? AND section_id=? AND topic=? AND status='proposed'",(method,status,proposal_id,section_id,topic))
            if updated.rowcount != 1:
                raise ValueError('proposal no longer available')
        db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(result.get('provider','unknown'),result.get('model'),result['outcome'],json.dumps({'section_id':section_id,'topic':topic,**decision_metadata(result)})))
    return result

def assess_record_topic(db, record_id, topic, provider):
    """Assess a proposed topic for an agent record without endorsing its claim."""
    if not isinstance(topic,str) or not topic.strip():
        raise ValueError('topic is required')
    record = db.execute("""SELECT kind,body FROM records r WHERE id=? AND status IN ('proposed','current') AND NOT EXISTS
        (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""",(record_id,)).fetchone()
    if record is None:
        raise ValueError('record is not current or proposed')
    result = judge(provider,{'title':record['kind'],'text':record['body'][:4000],'text_truncated':len(record['body'])>4000,'topic':topic},'topic supported')
    with db:
        current = db.execute("""SELECT 1 FROM records r WHERE r.id=? AND r.status IN ('proposed','current') AND NOT EXISTS
            (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""",(record_id,)).fetchone()
        if current is None:
            result = dict(result,outcome='unknown',reason='record or evidence changed during decision')
        else:
            status = 'rejected' if result['outcome'] == 'unsuitable' else 'proposed'
            db.execute('INSERT INTO topic_links(record_id,topic,method,status) VALUES (?,?,?,?)',(record_id,topic,'decision',status))
        db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(result.get('provider','unknown'),result.get('model'),result['outcome'],json.dumps({'record_id':record_id,'topic':topic,'question':'topic supported',**decision_metadata(result)})))
    return result

def assess_generated_topic(db, entry_id, topic, provider):
    """Assess a topic for one generated span without assigning it to its parent."""
    if not isinstance(topic,str) or not topic.strip():
        raise ValueError('topic is required')
    query = """SELECT g.title,g.body,g.section_id FROM generated_index g JOIN sections s ON s.id=g.section_id
        JOIN sources x ON x.id=s.source_id WHERE g.id=? AND g.status IN ('proposed','accepted') AND x.status='current'"""
    entry = db.execute(query,(entry_id,)).fetchone()
    if entry is None:
        raise ValueError('index entry is not current or proposed')
    result = judge(provider,{'title':entry['title'],'text':entry['body'][:4000],'text_truncated':len(entry['body'])>4000,'topic':topic},'topic supported')
    with db:
        current = db.execute(query,(entry_id,)).fetchone()
        if current is None or current['title'] != entry['title'] or current['body'] != entry['body'] or current['section_id'] != entry['section_id']:
            result = dict(result,outcome='unknown',reason='index entry or source changed during decision')
        else:
            status = 'rejected' if result['outcome'] == 'unsuitable' else 'proposed'
            db.execute('INSERT INTO topic_links(section_id,generated_index_id,topic,method,status) VALUES (?,?,?,?,?)',(entry['section_id'],entry_id,topic,'decision',status))
        db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(result.get('provider','unknown'),result.get('model'),result['outcome'],json.dumps({'generated_index_id':entry_id,'topic':topic,'question':'topic supported',**decision_metadata(result)})))
    return result


def assess_role(db, section_id, role, role_version, role_purpose, provider):
    """Save a provisional usefulness estimate for a source unit or agent record."""
    if not all(isinstance(value,str) and value.strip() for value in (role,role_version,role_purpose)):
        raise ValueError('role, version and purpose are required')
    validate_retrievable_ids(db)
    section = db.execute("SELECT sections.title,sections.body,sources.revision FROM sections JOIN sources ON sources.id=sections.source_id WHERE sections.id=? AND sources.status='current'",(section_id,)).fetchone()
    target_type = 'section'
    if section is None:
        section = db.execute("SELECT generated_index.title,generated_index.body,sources.revision FROM generated_index JOIN sections ON sections.id=generated_index.section_id JOIN sources ON sources.id=sections.source_id WHERE generated_index.id=? AND generated_index.status IN ('proposed','accepted') AND sources.status='current'",(section_id,)).fetchone()
        target_type = 'generated_index'
    if section is None:
        section = db.execute("""SELECT r.kind AS title,r.body,NULL AS revision FROM records r WHERE r.id=? AND r.status IN ('proposed','current') AND NOT EXISTS
            (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""",(section_id,)).fetchone()
        target_type = 'record'
    if section is None:
        raise ValueError('target is not current or its evidence is stale')
    evidence_before = tuple(row[0] for row in db.execute('SELECT section_id FROM evidence WHERE record_id=? ORDER BY section_id',(section_id,))) if target_type == 'record' else ()
    state = {'title':section['title'],'text':section['body'][:4000],'text_truncated':len(section['body'])>4000,'role':role,'role_version':role_version,'role_purpose':role_purpose}
    result = judge(provider,state,'role usefulness')
    score = result.get('probability')
    valid = not isinstance(score,bool) and isinstance(score,(int,float)) and math.isfinite(score) and 0 <= score <= 1
    if result['outcome'] != 'unknown' and not valid:
        result = dict(result,outcome='unknown',reason='invalid role-usefulness probability',probability=None)
    with db:
        if target_type == 'generated_index':
            current = db.execute("SELECT 1 FROM generated_index JOIN sections ON sections.id=generated_index.section_id JOIN sources ON sources.id=sections.source_id WHERE generated_index.id=? AND generated_index.status IN ('proposed','accepted') AND sources.status='current' AND sources.revision=?",(section_id,section['revision'])).fetchone()
        elif target_type == 'section':
            current = db.execute("SELECT 1 FROM sections JOIN sources ON sources.id=sections.source_id WHERE sections.id=? AND sources.status='current' AND sources.revision=?",(section_id,section['revision'])).fetchone()
        else:
            current = db.execute("""SELECT 1 FROM records r WHERE r.id=? AND r.body=? AND r.status IN ('proposed','current') AND NOT EXISTS
                (SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id JOIN sources x ON x.id=s.source_id WHERE e.record_id=r.id AND x.status != 'current')""",(section_id,section['body'])).fetchone()
            evidence_after = tuple(row[0] for row in db.execute('SELECT section_id FROM evidence WHERE record_id=? ORDER BY section_id',(section_id,)))
            if evidence_before != evidence_after:
                current = None
        if current is None:
            result = dict(result,outcome='unknown',reason='source changed during decision')
        detail = {('generated_index_id' if target_type == 'generated_index' else 'record_id' if target_type == 'record' else 'section_id'):section_id,'source_revision':section['revision'],'question':'role usefulness','role':role,'role_version':role_version,'role_purpose':role_purpose,**decision_metadata(result)}
        detail['probability'] = score if valid else None
        db.execute('INSERT INTO decision_receipts(provider,model,outcome,detail) VALUES (?,?,?,?)',(result.get('provider','unknown'),result.get('model'),result['outcome'],json.dumps(detail)))
        if result['outcome'] != 'unknown' and valid:
            if target_type == 'generated_index':
                db.execute('INSERT INTO index_role_annotations(entry_id,role,role_version,score,method,model,source_revision,status) VALUES (?,?,?,?,?,?,?,?)',(section_id,role,role_version,score,'decision',result.get('model'),section['revision'],'proposed'))
            else:
                column = 'record_id' if target_type == 'record' else 'section_id'
                db.execute(f'INSERT INTO role_annotations({column},role,role_version,score,method,model,source_revision,status) VALUES (?,?,?,?,?,?,?,?)',(section_id,role,role_version,score,'decision',result.get('model'),section['revision'],'proposed'))
    return result
