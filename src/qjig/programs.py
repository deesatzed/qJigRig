"""Content-bound, non-activating AI review records.

These records preserve attributed assertions; they do not prove source authority,
reviewer identity, model execution, semantic completeness, or permission to decide.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from .contracts import ContractError, Request
from .applicability import ApplicabilityInputs
from .plans import parse_plan

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_REV = re.compile(r'rev1:[0-9a-f]{64}\Z')


def _copy(value):
    try:
        return json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractError('review data must be finite JSON') from exc


def _actor(value):
    if not isinstance(value, dict) or set(value) != {'provider', 'model', 'prompt_sha256', 'config'}:
        raise ContractError('invalid model provenance')
    if (any(not isinstance(value[k], str) or not value[k].strip() for k in ('provider', 'model'))
            or not isinstance(value['prompt_sha256'], str) or not _SHA.fullmatch(value['prompt_sha256'])
            or not isinstance(value['config'], dict)):
        raise ContractError('invalid model provenance')
    return _copy(value)


def _reviewer(value):
    if not isinstance(value, dict) or set(value) != {'kind', 'provider', 'model', 'prompt_sha256', 'config'} or value['kind'] not in ('ai', 'synthetic'):
        raise ContractError('invalid reviewer provenance')
    actor = _actor({k: v for k, v in value.items() if k != 'kind'})
    return {'kind': value['kind'], **actor}


def _binding(value):
    keys = {'request', 'plan', 'corpus_revision_ids', 'source_metadata', 'as_of', 'entities', 'historical_as_known', 'planner'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ContractError('invalid review binding')
    value = _copy(value)
    request = Request.from_dict(value['request'])
    if any(not getattr(request, name).strip() for name in request._FIELDS):
        raise ContractError('empty request field')
    parse_plan(value['plan'])
    revisions = value['corpus_revision_ids']
    if (not isinstance(revisions, list) or not revisions or
            any(not isinstance(v, str) or not _REV.fullmatch(v) for v in revisions) or len(set(revisions)) != len(revisions)):
        raise ContractError('invalid corpus revisions')
    value['corpus_revision_ids'] = sorted(revisions)
    metadata = value['source_metadata']
    metadata_keys = {'scope', 'authority_id', 'entity_keys', 'effective_start', 'effective_end', 'observed_at'}
    if (not isinstance(metadata, dict) or set(metadata) != set(revisions)
            or any(not isinstance(v, dict) or set(v) != metadata_keys for v in metadata.values())):
        raise ContractError('source metadata must cover every revision')
    entities = value['entities']
    if (not isinstance(entities, list) or any(not isinstance(v, str) or not v.strip() for v in entities)
            or len(set(entities)) != len(entities) or type(value['historical_as_known']) is not bool):
        raise ContractError('invalid applicability inputs')
    value['entities'] = sorted(entities)
    try:
        if not isinstance(value['as_of'], str) or date.fromisoformat(value['as_of']).isoformat() != value['as_of']:
            raise ValueError
    except ValueError as exc:
        raise ContractError('invalid as-of date') from exc
    members = [{'revision_id': revision, **metadata[revision]} for revision in value['corpus_revision_ids']]
    inputs = ApplicabilityInputs.from_dict({'as_of': value['as_of'], 'historical_as_known': value['historical_as_known'],
                                             'request_entities': value['entities'], 'scope_authority_assurance': 'recorded_not_assessed',
                                             'members': members})
    value['source_metadata'] = {row['revision_id']: {k: v for k, v in row.items() if k != 'revision_id'}
                                for row in inputs.to_dict()['members']}
    value['planner'] = _actor(value['planner'])
    return value


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def make_review(binding: dict, reviewer: dict, result: dict) -> dict:
    if not isinstance(result, dict) or not result:
        raise ContractError('review result is required')
    reviewer = _reviewer(reviewer)
    payload = {'schema': 'qjig.ai-review.v1',
               'assurance': 'ai_reviewed_unvalidated' if reviewer['kind'] == 'ai' else 'synthetic_review_unvalidated',
               'binding': _binding(binding), 'reviewer': reviewer, 'result': _copy(result)}
    return {'payload': payload, 'sha256': _digest(payload)}


def verify_review(record: dict, binding: dict, reviewer: dict) -> dict:
    """Check exact recorded inputs; matching review is never a decision or activation."""
    try:
        if not isinstance(record, dict) or set(record) != {'payload', 'sha256'}:
            raise ContractError('invalid review record')
        payload = record['payload']
        if not isinstance(payload, dict) or set(payload) != {'schema', 'assurance', 'binding', 'reviewer', 'result'}:
            raise ContractError('invalid review payload')
        reconstructed = make_review(payload['binding'], payload['reviewer'], payload['result'])
        if reconstructed != record:
            raise ContractError('review record digest or content differs')
    except (ContractError, TypeError, KeyError, ValueError, AttributeError):
        return {'status': 'invalid', 'activation': False, 'semantic_assurance': 'not_assessed'}
    try:
        matches = _binding(binding) == payload['binding'] and _reviewer(reviewer) == payload['reviewer']
    except (ContractError, TypeError, KeyError, ValueError, AttributeError):
        return {'status': 'invalid_candidate', 'activation': False, 'semantic_assurance': 'not_assessed'}
    return {'status': 'matching_unvalidated' if matches else 'stale', 'activation': False,
            'semantic_assurance': 'not_assessed'}
