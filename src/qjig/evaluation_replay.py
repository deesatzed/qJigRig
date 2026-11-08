"""Structural replay for recorded direct evaluation runs; never invokes inference."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict

from .contracts import ContractError, Request
from .evaluation import DirectRetrieval, FullEvidence, CatalogRetrieval, _full_source_entries, _full_source_packet
from .evaluation_direct import _prompt, _validator, _catalog_incomplete
from .indexing import index_entries
from .journal import Journal
from .packets import serialize_packet
from .providers import (ProviderRequest, openrouter_wire_payload_v1, openrouter_wire_payload_v2,
                        openrouter_wire_payload_v3, openrouter_wire_payload_v4, openrouter_wire_payload_v5)
from .run_archive import RunArchive


def _check_wire(request, metadata, transport):
    if not isinstance(metadata,dict) or 'wire_payload_sha256' not in metadata:
        if request.route is not None and not str(transport).startswith('STAND_IN:'):
            raise ContractError('routed direct wire evidence unavailable')
        return
    fmt=metadata.get('wire_payload_format')
    serializers={'openrouter.chat.v1':openrouter_wire_payload_v1,'openrouter.chat.v2':openrouter_wire_payload_v2,
                 'openrouter.chat.v3':openrouter_wire_payload_v3,'openrouter.chat.v4':openrouter_wire_payload_v4,
                 'openrouter.chat.v5':openrouter_wire_payload_v5}
    if fmt not in serializers or (request.route is not None and fmt!='openrouter.chat.v5'):
        raise ContractError('direct wire format differs')
    digest=hashlib.sha256(serializers[fmt](request).encode('utf-8')).hexdigest()
    if not isinstance(metadata['wire_payload_sha256'],str) or not hmac.compare_digest(digest,metadata['wire_payload_sha256']):
        raise ContractError('direct wire digest differs')


def _rebuild_search(context, revisions):
    full = context['schema'] in ('qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v6')
    catalog = context['schema'] in ('qjig.direct-evaluation.v7', 'qjig.direct-evaluation.v8')
    search = object.__new__(FullEvidence if full else CatalogRetrieval if catalog else DirectRetrieval)
    search._revisions = tuple(revisions)
    search._entries = _full_source_entries(revisions) if full else [entry for revision in revisions for entry in index_entries(revision)]
    search._want, search._max_bytes = context['want'], context['max_bytes']
    search._max_rounds, search._expanded, search._trace = 1 + context['followups'], context['expanded'], []
    if full:
        search._packet = _full_source_packet(search._entries, context['max_bytes'])
    if catalog:
        from .applicability import ApplicabilityInputs
        from .acquisition import _check_role_priors
        search._inputs = ApplicabilityInputs.from_dict(context['catalog_applicability'])
        search._role_priors = context['catalog_role_priors']
        _check_role_priors(search._role_priors)
        search._scope = context['request']['scope']
        if ({m.revision_id for m in search._inputs.collection.members} != {r.revision_id for r in revisions}
                or search._inputs.as_of != context['applicability']['as_of']
                or sorted(search._inputs.request_entities) != context['applicability']['entities']
                or search._inputs.historical_as_known != context['applicability']['historical_as_known']):
            raise ContractError('catalog applicability differs')
    return search


def verify_direct_archive(archive: RunArchive, journal: Journal, *, expected_digest: str | None = None,
                          original_run_only: bool = False) -> dict:
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
        if not isinstance(context, dict) or context.get('schema') not in ('qjig.direct-evaluation.v1', 'qjig.direct-evaluation.v2', 'qjig.direct-evaluation.v3', 'qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v5', 'qjig.direct-evaluation.v6', 'qjig.direct-evaluation.v7', 'qjig.direct-evaluation.v8'):
            raise ContractError('invalid direct context')
        if context['schema'] in ('qjig.direct-evaluation.v3', 'qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v5', 'qjig.direct-evaluation.v6', 'qjig.direct-evaluation.v7', 'qjig.direct-evaluation.v8'):
            keys.add('case_binding')
            binding = context.get('case_binding')
            if (not isinstance(binding, dict) or set(binding) != {'case_id', 'design_sha256', 'case_sha256', 'reference_sha256'}
                    or not isinstance(binding['case_id'], str) or not binding['case_id'].strip()
                    or any(not isinstance(binding[k], str) or not re.fullmatch(r'[0-9a-f]{64}', binding[k])
                           for k in ('design_sha256', 'case_sha256', 'reference_sha256'))):
                raise ContractError('invalid case binding')
        if context['schema'] in ('qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v6'):
            keys.add('retrieval_mode')
            if context.get('retrieval_mode') != 'full_source_v1' or context.get('followups') != 0 or context.get('expanded') is not False:
                raise ContractError('invalid full evidence mode')
        if context['schema'] in ('qjig.direct-evaluation.v7', 'qjig.direct-evaluation.v8'):
            keys.update(('retrieval_mode','catalog_applicability','catalog_role_priors'))
            if context.get('retrieval_mode') != 'qjig_catalog_v1' or context.get('expanded') is not True:
                raise ContractError('invalid catalog retrieval mode')
        if context['schema'] in ('qjig.direct-evaluation.v5', 'qjig.direct-evaluation.v6', 'qjig.direct-evaluation.v8'):
            from .evaluation_budget import validate_assignment_binding
            keys.add('evaluation_assignment')
            validate_assignment_binding(context.get('evaluation_assignment'))
        if 'route' in context:
            keys.add('route')
            ProviderRequest('direct_initial',context['provider'],context['model'],'',context['max_tokens'],
                            max_price=context['max_price'],route=context['route'])
            if context['route'] is None:
                raise ContractError('invalid direct route')
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
        if type(original_run_only) is not bool:
            raise ContractError('invalid journal scope')
        if original_run_only:
            if not isinstance(expected_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_digest):
                raise ContractError('anchored digest required for original run prefix')
            results = [e for e in events if e['kind'] == 'run_result']
            if len(results) != 1 or results[0]['data'].get('status') != 'recorded_unvalidated':
                raise ContractError('completed direct run required for prefix replay')
            ids = results[0]['data'].get('call_ids')
            if not isinstance(ids, list) or not ids:
                raise ContractError('direct call identity missing')
            matches = [i for i, e in enumerate(journal_events) if e.call_id == ids[-1] and e.kind == 'receipt']
            if len(matches) != 1:
                raise ContractError('direct terminal receipt missing or ambiguous')
            split = matches[0] + 1
            suffix = journal_events[split:]
            seen = set()
            for event in suffix:
                if event.stage != 'semantic_review':
                    raise ContractError('unexpected later journal event')
                if event.kind == 'intent':
                    if event.call_id in seen or event.payload.get('context_binding') != {'reviewed_run_sha256':expected_digest}:
                        raise ContractError('semantic review binding differs')
                    seen.add(event.call_id)
                elif event.call_id not in seen:
                    raise ContractError('semantic review terminal has no intent')
            journal_events = journal_events[:split]
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
        search = _rebuild_search(context, revisions)
        packets, query, value = [], request.question, None
        for step, call_id in enumerate(call_ids):
            trace, sent, response, validated = events[step * 4: step * 4 + 4]
            found = search.search(query)
            if isinstance(search, CatalogRetrieval) and _catalog_incomplete(found):
                raise ContractError('catalog evidence was incomplete before dispatch')
            packets.append(found['packet'])
            reconstructed = {key: val for key, val in found.items() if key != 'packet'}
            reconstructed['packet'] = json.loads(serialize_packet(found['packet']))
            if trace['call_id'] != f'{request.request_id}#{step + 1}' or trace['data'] != reconstructed:
                raise ContractError('direct search trace differs')
            allow = step + 1 < search._max_rounds
            pr = ProviderRequest('direct_initial' if step == 0 else 'direct_final', context['provider'], context['model'],
                                 _prompt(request, context['applicability'], packets, allow, legacy_request_id=context['schema'].endswith('.v1')), context['max_tokens'],
                                 max_price=context['max_price'],route=context.get('route'))
            data = sent['data']
            expected_request = {'stage': pr.stage, 'provider': pr.provider, 'model': pr.model, 'prompt': pr.prompt,
                                'max_tokens': pr.max_tokens, 'input_sha256': pr.input_sha256()}
            if pr.max_price is not None:
                expected_request['max_price'] = dict(pr.max_price)
            if pr.route is not None:
                expected_request['route'] = pr.route
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
            _check_wire(pr,response['data'].get('metadata'),receipt.payload.get('transport'))
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
        result_report = {'status': 'structurally_verified' if expected_digest is not None else 'unanchored',
                         'sha256': digest, 'semantic_assurance': 'not_assessed'}
        if original_run_only:
            result_report['journal_scope'] = 'original_run_prefix'
        return result_report
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
    search = _rebuild_search(context, revisions)
    packets, query, cursor, terminal_failure = [], request.question, 0, None
    for step in range(1 + context['followups']):
        found = search.search(query)
        packets.append(found['packet'])
        trace = {k: v for k, v in found.items() if k != 'packet'}
        trace['packet'] = json.loads(serialize_packet(found['packet']))
        if cursor >= len(events) - 1 or events[cursor]['kind'] != 'trace' or events[cursor]['call_id'] != f'{request.request_id}#{step + 1}' or events[cursor]['data'] != trace:
            raise ContractError('failure search differs')
        cursor += 1
        if step < len(calls) and isinstance(search, CatalogRetrieval) and _catalog_incomplete(found):
            raise ContractError('catalog evidence was incomplete before dispatch')
        if step >= len(calls):
            if result['failure'] == 'catalog_evidence_incomplete' and isinstance(search, CatalogRetrieval) and _catalog_incomplete(found):
                terminal_failure = 'retrieval_failure'
            elif result['failure'] not in ('BudgetExceeded', 'ReconciliationRequired', 'preflight_unavailable'):
                raise ContractError('missing direct attempt')
            if cursor != len(events) - 1:
                raise ContractError('unexpected events after refusal')
            break  # policy and prior unresolved calls are not fully archived here
        call_id = calls[step]
        if cursor >= len(events) - 1 or events[cursor]['kind'] != 'request':
            raise ContractError('failure request missing')
        sent = events[cursor]; cursor += 1
        allow = step + 1 < search._max_rounds
        pr = ProviderRequest('direct_initial' if step == 0 else 'direct_final', context['provider'], context['model'],
                             _prompt(request, context['applicability'], packets, allow, legacy_request_id=context['schema'].endswith('.v1')),
                             context['max_tokens'], max_price=context['max_price'],route=context.get('route'))
        expected_request = {'stage': pr.stage, 'provider': pr.provider, 'model': pr.model, 'prompt': pr.prompt,
                            'max_tokens': pr.max_tokens, 'input_sha256': pr.input_sha256()}
        if pr.max_price is not None:
            expected_request['max_price'] = dict(pr.max_price)
        if pr.route is not None:
            expected_request['route'] = pr.route
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
        _check_wire(pr,response.get('metadata'),terminal.payload.get('transport'))
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
