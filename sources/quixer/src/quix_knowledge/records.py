"""Create evidence-linked records and provisional annotations."""
def add_record(db, id, kind, body, producer, evidence=(), output_ref=None, supersedes=None):
    if not all(isinstance(value,str) and value.strip() for value in (id,body,producer)):
        raise ValueError('record ID, body and producer must be nonempty')
    if kind not in ('finding','decision','test_result'):
        raise ValueError('invalid record kind')
    if kind == 'test_result' and (not isinstance(output_ref,str) or not output_ref.strip()):
        raise ValueError('test results require an output reference')
    with db:
        if db.execute('SELECT 1 FROM sections WHERE id=? UNION ALL SELECT 1 FROM generated_index WHERE id=?',(id,id)).fetchone():
            raise ValueError('ambiguous catalog ID across record types')
        db.execute('INSERT INTO records(id,kind,body,producer,supersedes,output_ref) VALUES (?,?,?,?,?,?)',(id,kind,body,producer,supersedes,output_ref))
        db.executemany('INSERT INTO evidence VALUES (?,?)',[(id,section) for section in evidence])

def review_record(db, record_id, decision, reviewer):
    """Review a proposal; replacement takes effect only on acceptance."""
    if decision not in ('accepted','rejected') or not isinstance(reviewer,str) or not reviewer.strip():
        raise ValueError('accepted/rejected and a named reviewer are required')
    with db:
        record = db.execute("SELECT id,supersedes FROM records WHERE id=? AND status='proposed'",(record_id,)).fetchone()
        if record is None:
            raise ValueError('record is not a proposal')
        if decision == 'accepted':
            stale = db.execute("""SELECT 1 FROM evidence e JOIN sections s ON s.id=e.section_id
                JOIN sources x ON x.id=s.source_id WHERE e.record_id=? AND x.status != 'current' LIMIT 1""",(record_id,)).fetchone()
            if stale:
                raise ValueError('record evidence is stale')
            if record['supersedes']:
                updated = db.execute("UPDATE records SET status='superseded' WHERE id=? AND status='current'",(record['supersedes'],))
                if updated.rowcount != 1:
                    raise ValueError('replacement target is not current')
                db.execute("UPDATE topic_links SET status='stale' WHERE record_id=?",(record['supersedes'],))
                db.execute("UPDATE role_annotations SET status='stale' WHERE record_id=?",(record['supersedes'],))
            db.execute("UPDATE records SET status='current' WHERE id=?",(record_id,))
        else:
            db.execute("UPDATE records SET status='invalidated' WHERE id=?",(record_id,))
            db.execute("UPDATE topic_links SET status='stale' WHERE record_id=?",(record_id,))
            db.execute("UPDATE role_annotations SET status='stale' WHERE record_id=?",(record_id,))
        db.execute('INSERT INTO record_reviews(record_id,reviewer,decision) VALUES (?,?,?)',(record_id,reviewer.strip(),decision))

def add_topic(db, section_id, topic, method, status='proposed'):
    with db:
        db.execute('INSERT INTO topic_links(section_id,topic,method,status) VALUES (?,?,?,?)',(section_id,topic,method,status))

def add_role(db, section_id, role, role_version, score, method, source_revision, model=None):
    with db:
        db.execute('INSERT INTO role_annotations(section_id,role,role_version,score,method,source_revision,model) VALUES (?,?,?,?,?,?,?)',(section_id,role,role_version,score,method,source_revision,model))

def review_topic(db, link_id, decision, reviewer):
    """Record a named review of a current topic proposal."""
    if decision not in ('accepted','rejected') or not isinstance(reviewer,str) or not reviewer.strip():
        raise ValueError('accepted/rejected and a named reviewer are required')
    with db:
        current = db.execute("""SELECT t.id FROM topic_links t
            LEFT JOIN sections s ON s.id=t.section_id
            LEFT JOIN sources src ON src.id=s.source_id
            LEFT JOIN records r ON r.id=t.record_id
            WHERE t.id=? AND t.status='proposed' AND
              ((t.section_id IS NOT NULL AND src.status='current' AND
                (t.generated_index_id IS NULL OR EXISTS (SELECT 1 FROM generated_index g WHERE g.id=t.generated_index_id AND g.section_id=t.section_id AND g.status IN ('proposed','accepted')))) OR
               (t.record_id IS NOT NULL AND r.status IN ('proposed','current') AND NOT EXISTS
                 (SELECT 1 FROM evidence e JOIN sections es ON es.id=e.section_id JOIN sources x ON x.id=es.source_id WHERE e.record_id=r.id AND x.status != 'current')))""",(link_id,)).fetchone()
        if current is None:
            raise ValueError('topic link is not a current proposal')
        db.execute('UPDATE topic_links SET status=? WHERE id=?',(decision,link_id))
        db.execute('INSERT INTO topic_link_reviews(link_id,reviewer,decision) VALUES (?,?,?)',(link_id,reviewer.strip(),decision))
