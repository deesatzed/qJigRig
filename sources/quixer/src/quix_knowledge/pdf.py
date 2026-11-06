"""PDF text ingestion with page-granularity anchors; OCR is not performed."""
import hashlib
from pathlib import Path
from .ingest import supersede_path, record_ingestion_failure


def ingest_pdf(db, path):
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError('PDF support requires the pdf extra (PyMuPDF)') from exc
    path = Path(path).resolve()
    try:
        raw = path.read_bytes()
        with fitz.open(stream=raw, filetype='pdf') as doc:
            if doc.needs_pass:
                raise ValueError('encrypted PDF requires a password')
            pages = [page.get_text() for page in doc]
            toc = doc.get_toc(simple=True)
    except (OSError, ValueError, RuntimeError) as exc:
        record_ingestion_failure(db,str(path),f'PDF extraction failed: {type(exc).__name__}')
        return None
    if not any(page.strip() for page in pages):
        record_ingestion_failure(db,str(path),'PDF has no extractable text; OCR not performed')
        return None
    revision = hashlib.sha256(raw).hexdigest()
    source_id = hashlib.sha256((str(path)+'\0'+revision).encode()).hexdigest()
    existing = db.execute('SELECT status FROM sources WHERE id=?',(source_id,)).fetchone()
    if existing and existing['status'] == 'current':
        return source_id
    grouped = {}
    for level, title, page in toc:
        if 1 <= page <= len(pages) and title.strip():
            grouped.setdefault(page, []).append(title.strip())
    if not grouped:
        starts = [(i, f'Page {i}', True) for i in range(1,len(pages)+1)]
    else:
        starts = [(page, ' / '.join(dict.fromkeys(titles)), False) for page,titles in sorted(grouped.items())]
        if starts[0][0] != 1:
            starts.insert(0,(1,'Pages before first bookmark',True))
    with db:
        supersede_path(db,str(path))
        if existing:
            db.execute("UPDATE sources SET status='current' WHERE id=?",(source_id,))
            return source_id
        db.execute('INSERT INTO sources(id,path,revision,body) VALUES (?,?,?,?)',(source_id,str(path),revision,'\n'.join(pages)))
        db.executemany('INSERT INTO extraction_warnings VALUES (?,?,?)',[(source_id,i,'no extractable text; blank or image-only page') for i,page in enumerate(pages,1) if not page.strip()])
        for i,(start,title,generated) in enumerate(starts):
            end = starts[i+1][0]-1 if i+1 < len(starts) else len(pages)
            section_id = hashlib.sha256(f'{source_id}:pages:{start}:{end}'.encode()).hexdigest()
            body = '\n'.join(pages[start-1:end])
            db.execute('INSERT INTO sections VALUES (?,?,?,?,?,?,?)',(section_id,source_id,title,body,1,max(1,len(body.splitlines())),int(generated)))
            db.execute('INSERT INTO section_pages VALUES (?,?,?)',(section_id,start,end))
    return source_id
