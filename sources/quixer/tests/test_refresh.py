from quix_knowledge.ingest import ingest
from quix_knowledge.refresh import refresh_sources
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def test_refresh_detects_change_missing_and_restoration(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_text('# Retry\nRetry is allowed.')
    first=ingest(db,path)
    assert refresh_sources(db)['unchanged'] == 1
    path.write_text('# Retry\nRetry is prohibited.')
    change=refresh_sources(db)
    assert change['updated'] == 1
    assert db.execute('SELECT status FROM sources WHERE id=?',(first,)).fetchone()[0] == 'superseded'
    assert 'prohibited' in search(db,'retry')[0]['body']
    path.unlink()
    assert refresh_sources(db)['failed'] == 1
    assert search(db,'retry') == []
    path.write_text('# Retry\nRetry is allowed.')
    assert refresh_sources(db)['updated'] == 1
    assert db.execute('SELECT status FROM sources WHERE id=?',(first,)).fetchone()[0] == 'current'


def test_refresh_handles_crlf_using_ingestion_normalization(tmp_path):
    db=open_catalog(':memory:')
    path=tmp_path/'doc.md'
    path.write_bytes(b'# Retry\r\nRetry twice.\r\n')
    ingest(db,path)
    assert refresh_sources(db)['unchanged'] == 1
