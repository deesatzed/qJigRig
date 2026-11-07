"""Portable authored-run evidence bundle; structural checks do not prove outcomes."""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .contracts import ContractError, Request
from .indexing import index_entries
from .logic import Observation, Outcome, evaluate, expression_ids, is_material, reachable_outcomes
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
        observations = {}
        evidence_by_predicate = {}
        for seq, record in enumerate(result['records'], 1):
            if type(record['sequence']) is not int or record['sequence'] != seq or record['predicate_id'] not in {p.id for p in plan.predicates}:
                raise ContractError('invalid trace sequence or predicate')
            observed = record['observation']
            if not isinstance(observed, dict) or set(observed) != {'outcome', 'reason'} or not isinstance(observed['reason'], str):
                raise ContractError('invalid trace observation')
            observations[record['predicate_id']] = Observation(Outcome(observed['outcome']), observed['reason'])
            evidence_by_predicate.setdefault(record['predicate_id'], []).extend(record['evidence'])
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
        recorded_observations = {key: {'outcome': value.outcome.value, 'reason': value.reason} for key, value in observations.items()}
        if result['observations'] != recorded_observations:
            raise ContractError('result observations differ from trace')
        predicate_ids = {p.id for p in plan.predicates}
        obligations = result['obligations']
        if not isinstance(obligations, list) or len(obligations) != len(predicate_ids):
            raise ContractError('invalid obligation set')
        skips = result['skipped']
        if not isinstance(skips, list) or any(not isinstance(item, dict) for item in skips):
            raise ContractError('invalid skip records')
        skip_by_predicate = {item['predicate_id']: item for item in skips}
        if len(skip_by_predicate) != len(skips) or not set(skip_by_predicate).issubset(predicate_ids):
            raise ContractError('invalid skip identities')
        evaluation = evaluate(plan.expression, observations)
        referenced = expression_ids(plan.expression)
        seen = set()
        for obligation in obligations:
            pid = obligation['predicate_id']
            if (pid not in predicate_ids or pid in seen or obligation['id'] != f'ob-{pid}' or
                    obligation['material'] is not True or obligation['kind'] != ('exception' if policy['needs'][pid].get('kind') == 'exception' else 'predicate_evidence') or
                    obligation['status'] not in ('open', 'evidence_found', 'unresolved', 'satisfied', 'skipped')):
                raise ContractError('invalid obligation binding')
            seen.add(pid)
            if obligation['status'] == 'satisfied' and (pid not in observations or observations[pid].outcome not in (Outcome.TRUE, Outcome.FALSE) or not evidence_by_predicate.get(pid)):
                raise ContractError('satisfied obligation lacks recorded evidence')
            if obligation['status'] == 'skipped' and (pid in observations or is_material(pid, plan.expression, observations)):
                raise ContractError('material obligation was skipped')
            if obligation['status'] == 'skipped':
                skip = skip_by_predicate.get(pid)
                if not skip or (pid not in referenced and skip.get('kind') != 'unreferenced'):
                    raise ContractError('skip lacks recorded justification')
                if pid in referenced and (skip.get('kind') != 'witnessed' or evaluation.outcome not in (Outcome.TRUE, Outcome.FALSE)
                                           or not evaluation.witnesses or skip.get('witnesses') != list(evaluation.witnesses)):
                    raise ContractError('skip lacks conclusive witnesses')
        if result['status'] == 'decided':
            reachable = reachable_outcomes(plan.expression, observations).outcomes
            if reachable != frozenset({result['outcome']}) or any(o['status'] not in ('satisfied', 'skipped') for o in obligations):
                raise ContractError('decision differs from recorded composition')
    except (ContractError, KeyError, TypeError, ValueError, UnicodeError, OverflowError, AttributeError):
        return {'status': 'invalid', 'sha256': None, 'semantic_assurance': 'not_assessed'}
    return {'status': 'structurally_verified' if expected_digest is not None else 'unanchored',
            'sha256': digest, 'semantic_assurance': 'not_assessed'}
