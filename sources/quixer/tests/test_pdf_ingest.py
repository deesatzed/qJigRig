import pytest

fitz = pytest.importorskip('fitz')
from quix_knowledge.pdf import ingest_pdf
from quix_knowledge.retrieve import search
from quix_knowledge.store import open_catalog


def make_pdf(path, toc):
    document = fitz.open()
    for text in ('First page describes retry.', 'Second page describes backoff.'):
        page = document.new_page()
        page.insert_text((72,72),text)
    if toc:
        document.set_toc([[1,'Retry',1],[1,'Backoff',2]])
    document.save(path)
    document.close()


@pytest.mark.parametrize('with_toc', [False,True])
def test_pdf_pages_searchable_with_and_without_bookmarks(tmp_path, with_toc):
    path = tmp_path/'document.pdf'
    make_pdf(path,with_toc)
    db = open_catalog(':memory:')
    source = ingest_pdf(db,path)
    assert source
    rows = search(db,'backoff')
    assert rows[0]['page_start'] == 2
    assert rows[0]['page_end'] == 2
    assert bool(rows[0]['generated']) is (not with_toc)
    assert 'backoff' in rows[0]['body'].lower()


def test_invalid_pdf_is_explicit_failure(tmp_path):
    db = open_catalog(':memory:')
    path=tmp_path/'broken.pdf'
    path.write_bytes(b'not a pdf')
    assert ingest_pdf(db,path) is None
    assert db.execute('SELECT count(*) FROM ingestion_failures').fetchone()[0] == 1

def test_blank_extracted_pages_are_reported(tmp_path):
    path = tmp_path/'partial.pdf'
    document = fitz.open()
    document.new_page().insert_text((72,72),'Some searchable text.')
    document.new_page()
    document.save(path)
    document.close()
    db = open_catalog(':memory:')
    source = ingest_pdf(db,path)
    assert source
    warning = db.execute('SELECT page,reason FROM extraction_warnings WHERE source_id=?',(source,)).fetchone()
    assert warning['page'] == 2
    assert 'no extractable text' in warning['reason']
    assert search(db,'searchable')[0]['source_warning_pages'] == [2]

def test_general_ingest_dispatches_pdf(tmp_path):
    from quix_knowledge.ingest import ingest
    path=tmp_path/'document.pdf'
    make_pdf(path, False)
    db=open_catalog(':memory:')
    source=ingest(db,path)
    assert source is not None
    assert search(db,'backoff')[0]['page_start'] == 2

def test_failed_pdf_refresh_invalidates_previous_revision(tmp_path):
    path=tmp_path/'document.pdf'
    make_pdf(path,False)
    db=open_catalog(':memory:')
    source=ingest_pdf(db,path)
    path.write_bytes(b'broken')
    assert ingest_pdf(db,path) is None
    assert db.execute('SELECT status FROM sources WHERE id=?',(source,)).fetchone()[0] == 'invalidated'
    assert search(db,'backoff') == []
