import hashlib
import sqlite3
import pytest
from quix_knowledge.store import open_catalog


def test_catalog_persists_and_enforces_references(tmp_path):
    path = tmp_path / 'catalog.db'
    db = open_catalog(path)
    digest = hashlib.sha256(b'hello').hexdigest()
    db.execute('INSERT INTO sources(id,path,revision,body) VALUES (?,?,?,?)', ('s1','a.md',digest,'hello'))
    db.commit()
    db.close()
    db = open_catalog(path)
    assert tuple(db.execute('SELECT path,revision FROM sources').fetchone()) == ('a.md', digest)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO sections(id,source_id,title,body,start_line,end_line,generated) VALUES ('x','missing','x','x',1,1,0)")

def test_version_one_catalog_migrates_without_losing_sources(tmp_path):
    path = tmp_path/'old.db'
    db = open_catalog(path)
    db.execute("INSERT INTO sources VALUES ('old','a.md','hash','body','current')")
    db.execute('DROP TABLE section_pages')
    db.execute('DROP TABLE extraction_warnings')
    db.execute('DROP TABLE generated_index_reviews')
    db.execute('DROP TABLE index_role_annotations')
    db.execute('DROP TABLE topic_link_reviews')
    db.execute('DROP TABLE record_reviews')
    db.execute('DROP TABLE generated_index')
    db.execute('PRAGMA user_version=1')
    db.commit()
    db.close()
    reopened = open_catalog(path)
    assert reopened.execute('PRAGMA user_version').fetchone()[0] == 7
    assert reopened.execute("SELECT body FROM sources WHERE id='old'").fetchone()[0] == 'body'
    assert reopened.execute('SELECT count(*) FROM section_pages').fetchone()[0] == 0
    assert reopened.execute('SELECT count(*) FROM generated_index').fetchone()[0] == 0

def test_empty_review_table_preserves_existing_catalog_fingerprint():
    import hashlib,json
    from quix_knowledge.store import corpus_fingerprint
    db=open_catalog(':memory:')
    tables=('sources','sections','section_pages','extraction_warnings','generated_index','generated_index_reviews','index_role_annotations','records','evidence','topic_links','topic_link_reviews','role_annotations')
    digest=hashlib.sha256()
    for name in tables:
        rows=[dict(row) for row in db.execute(f'SELECT * FROM {name}')]
        if name == 'topic_links':
            for row in rows:
                if row.get('generated_index_id') is None:
                    row.pop('generated_index_id',None)
        encoded=sorted(json.dumps(row,sort_keys=True,ensure_ascii=False) for row in rows)
        digest.update(json.dumps([name,encoded],ensure_ascii=False).encode())
    assert corpus_fingerprint(db) == digest.hexdigest()

def test_legacy_topic_table_migrates_without_losing_links(tmp_path):
    path=tmp_path/'legacy.db'
    db=sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE sources(id TEXT PRIMARY KEY,path TEXT NOT NULL,revision TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL);
        CREATE TABLE sections(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),title TEXT NOT NULL,body TEXT NOT NULL,start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,generated INTEGER NOT NULL);
        CREATE TABLE topic_links(id INTEGER PRIMARY KEY,section_id TEXT,record_id TEXT,topic TEXT NOT NULL,method TEXT NOT NULL,status TEXT NOT NULL);
        INSERT INTO sources VALUES ('s','doc','revision','body','current');
        INSERT INTO sections VALUES ('p','s','Title','body',1,1,0);
        INSERT INTO topic_links VALUES (1,'p',NULL,'retry','manual','accepted');
        PRAGMA user_version=6;
    """)
    db.close()
    reopened=open_catalog(path)
    link=reopened.execute('SELECT topic,status,generated_index_id FROM topic_links').fetchone()
    assert tuple(link) == ('retry','accepted',None)
    assert reopened.execute('PRAGMA user_version').fetchone()[0] == 7
