"""Structural replay for recorded direct evaluation runs; never invokes inference."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict

from .contracts import ContractError, Request
from .evaluation import DirectRetrieval
from .evaluation_direct import _prompt, _validator
from .indexing import index_entries
from .journal import Journal
from .packets import serialize_packet
from .providers import ProviderRequest
from .run_archive import RunArchive


def verify_direct_archive(archive: RunArchive, journal: Journal, *, expected_digest: str | None = None) -> dict:
    """Reconstruct successful direct runs; failures and missing work remain incomplete.

    Digest anchoring detects changes relative to the supplied digest, not source
    authority, label isolation, provider authenticity or model correctness.
    """
    invalid = {'status': 'invalid', 'sha256': None, 'semantic_assurance': 'not_assessed'}
    try:
        if not isinstance(archive, RunArchive) or not isinstance(journal, Journal):
            raise ContractError('archive and journal required')
        context, events = archive.context(), archive.events()
        keys = {'schema', 'request', 'source_revisions', 'applicability', 'want', 'max_bytes', 'followups',
                'expanded', 'provider', 'model', 'max_tokens', 'max_price'}
        if not isinstance(context, dict) or context.get('schema') not in ('qjig.direct-evaluation.v1', 'qjig.direct-evaluation.v2', 'qjig.direct-evaluation.v3'):
            raise ContractError('invalid direct context')
        if context['schema'] == 'qjig.direct-evaluation.v3':
            keys.add('case_binding')
            binding = context.get('case_binding')
            if (not isinstance(binding, dict) or set(binding) != {'case_id', 'design_sha256', 'case_sha256', 'reference_sha256'}
                    or not isinstance(binding['case_id'], str) or not binding['case_id'].strip()
                    or any(not isinstance(binding[k], str) or not re.fullmatch(r'[0-9a-f]{64}', binding[k])
                           for k in ('design_sha256', 'case_sha256', 'reference_sha256'))):
                raise ContractError('invalid case binding')
        if set(context) != keys:
            raise ContractError('invalid direct context')
        request = Request.from_dict(context['request'])
        revisions = [archive.revision(i) for i in archive.revision_ids()]
        if (context['source_revisions'] != sorted(r.revision_id for r in revisions) or not revisions or archive.source_ids()
                or type(context['want']) is not int or not 1 <= context['want'] <= 100
                or type(context['max_bytes']) is not int or not 1 <= context['max_bytes'] <= 1024 * 1024
                or type(context['followups']) is not int or context['followups'] not in (0, 1)
                or type(context['expanded']) is not bool):
            raise ContractError('invalid direct sources or bounds')
        journal_events = journal.events(request.request_id)
        snapshot = {'context': context, 'events': events, 'journal': [asdict(e) for e in journal_events],
                    'revisions': [r.revision_id for r in revisions]}
        raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        if expected_digest is not None and (not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest)
                                            or not hmac.compare_digest(digest, expected_digest)):
            raise ContractError('direct archive digest mismatch')
        results = [e for e in events if e['kind'] == 'run_result']
        if len(results) != 1:
            return {'status': 'incomplete', 'sha256': digest, 'semantic_assurance': 'not_assessed'}
        if results[0]['data'].get('status') == 'unavailable':
            return _verify_failure(context, events, journal_events, revisions, request, digest)
        if results[0]['data'].get('status') != 'recorded_unvalidated':
            raise ContractError('invalid direct result status')
        result = results[0]['data']
        call_ids = result['call_ids']
        if (not isinstance(call_ids, list) or not 1 <= len(call_ids) <= 1 + context['followups']
                or len(set(call_ids)) != len(call_ids)):
            raise ContractError('invalid direct call set')
        expected_kinds = [kind for _ in call_ids for kind in ('trace', 'request', 'response', 'validation')] + ['run_result']
        if [e['kind'] for e in events] != expected_kinds or len(journal_events) != len(call_ids) * 2:
            raise ContractError('direct events missing or unexpected')
        search = object.__new__(DirectRetrieval)
        search._revisions = tuple(revisions)
        search._entries = [entry for revision in revisions for entry in index_entries(revision)]
        search._want, search._max_bytes = context['want'], context['max_bytes']
        search._max_rounds, search._expanded, search._trace = 1 + context['followups'], context['expanded'], []
        packets, query, value = [], request.question, None
        for step, call_id in enumerate(call_ids):
            trace, sent, response, validated = events[step * 4: step * 4 + 4]
            found = search.search(query)
            packets.append(found['packet'])
            reconstructed = {key: val for key, val in found.items() if key != 'packet'}
            reconstructed['packet'] = json.loads(serialize_packet(found['packet']))
            if trace['call_id'] != f'{request.request_id}#{step + 1}' or trace['data'] != reconstructed:
                raise ContractError('direct search trace differs')
            allow = step + 1 < search._max_rounds
            pr = ProviderRequest('direct_initial' if step == 0 else 'direct_final', context['provider'], context['model'],
                                 _prompt(request, context['applicability'], packets, allow, legacy_request_id=context['schema'].endswith('.v1')), context['max_tokens'],
                                 max_price=context['max_price'])
            data = sent['data']
            expected_request = {'stage': pr.stage, 'provider': pr.provider, 'model': pr.model, 'prompt': pr.prompt,
                                'max_tokens': pr.max_tokens, 'input_sha256': pr.input_sha256()}
            if pr.max_price is not None:
                expected_request['max_price'] = dict(pr.max_price)
            if sent['call_id'] != call_id or data != expected_request or response['call_id'] != call_id or validated['call_id'] != call_id:
                raise ContractError('direct request differs')
            body = response['data']['body']
            raw_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
            if response['data']['body_sha256'] != raw_hash or not 200 <= response['data']['http_status'] < 300:
                raise ContractError('direct response invalid')
            value, failure = _validator(packets, allow)(body)
            if failure is not None or validated['data'] != {'value': value, 'failure': None}:
                raise ContractError('direct response validation differs')
            intent, receipt = journal_events[step * 2:step * 2 + 2]
            if (intent.kind != 'intent' or receipt.kind != 'receipt' or intent.call_id != call_id or receipt.call_id != call_id
                    or (intent.stage, intent.provider, intent.model, intent.input_sha256) != (pr.stage, pr.provider, pr.model, pr.input_sha256())
                    or (receipt.stage, receipt.provider, receipt.model, receipt.input_sha256) != (pr.stage, pr.provider, pr.model, pr.input_sha256())
                    or receipt.payload.get('raw_sha256') != raw_hash or receipt.payload.get('usage') != (response['data']['usage'] or {})
                    or receipt.payload.get('http_status') != response['data']['http_status']
                    or receipt.payload.get('metadata') != response['data']['metadata']
                    or receipt.payload.get('note') != response['data']['note']
                    or intent.payload.get('request_max_price') != context['max_price']
                    or receipt.payload.get('validation') != 'ok'):
                raise ContractError('direct journal differs')
            if step + 1 < len(call_ids):
                if value['action'] != 'search':
                    raise ContractError('unexpected extra call')
                query = value['query']
            elif value['action'] != 'answer':
                raise ContractError('direct answer missing')
        expected = {'status': 'recorded_unvalidated', 'failure': None, 'answer': value['answer'],
                    'citations': value['citations'], 'call_ids': call_ids, 'searches': list(search.trace)}
        if results[0]['call_id'] != request.request_id or result != expected:
            raise ContractError('direct result differs')
        return {'status': 'structurally_verified' if expected_digest is not None else 'unanchored',
                'sha256': digest, 'semantic_assurance': 'not_assessed'}
    except (ContractError, KeyError, ValueError, TypeError, AttributeError, UnicodeError, OverflowError):
        return invalid


def _verify_failure(context, events, journal_events, revisions, request, digest):
    """Check recorded failure mechanics without claiming that an uncertain call finished."""
    result = events[-1]['data']
    if events[-1]['kind'] != 'run_result' or events[-1]['call_id'] != request.request_id:
        raise ContractError('failure result missing')
    if set(result) != {'status', 'failure', 'answer', 'call_ids', 'searches'} or result['answer'] is not None:
        raise ContractError('invalid failure result')
    calls = result['call_ids']
    if (not isinstance(calls, list) or len(calls) > 1 + context['followups'] or len(set(calls)) != len(calls)
            or len(journal_events) != len(calls) * 2):
        raise ContractError('invalid failed call set')
    search = object.__new__(DirectRetrieval)
    search._revisions = tuple(revisions)
    search._entries = [entry for revision in revisions for entry in index_entries(revision)]
    search._want, search._max_bytes = context['want'], context['max_bytes']
    search._max_rounds, search._expanded, search._trace = 1 + context['followups'], context['expanded'], []
    packets, query, cursor, terminal_failure = [], request.question, 0, None
    for step in range(1 + context['followups']):
        found = search.search(query)
        packets.append(found['packet'])
        trace = {k: v for k, v in found.items() if k != 'packet'}
        trace['packet'] = json.loads(serialize_packet(found['packet']))
        if cursor >= len(events) - 1 or events[cursor]['kind'] != 'trace' or events[cursor]['call_id'] != f'{request.request_id}#{step + 1}' or events[cursor]['data'] != trace:
            raise ContractError('failure search differs')
        cursor += 1
        if step >= len(calls):
            if result['failure'] not in ('BudgetExceeded', 'ReconciliationRequired', 'preflight_unavailable') or cursor != len(events) - 1:
                raise ContractError('missing direct attempt')
            break  # policy and prior unresolved calls are not fully archived here
        call_id = calls[step]
        if cursor >= len(events) - 1 or events[cursor]['kind'] != 'request':
            raise ContractError('failure request missing')
        sent = events[cursor]; cursor += 1
        allow = step + 1 < search._max_rounds
        pr = ProviderRequest('direct_initial' if step == 0 else 'direct_final', context['provider'], context['model'],
                             _prompt(request, context['applicability'], packets, allow, legacy_request_id=context['schema'].endswith('.v1')),
                             context['max_tokens'], max_price=context['max_price'])
        expected_request = {'stage': pr.stage, 'provider': pr.provider, 'model': pr.model, 'prompt': pr.prompt,
                            'max_tokens': pr.max_tokens, 'input_sha256': pr.input_sha256()}
        if pr.max_price is not None:
            expected_request['max_price'] = dict(pr.max_price)
        intent, terminal = journal_events[step * 2:step * 2 + 2]
        identity = (pr.stage, pr.provider, pr.model, pr.input_sha256())
        if (sent['call_id'] != call_id or sent['data'] != expected_request or intent.kind != 'intent'
                or intent.call_id != call_id or terminal.call_id != call_id
                or (intent.stage, intent.provider, intent.model, intent.input_sha256) != identity
                or (terminal.stage, terminal.provider, terminal.model, terminal.input_sha256) != identity
                or intent.payload.get('request_max_price') != context['max_price'] or cursor >= len(events) - 1):
            raise ContractError('failure request binding differs')
        event = events[cursor]; cursor += 1
        if event['call_id'] != call_id:
            raise ContractError('failure call identity differs')
        if event['kind'] == 'failure':
            recorded = event['data'].get('failure')
            if (terminal.kind == 'uncertain' and recorded == 'uncertain_outcome' and result['failure'] == 'UncertainOutcome'):
                terminal_failure = 'uncertain_outcome'
            elif (terminal.kind == 'failure' and terminal.payload.get('error') == 'ProviderUnavailable'
                  and recorded == 'provider_failure' and result['failure'] == 'ProviderUnavailable'):
                terminal_failure = 'provider_failure'
            else:
                raise ContractError('failure terminal differs')
            if step != len(calls) - 1 or cursor != len(events) - 1:
                raise ContractError('work continues after failure')
            break
        if event['kind'] != 'response' or terminal.kind != 'receipt' or cursor >= len(events) - 1:
            raise ContractError('failure response missing')
        validated = events[cursor]; cursor += 1
        response = event['data']; body = response['body']; raw_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        if validated['kind'] != 'validation' or validated['call_id'] != call_id or response['body_sha256'] != raw_hash:
            raise ContractError('failure response differs')
        if 200 <= response['http_status'] < 300:
            try:
                value, failure = _validator(packets, allow)(body)
            except Exception:
                value, failure = None, 'validator_error'
        else:
            value, failure = None, 'http_error'
        if (validated['data'] != {'value': value, 'failure': failure} or terminal.payload.get('validation') != (failure or 'ok')
                or terminal.payload.get('raw_sha256') != raw_hash or terminal.payload.get('usage') != (response['usage'] or {})
                or terminal.payload.get('http_status') != response['http_status']
                or terminal.payload.get('metadata') != response['metadata'] or terminal.payload.get('note') != response['note']):
            raise ContractError('failure receipt differs')
        if failure is not None:
            if result['failure'] != failure or step != len(calls) - 1 or cursor != len(events) - 1:
                raise ContractError('failure classification differs')
            terminal_failure = ('malformed' if failure in ('malformed_output', 'schema_violation', 'invalid_followup')
                                else 'unsupported' if failure == 'unsupported_citation' else 'provider_failure' if failure == 'http_error'
                                else 'unknown_review' if failure == 'validator_error' else None)
            if terminal_failure is None:
                raise ContractError('unrecognized failure')
            break
        if value['action'] != 'search' or step + 1 >= search._max_rounds:
            raise ContractError('unexpected successful result in failure path')
        query = value['query']
    if result['searches'] != list(search.trace):
        raise ContractError('failure searches differ')
    return {'status': 'incomplete', 'sha256': digest, 'semantic_assurance': 'not_assessed',
            'failure_verified': terminal_failure is not None,
            'classification': terminal_failure or 'unknown_review',
            'reconciliation_required': terminal_failure == 'uncertain_outcome'}
