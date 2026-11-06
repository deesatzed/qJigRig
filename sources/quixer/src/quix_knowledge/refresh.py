"""Explicitly reconcile known source paths with the catalog."""
import hashlib
from pathlib import Path

from .ingest import ingest, record_ingestion_failure


def refresh_sources(db):
    paths = [row['path'] for row in db.execute("SELECT DISTINCT path FROM sources WHERE status IN ('current','invalidated') ORDER BY path")]
    report = {'unchanged':0,'updated':0,'failed':0,'sources':[]}
    for name in paths:
        path = Path(name)
        current = db.execute("SELECT id,revision FROM sources WHERE path=? AND status='current'",(name,)).fetchone()
        try:
            content = path.read_bytes() if path.suffix.lower() == '.pdf' else path.read_text(encoding='utf-8').encode()
            observed = hashlib.sha256(content).hexdigest()
        except (OSError,UnicodeError):
            observed = None
        if current is not None and observed == current['revision']:
            report['unchanged'] += 1
            report['sources'].append({'path':name,'status':'unchanged','source_id':current['id']})
            continue
        try:
            new_id = ingest(db,path)
        except RuntimeError as exc:
            record_ingestion_failure(db,name,f'refresh unavailable: {type(exc).__name__}')
            new_id = None
        status = 'updated' if new_id else 'failed'
        report[status] += 1
        report['sources'].append({'path':name,'status':status,'source_id':new_id,'prior_source_id':current['id'] if current else None,'needs_reindex':bool(new_id)})
    return report
