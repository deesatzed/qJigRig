"""Private case bindings for a source-isolated evaluation; no model dispatch."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date

from .contracts import ContractError
from .evaluation import EvaluationSource, _manifest, load_isolated_sources, validate_evaluation_design
from .evaluation_scoring import reference_digest
from .sources import SourceRevision, decode_source

_SHA = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class PreparedEvaluationCase:
    question: str
    role: str
    role_version: str
    scope: str
    as_of: str
    entities: tuple[str, ...]
    historical_as_known: bool
    sources: tuple[EvaluationSource, ...] = field(repr=False)


def case_lock_digest(lock: dict) -> str:
    """Hash a private case binding; this does not authenticate its author."""
    keys = {'schema', 'case_id', 'design_sha256', 'question', 'role', 'role_version', 'scope',
            'as_of', 'entities', 'historical_as_known', 'sources', 'reference_sha256'}
    if not isinstance(lock, dict) or set(lock) != keys or lock['schema'] != 'qjig.evaluation-case.v1':
        raise ContractError('invalid evaluation case binding')
    if (any(not isinstance(lock[k], str) or not lock[k].strip() for k in ('case_id', 'question', 'role', 'role_version', 'scope'))
            or any(not isinstance(lock[k], str) or not _SHA.fullmatch(lock[k]) for k in ('design_sha256', 'reference_sha256'))):
        raise ContractError('invalid evaluation case identity')
    try:
        if not isinstance(lock['as_of'], str) or date.fromisoformat(lock['as_of']).isoformat() != lock['as_of']:
            raise ValueError
    except ValueError as exc:
        raise ContractError('invalid evaluation case date') from exc
    entities = lock['entities']
    if (not isinstance(entities, list) or any(not isinstance(x, str) or not x.strip() for x in entities)
            or entities != sorted(set(entities)) or type(lock['historical_as_known']) is not bool):
        raise ContractError('invalid evaluation case context')
    _manifest(lock['sources'], 'case source')
    try:
        data = json.dumps(lock, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractError('invalid evaluation case binding') from exc
    return hashlib.sha256(data).hexdigest()


def prepare_evaluation_case(root, design: dict, lock: dict, reference: dict, protected: list[dict], *,
                            expected_design_sha256: str, expected_case_sha256: str) -> PreparedEvaluationCase:
    """Check a declared case before producing source and question inputs.

    The protected manifest and digest anchors are caller assertions; this does
    not detect transformed labels, verify authorship or establish reference truth.
    """
    if (not isinstance(expected_design_sha256, str) or not _SHA.fullmatch(expected_design_sha256)
            or not isinstance(expected_case_sha256, str) or not _SHA.fullmatch(expected_case_sha256)):
        raise ContractError('evaluation case anchors required')
    validate_evaluation_design(design, expected_digest=expected_design_sha256)
    if not hmac.compare_digest(case_lock_digest(lock), expected_case_sha256) or lock['design_sha256'] != expected_design_sha256:
        raise ContractError('evaluation case digest differs')
    cases = {case['id']: case for case in design['cases']}
    if lock['case_id'] not in cases:
        raise ContractError('case not in evaluation design')
    family = next(f for f in design['families'] if f['id'] == cases[lock['case_id']]['family'])
    if any(source['sha256'] not in family['source_hashes'] for source in lock['sources']):
        raise ContractError('case source is not in its family')
    if not hmac.compare_digest(reference_digest(reference), lock['reference_sha256']):
        raise ContractError('case reference differs')
    keys = ('case_id', 'question', 'role', 'role_version', 'scope', 'as_of', 'entities', 'historical_as_known')
    if any(lock[k] != reference[k] for k in keys):
        raise ContractError('case reference context differs')
    sources = load_isolated_sources(root, lock['sources'], protected)
    revisions = {rev.revision_id: rev for rev in (SourceRevision.create(source.path, 'evaluation_allowlist',
                 decode_source(source.raw, encoding='utf-8')) for source in sources)}
    if sorted(revisions) != reference['source_revisions']:
        raise ContractError('case reference sources differ')
    if any(e['quote'] not in revisions[e['revision_id']].decoded.text for e in reference['evidence']):
        raise ContractError('reference evidence not in case sources')
    return PreparedEvaluationCase(lock['question'], lock['role'], lock['role_version'], lock['scope'],
                                  lock['as_of'], tuple(lock['entities']), lock['historical_as_known'], sources)
