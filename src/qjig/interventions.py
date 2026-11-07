"""Explicit derived source edits with immutable parent and child links."""
from __future__ import annotations

import hashlib
import json

from .contracts import ContractError
from .indexing import index_entries
from .sources import SourceRevision, decode_source
from .spans import make_span
from .store import Catalog


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _prepare(catalog: Catalog, value: object) -> tuple[str, SourceRevision, dict]:
    fields = {'parent_revision_id', 'text_sha256', 'start', 'end', 'replacement', 'role_id', 'role_version'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError('invalid intervention fields')
    if any(not isinstance(value[k], str) or not value[k].strip() for k in ('parent_revision_id', 'text_sha256', 'role_id', 'role_version')) or not isinstance(value['replacement'], str):
        raise ContractError('invalid intervention content')
    parent = catalog.get_revision(value['parent_revision_id'])
    original = make_span(parent, value['start'], value['end'])
    if original.text_sha256 != value['text_sha256']:
        raise ContractError('parent source hash mismatch')
    text = parent.decoded.text[:original.start] + value['replacement'] + parent.decoded.text[original.end:]
    if text == parent.decoded.text or not text.strip():
        raise ContractError('intervention must change the source')
    raw = text.encode('utf-8')
    if len(raw) > 1_000_000:
        raise ContractError('intervention source is too large')
    child = SourceRevision.create(parent.source_id, f'api:{parent.source_id}', decode_source(raw, encoding='utf-8'))
    payload = _canonical(value)
    ident = 'intervention1:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()
    result = {'intervention_id': ident, 'kind': 'source_intervention', 'source_id': parent.source_id,
              'parent_revision_id': parent.revision_id, 'child_revision_id': child.revision_id,
              'role_id': value['role_id'], 'role_version': value['role_version'],
              'start': original.start, 'end': original.end, 'original_text': original.text,
              'replacement': value['replacement'], 'parent_text_sha256': original.text_sha256}
    return payload, child, result


def apply_intervention(catalog: Catalog, value: object) -> tuple[dict, bool]:
    payload, child, result = _prepare(catalog, value)
    parent = result['parent_revision_id']
    metadata = next((row for row in catalog.metadata_rows() if row[0] == parent), None)
    if metadata is None:
        raise ContractError('parent metadata unavailable')
    link = (result['intervention_id'], parent, child.revision_id, payload)
    created = catalog.import_snapshot(child, index_entries(child), (child.revision_id, *metadata[1:]), parent_link=link)
    return result, created


def list_interventions(catalog: Catalog) -> list[dict]:
    results = []
    for ident, parent, child, payload in catalog.intervention_rows():
        try:
            value = json.loads(payload)
            checked_payload, expected_child, result = _prepare(catalog, value)
            actual = catalog.get_revision(child)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError('stored intervention invalid') from exc
        if (checked_payload != payload or ident != result['intervention_id'] or parent != result['parent_revision_id']
                or child != expected_child.revision_id or actual.revision_id != child):
            raise ContractError('stored intervention binding mismatch')
        results.append(result)
    return results
