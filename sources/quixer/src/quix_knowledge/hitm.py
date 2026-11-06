"""Versioned, local read contract for the proposed HITMCockpit adapter."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from .context import build_context_packet
from .retrieve import search
from .store import corpus_fingerprint
from .evidence_recovery import EvidenceRejected


class SourceChanged(ValueError):
    pass


def _check_sources(db):
    for row in db.execute("SELECT path,revision FROM sources WHERE status='current'"):
        path = Path(row['path'])
        try:
            content = path.read_bytes() if path.suffix.lower() == '.pdf' else path.read_text(encoding='utf-8').encode('utf-8')
        except (OSError, UnicodeError) as exc:
            raise SourceChanged('source cannot be verified') from exc
        if hashlib.sha256(content).hexdigest() != row['revision']:
            raise SourceChanged('source changed since indexing')


def _validate_request(request):
    if not isinstance(request, dict) or type(request.get('version')) is not int or request['version'] != 1:
        raise ValueError('unsupported protocol version')
    if set(request) != {'version','task','role','role_version','limit','budget_characters'}:
        raise ValueError('request fields do not match protocol version')
    if not all(isinstance(request.get(k),str) and request[k].strip() for k in ('task','role','role_version')):
        raise ValueError('task, role and role version are required')
    if any(type(request.get(k)) is not int or request[k] < 0 for k in ('limit','budget_characters')):
        raise ValueError('nonnegative result limit and character budget are required')


def retrieve_context(db, request):
    """Return a character-budgeted packet; callers must revalidate before use."""
    _validate_request(request)
    _check_sources(db)
    fingerprint = corpus_fingerprint(db)
    rows = search(db,request['task'],variant='role',role=request['role'],role_version=request['role_version'],limit=request['limit'])
    for row in rows:
        if row['record_type'] == 'agent_record':
            row['evidence_sources'] = [dict(item) for item in db.execute('''SELECT s.id AS section_id,x.path,x.revision,x.status AS source_status,
                s.start_line,s.end_line,p.page_start,p.page_end FROM evidence e JOIN sections s ON s.id=e.section_id
                JOIN sources x ON x.id=s.source_id LEFT JOIN section_pages p ON p.section_id=s.id
                WHERE e.record_id=? ORDER BY s.id''',(row['id'],))]
    _check_sources(db)
    if corpus_fingerprint(db) != fingerprint:
        raise ValueError('catalog changed during retrieval')
    packet = build_context_packet(request['task'],request['role'],request['role_version'],rows,budget=request['budget_characters'],count_tokens=len,tokenizer_name='json-characters',catalog_fingerprint=fingerprint)
    return {'version':1,'packet':packet}


def retrieve_recovery_context(db, request):
    """Build a role-ranked, source-checked packet and bounded recovery receipt."""
    from .switch_snapshot import build_snapshot
    from .evidence_recovery import recover_evidence, verify_evidence_candidate
    _validate_request(request)
    if request['limit'] < 1: raise ValueError('result limit must be positive')
    snapshot=build_snapshot(db,task=request['task'],role=request['role'],role_version=request['role_version'],max_steps=5,max_characters=12000,matched_candidates=True,verify_all_sources=False)
    rows=search(db,request['task'],variant='role',role=request['role'],role_version=request['role_version'],limit=100,ranking='bm25',include_generated=False)
    bound={row['id']:row for row in snapshot['candidates']}
    ranked=[bound[row['id']] for row in rows if row['id'] in bound]
    recovery=recover_evidence(ranked,[],limit=request['limit'])
    if corpus_fingerprint(db)!=snapshot['catalog_fingerprint']:raise ValueError('catalog changed during retrieval')
    selected=recovery.pop('results')
    for row in selected: row['context_truncated']=row.get('body_truncated',False)
    packet=build_context_packet(request['task'],request['role'],request['role_version'],selected,budget=request['budget_characters'],count_tokens=len,tokenizer_name='json-characters',catalog_fingerprint=snapshot['catalog_fingerprint'])
    recovery['shortfall_count']+=len(selected)-len(packet['results'])
    if not packet['results']:recovery['status']='insufficient_evidence'
    for row in selected:verify_evidence_candidate(row)
    if corpus_fingerprint(db)!=snapshot['catalog_fingerprint']:raise ValueError('catalog changed during retrieval')
    return {'version':1,'packet':packet,'recovery':recovery}


def cli_context(catalog_path, recovery=False):
    """Read one bounded request and write one structured response without catalog writes."""
    def fail(code, message):
        print(json.dumps({'ok':False,'error':{'code':code,'message':message}}))
        return 1
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            return fail('invalid_request','request exceeds 65536 bytes')
        request = json.loads(raw.decode('utf-8'))
        if not isinstance(request,dict) or type(request.get('limit')) is not int or request['limit'] > 100 or type(request.get('budget_characters')) is not int or request['budget_characters'] > 100000:
            return fail('invalid_request','request exceeds bounds or lacks required fields')
        _validate_request(request)
    except (UnicodeError, ValueError):
        return fail('invalid_request','request must be valid UTF-8 JSON')
    db = None
    try:
        uri = Path(catalog_path).resolve().as_uri() + '?mode=ro'
        db = sqlite3.connect(uri,uri=True)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != 7:
            return fail('catalog_unavailable','catalog schema version is unsupported')
        result = retrieve_recovery_context(db,request) if recovery else retrieve_context(db,request)
        if recovery and result['recovery']['status']=='insufficient_evidence':
            print(json.dumps({'ok':False,'error':{'code':'insufficient_evidence','message':'no verified evidence is available'},'recovery':result['recovery']},ensure_ascii=False))
            return 1
        print(json.dumps({'ok':True,**result},ensure_ascii=False))
        return 0
    except SourceChanged:
        return fail('source_changed','a source is missing, unreadable or changed')
    except EvidenceRejected as exc:
        if str(exc) in ('source_changed','source_unavailable'):
            return fail('source_changed','a selected source changed during retrieval')
        return fail('unsupported_evidence','selected evidence failed verification')
    except ValueError as exc:
        code = 'budget_too_small' if str(exc) == 'budget is too small for packet metadata' else 'catalog_changed' if str(exc) == 'catalog changed during retrieval' else 'invalid_request'
        return fail(code,str(exc))
    except (sqlite3.Error,OSError):
        return fail('catalog_unavailable','catalog could not be read')
    finally:
        if db is not None:
            db.close()
