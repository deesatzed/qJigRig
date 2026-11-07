"""Reference-linked mechanical comparison; references are not independent truth."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import date

from .contracts import ContractError
from .evaluation_replay import verify_direct_archive
from .indexing import index_entries

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_REV = re.compile(r'rev1:[0-9a-f]{64}\Z')


def reference_digest(reference: dict) -> str:
    """Validate and hash a private, attributed reference with explicit evidence."""
    keys = {'case_id', 'question', 'role', 'role_version', 'scope', 'as_of', 'entities', 'historical_as_known',
            'source_revisions', 'expected_answer', 'provenance', 'evidence'}
    if not isinstance(reference, dict) or set(reference) != keys:
        raise ContractError('invalid evaluation reference')
    if any(not isinstance(reference[k], str) or not reference[k].strip() for k in ('case_id', 'question', 'role', 'role_version', 'scope')):
        raise ContractError('invalid reference identity')
    try:
        if not isinstance(reference['as_of'], str) or date.fromisoformat(reference['as_of']).isoformat() != reference['as_of']:
            raise ValueError
    except ValueError as exc:
        raise ContractError('invalid reference date') from exc
    entities, revisions = reference['entities'], reference['source_revisions']
    if (not isinstance(entities, list) or any(not isinstance(x, str) or not x.strip() for x in entities)
            or entities != sorted(set(entities)) or type(reference['historical_as_known']) is not bool
            or not isinstance(revisions, list) or not revisions or any(not isinstance(x, str) or not _REV.fullmatch(x) for x in revisions)
            or revisions != sorted(set(revisions)) or reference['expected_answer'] not in ('yes', 'no', 'unknown', 'conflict')
            or reference['provenance'] not in ('authored_unvalidated', 'ai_reviewed_unvalidated')):
        raise ContractError('invalid reference context')
    evidence = reference['evidence']
    if (not isinstance(evidence, list) or not evidence or any(
            not isinstance(e, dict) or set(e) != {'revision_id', 'quote'} or e['revision_id'] not in revisions
            or not isinstance(e['quote'], str) or not e['quote'].strip() for e in evidence)):
        raise ContractError('invalid reference evidence')
    try:
        encoded = json.dumps(reference, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ContractError('invalid evaluation reference') from exc
    return hashlib.sha256(encoded).hexdigest()


def score_direct_archive(archive, journal, reference: dict, *, expected_run_sha256: str,
                         expected_reference_sha256: str) -> dict:
    """Compare a replayed direct answer to one externally pinned private reference.

    Exact quote coverage is a narrow mechanical check. It cannot establish that
    a reference is correct, an answer is supported, or a source is authoritative.
    """
    ref_hash = reference_digest(reference)
    if (not isinstance(expected_reference_sha256, str) or not _SHA.fullmatch(expected_reference_sha256)
            or not hmac.compare_digest(ref_hash, expected_reference_sha256)):
        raise ContractError('reference digest mismatch')
    replay = verify_direct_archive(archive, journal, expected_digest=expected_run_sha256)
    if replay['status'] not in ('structurally_verified', 'incomplete') or replay.get('sha256') != expected_run_sha256:
        raise ContractError('direct run is not structurally verified')
    context = archive.context()
    request, applicability = context['request'], context['applicability']
    if (any(reference[k] != request[k] for k in ('question', 'role', 'role_version', 'scope'))
            or any(reference[k] != applicability[k] for k in ('as_of', 'entities', 'historical_as_known'))
            or reference['source_revisions'] != context['source_revisions']):
        raise ContractError('reference differs from direct run context')
    revisions = {ident: archive.revision(ident) for ident in context['source_revisions']}
    entries = {entry.entry_id: entry for revision in revisions.values() for entry in index_entries(revision)}
    for requirement in reference['evidence']:
        if requirement['quote'] not in revisions[requirement['revision_id']].decoded.text:
            raise ContractError('reference quote not in source')
    if replay['status'] == 'incomplete':
        return {'case_id': reference['case_id'], 'run_sha256': expected_run_sha256, 'reference_sha256': ref_hash,
                'reference_provenance': reference['provenance'], 'classification': replay.get('classification', 'unknown_review'),
                'answer_matches_reference': None, 'required_evidence_covered': None,
                'failure_verified': replay.get('failure_verified', False),
                'reconciliation_required': bool(journal.pending(request['request_id'])) or replay.get('reconciliation_required', False),
                'semantic_assurance': 'not_assessed'}
    result = next(event['data'] for event in archive.events() if event['kind'] == 'run_result')
    cited = [(entries[c['entry_id']].revision_id, c['quote']) for c in result['citations']]
    covered = all(any(revision == required['revision_id'] and required['quote'] in quote for revision, quote in cited)
                  for required in reference['evidence'])
    actual, expected = result['answer'], reference['expected_answer']
    if not covered:
        classification = 'unknown_review'
    elif actual == expected:
        classification = 'justified_deferral' if actual == 'unknown' else 'matches_reference'
    elif actual == 'unknown':
        classification = 'unjustified_deferral'
    else:
        classification = 'differs_from_reference'
    return {'case_id': reference['case_id'], 'run_sha256': expected_run_sha256, 'reference_sha256': ref_hash,
            'reference_provenance': reference['provenance'], 'classification': classification,
            'answer_matches_reference': actual == expected, 'required_evidence_covered': covered,
            'semantic_assurance': 'not_assessed'}


def make_reference(*, case_id: str, request, sources, as_of: str, entities: list[str], historical_as_known: bool,
                   expected_answer: str, provenance: str, evidence: list[dict]) -> dict:
    """Bind private reference assertions to source revisions and exact quotations.

    Sources should come from the isolated loader. This function checks bytes and
    quoted text, not the completeness of the protected manifest or correctness
    of the reference judgment.
    """
    from .contracts import Request
    from .evaluation import EvaluationSource
    from .sources import SourceRevision, decode_source
    if (not isinstance(request, Request) or not isinstance(sources, tuple) or not sources or
            not all(isinstance(source, EvaluationSource) for source in sources)):
        raise ContractError('request and isolated sources required')
    revisions = {}
    for source in sources:
        if (source.path in revisions or not isinstance(source.raw, bytes) or not isinstance(source.sha256, str)
                or not _SHA.fullmatch(source.sha256) or not hmac.compare_digest(hashlib.sha256(source.raw).hexdigest(), source.sha256)):
            raise ContractError('invalid isolated source')
        revisions[source.path] = SourceRevision.create(source.path, 'evaluation_allowlist', decode_source(source.raw, encoding='utf-8'))
    if not isinstance(evidence, list) or not evidence:
        raise ContractError('reference evidence required')
    bound = []
    for item in evidence:
        if (not isinstance(item, dict) or set(item) != {'path', 'quote'} or not isinstance(item['path'], str)
                or item['path'] not in revisions or not isinstance(item['quote'], str) or not item['quote'].strip()
                or item['quote'] not in revisions[item['path']].decoded.text):
            raise ContractError('reference evidence is not in source')
        bound.append({'revision_id': revisions[item['path']].revision_id, 'quote': item['quote']})
    if not isinstance(entities, list) or any(not isinstance(x, str) or not x.strip() for x in entities) or len(set(entities)) != len(entities):
        raise ContractError('invalid reference entities')
    ref = {'case_id': case_id, 'question': request.question, 'role': request.role, 'role_version': request.role_version,
           'scope': request.scope, 'as_of': as_of, 'entities': sorted(entities), 'historical_as_known': historical_as_known,
           'source_revisions': sorted(r.revision_id for r in revisions.values()), 'expected_answer': expected_answer,
           'provenance': provenance, 'evidence': bound}
    reference_digest(ref)
    return ref
