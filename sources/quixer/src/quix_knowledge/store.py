"""Single-writer SQLite catalog."""
import sqlite3
import hashlib
import json

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,path TEXT NOT NULL,revision TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'current' CHECK(status IN ('current','superseded','invalidated')), UNIQUE(path,revision));
CREATE TABLE IF NOT EXISTS sections(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),title TEXT NOT NULL,body TEXT NOT NULL,start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,generated INTEGER NOT NULL CHECK(generated IN (0,1)));
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT NOT NULL CHECK(kind IN ('finding','decision','test_result')),body TEXT NOT NULL,producer TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','current','superseded','invalidated')),supersedes TEXT REFERENCES records(id),output_ref TEXT);
CREATE TABLE IF NOT EXISTS record_reviews(id INTEGER PRIMARY KEY,record_id TEXT NOT NULL REFERENCES records(id),reviewer TEXT NOT NULL,decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS evidence(record_id TEXT NOT NULL REFERENCES records(id),section_id TEXT NOT NULL REFERENCES sections(id),PRIMARY KEY(record_id,section_id));
CREATE TABLE IF NOT EXISTS topic_links(id INTEGER PRIMARY KEY,section_id TEXT REFERENCES sections(id),record_id TEXT REFERENCES records(id),topic TEXT NOT NULL,method TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected','stale')),generated_index_id TEXT REFERENCES generated_index(id),CHECK((section_id IS NULL) != (record_id IS NULL)));
CREATE TABLE IF NOT EXISTS topic_link_reviews(id INTEGER PRIMARY KEY,link_id INTEGER NOT NULL REFERENCES topic_links(id),reviewer TEXT NOT NULL,decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS role_annotations(id INTEGER PRIMARY KEY,section_id TEXT REFERENCES sections(id),record_id TEXT REFERENCES records(id),role TEXT NOT NULL,role_version TEXT NOT NULL,score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),method TEXT NOT NULL,model TEXT,source_revision TEXT,status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','accepted','stale')),CHECK((section_id IS NULL) != (record_id IS NULL)));
CREATE TABLE IF NOT EXISTS decision_receipts(id INTEGER PRIMARY KEY,provider TEXT NOT NULL,model TEXT,outcome TEXT NOT NULL,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingestion_failures(path TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS section_pages(section_id TEXT PRIMARY KEY REFERENCES sections(id),page_start INTEGER NOT NULL CHECK(page_start >= 1),page_end INTEGER NOT NULL CHECK(page_end >= page_start));
CREATE TABLE IF NOT EXISTS extraction_warnings(source_id TEXT NOT NULL REFERENCES sources(id),page INTEGER NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(source_id,page));
CREATE TABLE IF NOT EXISTS generated_index(id TEXT PRIMARY KEY,section_id TEXT NOT NULL REFERENCES sections(id),title TEXT NOT NULL,body TEXT NOT NULL,start_offset INTEGER NOT NULL CHECK(start_offset >= 0),end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected','stale')),method TEXT NOT NULL,UNIQUE(section_id,start_offset,end_offset,method));
CREATE TABLE IF NOT EXISTS generated_index_reviews(id INTEGER PRIMARY KEY,entry_id TEXT NOT NULL REFERENCES generated_index(id),reviewer TEXT NOT NULL,decision TEXT NOT NULL CHECK(decision IN ('accepted','rejected')),reviewed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE IF NOT EXISTS index_role_annotations(id INTEGER PRIMARY KEY,entry_id TEXT NOT NULL REFERENCES generated_index(id),role TEXT NOT NULL,role_version TEXT NOT NULL,score REAL NOT NULL CHECK(score BETWEEN 0 AND 1),method TEXT NOT NULL,model TEXT,source_revision TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('proposed','accepted','stale')),created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
"""

def open_catalog(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version not in (0, 1, 2, 3, 4, 5, 6, 7):
        db.close()
        raise ValueError(f'Unsupported schema version: {version}')
    db.executescript(SCHEMA)
    if 'generated_index_id' not in {row['name'] for row in db.execute('PRAGMA table_info(topic_links)')}:
        db.execute('ALTER TABLE topic_links ADD COLUMN generated_index_id TEXT REFERENCES generated_index(id)')
    db.executescript("""CREATE TRIGGER IF NOT EXISTS topic_entry_parent_insert BEFORE INSERT ON topic_links
        WHEN NEW.generated_index_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM generated_index WHERE id=NEW.generated_index_id AND section_id=NEW.section_id AND NEW.record_id IS NULL)
        BEGIN SELECT RAISE(ABORT,'generated topic parent mismatch'); END;
        CREATE TRIGGER IF NOT EXISTS topic_entry_parent_update BEFORE UPDATE ON topic_links
        WHEN NEW.generated_index_id IS NOT NULL AND NOT EXISTS
          (SELECT 1 FROM generated_index WHERE id=NEW.generated_index_id AND section_id=NEW.section_id AND NEW.record_id IS NULL)
        BEGIN SELECT RAISE(ABORT,'generated topic parent mismatch'); END;""")
    db.execute('PRAGMA user_version=7')
    db.commit()
    return db

def validate_retrievable_ids(db):
    """Reject cross-type identity collisions before resolving or comparing results."""
    collision = db.execute("""SELECT id FROM (
        SELECT id FROM sections UNION ALL SELECT id FROM generated_index UNION ALL SELECT id FROM records
    ) GROUP BY id HAVING count(*) > 1 LIMIT 1""").fetchone()
    if collision is not None:
        raise ValueError('ambiguous catalog ID across record types')

def corpus_fingerprint(db):
    """Hash catalog records and annotations, excluding mutable decision receipts."""
    tables = ('sources','sections','section_pages','extraction_warnings','generated_index','generated_index_reviews','index_role_annotations','records','evidence','topic_links','topic_link_reviews','role_annotations')
    digest = hashlib.sha256()
    for name in tables:
        rows = [dict(row) for row in db.execute(f'SELECT * FROM {name}').fetchall()]
        if name == 'topic_links':
            for row in rows:
                if row.get('generated_index_id') is None:
                    row.pop('generated_index_id',None)
        encoded = sorted(json.dumps(row,sort_keys=True,ensure_ascii=False) for row in rows)
        digest.update(json.dumps([name,encoded],ensure_ascii=False).encode())
    reviews = [dict(row) for row in db.execute('SELECT * FROM record_reviews').fetchall()]
    if reviews:
        encoded = sorted(json.dumps(row,sort_keys=True,ensure_ascii=False) for row in reviews)
        digest.update(json.dumps(['record_reviews',encoded],ensure_ascii=False).encode())
    return digest.hexdigest()
