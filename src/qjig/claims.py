"""Attributed agent interpretations kept separate from source revisions and indexes."""
from __future__ import annotations

import hashlib
import json

from .contracts import ContractError
from .spans import make_span
from .store import Catalog


def _canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _checked(catalog: Catalog, value: object) -> tuple[str, dict]:
    if not isinstance(value, dict) or set(value) != {'role_id', 'role_version', 'text', 'evidence'}:
        raise ContractError('invalid interpretation fields')
    if any(not isinstance(value[k], str) or not value[k].strip() for k in ('role_id', 'role_version', 'text')):
        raise ContractError('interpretation attribution and text are required')
    evidence = value['evidence']
    if not isinstance(evidence, dict) or set(evidence) != {'revision_id', 'text_sha256', 'start', 'end'}:
        raise ContractError('invalid evidence reference')
    revision = catalog.get_revision(evidence['revision_id'])
    span = make_span(revision, evidence['start'], evidence['end'])
    if span.text_sha256 != evidence['text_sha256']:
        raise ContractError('evidence text hash mismatch')
    payload = _canonical(value)
    ident = 'claim1:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()
    return ident, {'claim_id': ident, 'kind': 'agent_interpretation', 'role_id': value['role_id'],
                   'role_version': value['role_version'], 'text': value['text'],
                   'evidence': {**evidence, 'text': span.text}}


def add_interpretation(catalog: Catalog, value: object) -> tuple[dict, bool]:
    ident, result = _checked(catalog, value)
    created = catalog.put_interpretation(ident, _canonical(value))
    return result, created


def list_interpretations(catalog: Catalog) -> list[dict]:
    result = []
    for ident, payload in catalog.interpretation_rows():
        try:
            value = json.loads(payload)
            checked_id, claim = _checked(catalog, value)
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError('stored interpretation invalid') from exc
        if checked_id != ident or _canonical(value) != payload:
            raise ContractError('stored interpretation identity mismatch')
        result.append(claim)
    return result
