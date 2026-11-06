from quix_knowledge.store import open_catalog
from quix_knowledge.ingest import ingest

def test_revision_and_anchors(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'a.md'
    path.write_text('# First\nalpha\n## Second\nbeta\n')
    first = ingest(db, path)
    rows = db.execute('SELECT title,start_line,generated FROM sections WHERE source_id=? ORDER BY start_line',(first,)).fetchall()
    assert [tuple(r) for r in rows] == [('First',1,0),('Second',3,0)]
    path.write_text('no heading\n')
    second = ingest(db, path)
    assert first != second
    assert db.execute('SELECT status FROM sources WHERE id=?',(first,)).fetchone()[0] == 'superseded'
    assert db.execute('SELECT generated FROM sections WHERE source_id=?',(second,)).fetchone()[0] == 1
    path.write_text('# First\nalpha\n## Second\nbeta\n')
    assert ingest(db,path) == first
    assert db.execute('SELECT status FROM sources WHERE id=?',(first,)).fetchone()[0] == 'current'
    assert db.execute('SELECT status FROM sources WHERE id=?',(second,)).fetchone()[0] == 'superseded'

def test_empty_file_records_failure(tmp_path):
    db = open_catalog(':memory:')
    path = tmp_path / 'empty'
    path.write_text('')
    assert ingest(db,path) is None
    assert db.execute('SELECT reason FROM ingestion_failures').fetchone()[0] == 'empty text'

def test_failed_reingestion_does_not_leave_old_source_current(tmp_path):
    from quix_knowledge.retrieve import search
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    old=ingest(db,path)
    path.write_text('')
    assert ingest(db,path) is None
    assert db.execute('SELECT status FROM sources WHERE id=?',(old,)).fetchone()[0] == 'invalidated'
    assert search(db,'retry') == []
