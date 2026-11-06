"""Ingest UTF-8 text with line-level structural anchors."""
import hashlib
from pathlib import Path
import re

def supersede_path(db, path):
    """Invalidate derived annotations for the current revision within caller transaction."""
    affected = "SELECT evidence.record_id FROM evidence JOIN sections ON sections.id=evidence.section_id JOIN sources ON sources.id=sections.source_id WHERE sources.path=? AND sources.status='current'"
    db.execute(f"UPDATE topic_links SET status='stale' WHERE record_id IN ({affected})", (path,))
    db.execute(f"UPDATE role_annotations SET status='stale' WHERE record_id IN ({affected})", (path,))
    db.execute("UPDATE index_role_annotations SET status='stale' WHERE entry_id IN (SELECT generated_index.id FROM generated_index JOIN sections ON generated_index.section_id=sections.id JOIN sources ON sections.source_id=sources.id WHERE sources.path=? AND sources.status='current')",(path,))
    db.execute("UPDATE generated_index SET status='stale' WHERE section_id IN (SELECT sections.id FROM sections JOIN sources ON sources.id=sections.source_id WHERE sources.path=? AND sources.status='current')",(path,))
    db.execute("UPDATE topic_links SET status='stale' WHERE section_id IN (SELECT sections.id FROM sections JOIN sources ON sources.id=sections.source_id WHERE sources.path=? AND sources.status='current')",(path,))
    db.execute("UPDATE role_annotations SET status='stale' WHERE section_id IN (SELECT sections.id FROM sections JOIN sources ON sources.id=sections.source_id WHERE sources.path=? AND sources.status='current')",(path,))
    db.execute("UPDATE sources SET status='superseded' WHERE path=? AND status='current'",(path,))

def record_ingestion_failure(db, path, reason):
    """Retain old data, but never present it as current after a failed refresh."""
    with db:
        current = [row['id'] for row in db.execute("SELECT id FROM sources WHERE path=? AND status='current'",(path,))]
        supersede_path(db,path)
        db.executemany("UPDATE sources SET status='invalidated' WHERE id=?",[(source_id,) for source_id in current])
        db.execute('INSERT INTO ingestion_failures VALUES (?,?)',(path,reason))

def ingest(db, path):
    path = Path(path).resolve()
    if path.suffix.lower() == '.pdf':
        from .pdf import ingest_pdf
        return ingest_pdf(db,path)
    try:
        body = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        record_ingestion_failure(db,str(path),str(exc))
        return None
    if not body.strip():
        record_ingestion_failure(db,str(path),'empty text')
        return None
    revision = hashlib.sha256(body.encode()).hexdigest()
    source_id = hashlib.sha256((str(path)+'\0'+revision).encode()).hexdigest()
    existing = db.execute('SELECT status FROM sources WHERE id=?',(source_id,)).fetchone()
    if existing and existing[0] == 'current':
        return source_id
    lines = body.splitlines()
    headings = [(i, m.group(1)) for i,line in enumerate(lines) if (m := re.match(r'^#{1,6}\s+(.+?)\s*#*\s*$',line))]
    if not headings or headings[0][0] > 0:
        headings.insert(0,(0,'Unstructured text'))
    with db:
        supersede_path(db, str(path))
        if existing:
            db.execute("UPDATE sources SET status='current' WHERE id=?",(source_id,))
            return source_id
        db.execute('INSERT INTO sources(id,path,revision,body) VALUES (?,?,?,?)',(source_id,str(path),revision,body))
        for n,(start,title) in enumerate(headings):
            end = headings[n+1][0] if n+1 < len(headings) else len(lines)
            sid = hashlib.sha256(f'{source_id}:{start}:{end}'.encode()).hexdigest()
            generated = int(title == 'Unstructured text' and not re.match(r'^#{1,6}\s+',lines[start]))
            db.execute('INSERT INTO sections VALUES (?,?,?,?,?,?,?)',(sid,source_id,title,'\n'.join(lines[start:end]),start+1,end,generated))
    return source_id
