"""Portable authored-run evidence bundle; structural checks do not prove outcomes."""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .contracts import ContractError, Request
from .indexing import index_entries
from .plans import parse_plan
from .sources import SourceRevision, decode_source
from .spans import Span, verify_span
from .store import Catalog, CatalogStateChanged


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def export_authored(catalog: Catalog, result: dict, policy: dict, source_state: str) -> dict:
    """Capture cited raw source bytes while the supplied catalog state is unchanged."""
    if not isinstance(result, dict) or not isinstance(policy, dict) or not isinstance(source_state, str):
        raise ContractError('authored result, policy and source state are required')
    if catalog.source_state() != source_state:
        raise CatalogStateChanged('catalog changed before export')
    try:
        revision_ids = {e['revision_id'] for record in result['records'] for e in record['evidence']}
        sources = {}
        for ident in sorted(revision_ids):
            revision = catalog.get_revision(ident)
            sources[ident] = {'source_id': revision.source_id, 'encoding': revision.decoded.encoding,
                              'raw_base64': base64.b64encode(revision.decoded.raw).decode('ascii')}
        payload = {'schema': 'qjig.authored-export.v1', 'source_state': source_state, 'policy': policy,
                   'result': result, 'sources': sources,
                   'resources': {'provider_calls_reported': result['providers_called'], 'cost_usd': None,
                                 'cost_status': 'not_reported'}}
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError('invalid authored result') from exc
    if catalog.source_state() != source_state:
        raise CatalogStateChanged('catalog changed during export')
    bundle = {'payload': payload, 'sha256': digest}
    if verify_authored_export(bundle)['status'] != 'unanchored':
        raise ContractError('authored result failed structural verification')
    return bundle


def verify_authored_export(bundle: object, *, expected_digest: str | None = None) -> dict:
    """Check recorded evidence without inference; an external digest is not authentication."""
    try:
        if not isinstance(bundle, dict) or set(bundle) != {'payload', 'sha256'}:
            raise ContractError('invalid export envelope')
        payload, recorded = bundle['payload'], bundle['sha256']
        if not isinstance(payload, dict) or set(payload) != {'schema', 'source_state', 'policy', 'result', 'sources', 'resources'}:
            raise ContractError('invalid export payload')
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        if recorded != digest or (expected_digest is not None and expected_digest != digest):
            raise ContractError('export digest mismatch')
        if payload['schema'] != 'qjig.authored-export.v1' or not isinstance(payload['source_state'], str) or not re.fullmatch(r'[0-9a-f]{64}', payload['source_state']):
            raise ContractError('invalid export schema or catalog state')
        result, policy, sources = payload['result'], payload['policy'], payload['sources']
        if not isinstance(result, dict) or not isinstance(policy, dict) or not isinstance(sources, dict):
            raise ContractError('invalid export contents')
        Request.from_dict(result['request'])
        plan = parse_plan(policy['plan'])
        if plan.origin != 'authored' or result['plan_origin'] != plan.origin or result['providers_called'] != 0 or type(result['providers_called']) is not int:
            raise ContractError('invalid authored origin or resource declaration')
        if payload['resources'] != {'provider_calls_reported': 0, 'cost_usd': None, 'cost_status': 'not_reported'}:
            raise ContractError('invalid resource record')
        if result['status'] not in ('decided', 'deferred') or (result['status'] == 'decided' and type(result['outcome']) is not bool) or (result['status'] == 'deferred' and result['outcome'] is not None):
            raise ContractError('invalid result status')
        revisions, entries = {}, {}
        for ident, source in sources.items():
            if not isinstance(source, dict) or set(source) != {'source_id', 'encoding', 'raw_base64'}:
                raise ContractError('invalid exported source')
            raw = base64.b64decode(source['raw_base64'], validate=True)
            revision = SourceRevision.create(source['source_id'], 'export', decode_source(raw, encoding=source['encoding']))
            if revision.revision_id != ident:
                raise ContractError('source identity mismatch')
            revisions[ident] = revision
            entries[ident] = {entry.entry_id: entry for entry in index_entries(revision)}
        used = set()
        for seq, record in enumerate(result['records'], 1):
            if type(record['sequence']) is not int or record['sequence'] != seq or record['predicate_id'] not in {p.id for p in plan.predicates}:
                raise ContractError('invalid trace sequence or predicate')
            for evidence in record['evidence']:
                ident = evidence['revision_id']
                revision = revisions[ident]
                entry = entries[ident][evidence['entry_id']]
                span = Span(ident, evidence['text_sha256'], evidence['start'], evidence['end'], evidence['text'])
                verify_span(revision, span)
                if (evidence['source_id'] != revision.source_id or span.start != entry.span.start or
                    span.end > entry.span.end or type(evidence['truncated']) is not bool or
                    (not evidence['truncated'] and span.end != entry.span.end)):
                    raise ContractError('evidence entry binding mismatch')
                used.add(ident)
        if used != set(revisions):
            raise ContractError('source set mismatch')
    except (ContractError, KeyError, TypeError, ValueError, UnicodeError, OverflowError, AttributeError):
        return {'status': 'invalid', 'sha256': None, 'semantic_assurance': 'not_assessed'}
    return {'status': 'structurally_verified' if expected_digest is not None else 'unanchored',
            'sha256': digest, 'semantic_assurance': 'not_assessed'}
