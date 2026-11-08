"""Reference-linked mechanical comparison; references are not independent truth."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import date
from dataclasses import asdict

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
                         expected_reference_sha256: str, original_run_only: bool = False) -> dict:
    """Compare a replayed direct answer to one externally pinned private reference.

    Exact quote coverage is a narrow mechanical check. It cannot establish that
    a reference is correct, an answer is supported, or a source is authoritative.
    """
    ref_hash = reference_digest(reference)
    if (not isinstance(expected_reference_sha256, str) or not _SHA.fullmatch(expected_reference_sha256)
            or not hmac.compare_digest(ref_hash, expected_reference_sha256)):
        raise ContractError('reference digest mismatch')
    replay = verify_direct_archive(archive, journal, expected_digest=expected_run_sha256,
                                   original_run_only=original_run_only)
    if replay['status'] not in ('structurally_verified', 'incomplete') or replay.get('sha256') != expected_run_sha256:
        raise ContractError('direct run is not structurally verified')
    context = archive.context()
    request, applicability = context['request'], context['applicability']
    if context.get('schema') in ('qjig.direct-evaluation.v3', 'qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v5', 'qjig.direct-evaluation.v6', 'qjig.direct-evaluation.v7', 'qjig.direct-evaluation.v8'):
        binding = context['case_binding']
        if binding['case_id'] != reference['case_id'] or binding['reference_sha256'] != ref_hash:
            raise ContractError('reference differs from recorded case binding')
    if (any(reference[k] != request[k] for k in ('question', 'role', 'role_version', 'scope'))
            or any(reference[k] != applicability[k] for k in ('as_of', 'entities', 'historical_as_known'))
            or reference['source_revisions'] != context['source_revisions']):
        raise ContractError('reference differs from direct run context')
    revisions = {ident: archive.revision(ident) for ident in context['source_revisions']}
    if context.get('schema') in ('qjig.direct-evaluation.v4', 'qjig.direct-evaluation.v6'):
        from .evaluation import _full_source_entries
        entries = {entry.entry_id: entry for entry in _full_source_entries(revisions.values())}
    else:
        entries = {entry.entry_id: entry for revision in revisions.values() for entry in index_entries(revision)}
    for requirement in reference['evidence']:
        if requirement['quote'] not in revisions[requirement['revision_id']].decoded.text:
            raise ContractError('reference quote not in source')
    if replay['status'] == 'incomplete':
        return {'case_id': reference['case_id'], 'run_sha256': expected_run_sha256, 'reference_sha256': ref_hash,
                'reference_provenance': reference['provenance'], 'classification': replay.get('classification', 'unknown_review'),
                'answer_matches_reference': None, 'required_evidence_covered': None,
                'recorded_answer': None, 'reference_expected_answer': reference['expected_answer'],
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
    result_score = {'case_id': reference['case_id'], 'run_sha256': expected_run_sha256, 'reference_sha256': ref_hash,
            'reference_provenance': reference['provenance'], 'classification': classification,
            'answer_matches_reference': actual == expected, 'required_evidence_covered': covered,
            'recorded_answer': actual, 'reference_expected_answer': expected,
            'semantic_assurance': 'not_assessed'}
    if original_run_only:
        result_score['journal_scope'] = 'original_run_prefix'
    return result_score


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


def summarize_intervention_pairs(design: dict, records: list[dict], *, expected_design_sha256: str) -> dict:
    """Report every parent/intervention assignment without inferring missing outcomes.

    Input records and their arm mappings are private caller assertions. This
    does not authenticate scores or establish semantic validity of references.
    """
    from .evaluation import validate_evaluation_design
    if not isinstance(expected_design_sha256, str) or not _SHA.fullmatch(expected_design_sha256):
        raise ContractError('frozen design digest required')
    validate_evaluation_design(design, expected_digest=expected_design_sha256)
    if not isinstance(records, list):
        raise ContractError('scored assignments must be a list')
    families = {family['id']: family['partition'] for family in design['families']}
    cases = {case['id']: case for case in design['cases']}
    if sum(design['repeats'][families[case['family']]] for case in cases.values()) * len(design['arms']) > 100_000:
        raise ContractError('evaluation assignment set exceeds limit')
    answers = ('yes', 'no', 'unknown', 'conflict')
    assignments, references, run_ids = {}, {}, set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'arm', 'repeat', 'score'} or not isinstance(record['score'], dict):
            raise ContractError('invalid scored assignment')
        score, arm, repeat = record['score'], record['arm'], record['repeat']
        case_id = score.get('case_id')
        if (not isinstance(case_id, str) or case_id not in cases or not isinstance(arm, str) or arm not in design['arms']
                or type(repeat) is not int or not 1 <= repeat <= design['repeats'][families[cases[case_id]['family']]]):
            raise ContractError('unassigned score')
        key = (case_id, arm, repeat)
        run_id, ref_id = score.get('run_sha256'), score.get('reference_sha256')
        expected, actual = score.get('reference_expected_answer'), score.get('recorded_answer')
        covered, matched, provenance = score.get('required_evidence_covered'), score.get('answer_matches_reference'), score.get('reference_provenance')
        if (key in assignments or not isinstance(run_id, str) or not _SHA.fullmatch(run_id) or run_id in run_ids
                or not isinstance(ref_id, str) or not _SHA.fullmatch(ref_id) or expected not in answers
                or (actual is not None and actual not in answers) or covered not in (True, False, None)
                or type(covered) not in (bool, type(None)) or type(matched) not in (bool, type(None))
                or provenance not in ('authored_unvalidated', 'ai_reviewed_unvalidated')
                or (actual is None and (covered is not None or matched is not None))
                or (actual is not None and (type(covered) is not bool or matched is not (actual == expected)))):
            raise ContractError('invalid or duplicate scored result')
        reference = (ref_id, expected, provenance)
        if case_id in references and references[case_id] != reference:
            raise ContractError('case reference changed across assignments')
        references[case_id] = reference
        assignments[key] = score
        run_ids.add(run_id)
    pairs = []
    for case in sorted(cases.values(), key=lambda c: c['id']):
        parent = case['parent']
        if parent is None:
            continue
        partition = families[case['family']]
        for arm in sorted(design['arms']):
            for repeat in range(1, design['repeats'][partition] + 1):
                before = assignments.get((parent, arm, repeat))
                after = assignments.get((case['id'], arm, repeat))
                valid = bool(before and after and before['recorded_answer'] is not None and after['recorded_answer'] is not None
                             and before['required_evidence_covered'] and after['required_evidence_covered'])
                if valid:
                    expected_change = before['reference_expected_answer'] != after['reference_expected_answer']
                    observed_change = before['recorded_answer'] != after['recorded_answer']
                    comparison = ('matches_reference' if before['answer_matches_reference'] and after['answer_matches_reference']
                                  else 'differs_from_reference')
                else:
                    expected_change = observed_change = None
                    comparison = 'unknown_review'
                pairs.append({'parent_case': parent, 'intervention_case': case['id'], 'partition': partition,
                              'arm': arm, 'repeat': repeat, 'parent_recorded': before is not None,
                              'intervention_recorded': after is not None, 'evidence_covered': valid,
                              'expected_change': expected_change, 'observed_change': observed_change, 'comparison': comparison})
    return {'design_sha256': expected_design_sha256, 'pairs': pairs,
            'complete_pairs': sum(p['evidence_covered'] for p in pairs), 'semantic_assurance': 'not_assessed'}


def score_fresh_archive(archive, journal, reference: dict, *, expected_run_sha256: str,
                        expected_reference_sha256: str, expected_journal_sha256: str | None = None,
                        original_run_only: bool = False) -> dict:
    """Score a replayed fresh graph separately from its mandatory request deferral.

    Exact reference quotes seen in model support statements are mechanical
    observations, not proof of relevance, completeness or reference correctness.
    """
    from .logic import Observation, Outcome, evaluate
    from .replay import verify_archive
    ref_hash = reference_digest(reference)
    if (not isinstance(expected_reference_sha256, str) or not _SHA.fullmatch(expected_reference_sha256)
            or not hmac.compare_digest(ref_hash, expected_reference_sha256)
            or not isinstance(expected_run_sha256, str) or not _SHA.fullmatch(expected_run_sha256)):
        raise ContractError('evaluation anchors required')
    replay = verify_archive(archive, expected_digest=expected_run_sha256)
    if replay.status not in ('structurally_verified', 'incomplete') or replay.digest != expected_run_sha256:
        raise ContractError('fresh run is not structurally verified')
    context, events = archive.context(), archive.events()
    request, inputs = context['request'], context['applicability_inputs']
    if type(original_run_only) is not bool:
        raise ContractError('invalid journal scope')
    recorded_prefix = None
    if original_run_only:
        if (replay.status != 'structurally_verified' or not isinstance(expected_journal_sha256,str)
                or not _SHA.fullmatch(expected_journal_sha256)):
            raise ContractError('anchored completed fresh journal required')
        original_requests=[e for e in events if e['kind']=='request']
        journal_events=journal.events(request['request_id'])
        if not original_requests:
            raise ContractError('fresh request identity missing')
        last_call=original_requests[-1]['call_id']
        matches=[i for i,e in enumerate(journal_events) if e.call_id==last_call and e.kind=='receipt']
        if len(matches)!=1:
            raise ContractError('fresh terminal receipt missing or ambiguous')
        split=matches[0]+1
        recorded_prefix=journal_events[:split]
        seen=set()
        for event in journal_events[split:]:
            if event.stage not in ('semantic_review','outcome_review'):
                raise ContractError('unexpected later journal event')
            if event.kind=='intent':
                expected_binding={'reviewed_run_sha256':expected_run_sha256,
                                  'reviewed_journal_sha256':expected_journal_sha256}
                if event.call_id in seen or event.payload.get('context_binding')!=expected_binding:
                    raise ContractError('fresh semantic review binding differs')
                seen.add(event.call_id)
            elif event.call_id not in seen:
                raise ContractError('semantic review terminal has no intent')
        encoded=json.dumps([asdict(e) for e in recorded_prefix],sort_keys=True,separators=(',',':'),
                           ensure_ascii=False,allow_nan=False).encode('utf-8')
        if not hmac.compare_digest(hashlib.sha256(encoded).hexdigest(),expected_journal_sha256):
            raise ContractError('fresh original journal anchor differs')
    elif expected_journal_sha256 is not None:
        _fresh_journal_for_scoring(journal, request['request_id'], expected_journal_sha256)
    binding = context.get('evaluation_case_binding')
    if (not isinstance(binding, dict) or binding.get('case_id') != reference['case_id']
            or binding.get('reference_sha256') != ref_hash
            or any(reference[k] != request[k] for k in ('question', 'role', 'role_version', 'scope'))
            or not isinstance(inputs, dict) or reference['as_of'] != inputs['as_of']
            or reference['entities'] != inputs['request_entities']
            or reference['historical_as_known'] != inputs['historical_as_known']
            or reference['source_revisions'] != sorted(context['corpus'])):
        raise ContractError('reference differs from fresh run context')
    revisions = {ident: archive.revision(ident) for ident in reference['source_revisions']}
    if any(item['quote'] not in revisions[item['revision_id']].decoded.text for item in reference['evidence']):
        raise ContractError('reference quote not in source')
    if replay.status == 'incomplete':
        recorded, reconciliations = _fresh_journal_for_scoring(journal, request['request_id'], expected_journal_sha256)
        results = [event['data'] for event in events if event['kind'] == 'run_result']
        if len(results) == 1 and results[0].get('schema') == 'qjig.fresh-result.v1':
            return _score_fresh_receipt_failure(context, events, journal, reference, expected_run_sha256, ref_hash, recorded, reconciliations)
        return _score_fresh_planner_failure(context, events, journal, reference, expected_run_sha256, ref_hash, recorded, reconciliations)
    requests = [e for e in events if e['kind'] == 'request']
    recorded = recorded_prefix if original_run_only else journal.events(request['request_id'])
    if len(recorded) != 2 * len(requests):
        raise ContractError('fresh journal call count differs')
    responses = {e['call_id']: e['data'] for e in events if e['kind'] == 'response'}
    for index, sent in enumerate(requests):
        intent, terminal = recorded[index * 2:index * 2 + 2]
        data, call_id = sent['data'], sent['call_id']
        response = responses.get(call_id)
        if (not isinstance(response, dict) or intent.kind != 'intent' or terminal.kind != 'receipt'
                or intent.call_id != call_id or terminal.call_id != call_id
                or (intent.stage, intent.provider, intent.model, intent.input_sha256) != (data['stage'], data['provider'], data['model'], data['input_sha256'])
                or (terminal.stage, terminal.provider, terminal.model, terminal.input_sha256) != (data['stage'], data['provider'], data['model'], data['input_sha256'])
                or terminal.payload.get('raw_sha256') != response['body_sha256']
                or terminal.payload.get('usage') != (response['usage'] or {})
                or terminal.payload.get('http_status') != response['http_status']
                or terminal.payload.get('metadata') != response['metadata']
                or terminal.payload.get('note') != response['note']
                or terminal.payload.get('validation') != 'ok'
                or intent.payload.get('request_max_price') != data.get('max_price')):
            raise ContractError('fresh journal binding differs')
    stages = {e['call_id']: e['data']['stage'] for e in requests}
    pending, quoted = [], []
    for event in events:
        if event['kind'] == 'validation' and stages.get(event['call_id']) in ('judge_positive', 'judge_negative'):
            value = event['data'].get('value')
            if isinstance(value, dict) and value.get('supported') is True and isinstance(value.get('quote'), str) and value['quote'].strip():
                pending.append(value['quote'])
        elif event['kind'] == 'trace':
            for quote in pending:
                usable = [e for e in event['data']['evidence'] if quote in e['text'] and context['corpus'].get(e['revision_id']) == 'match']
                if usable:
                    quoted.append((usable[0]['revision_id'], quote))
            pending.clear()
    covered = all(any(revision == item['revision_id'] and item['quote'] in quote for revision, quote in quoted)
                  for item in reference['evidence'])
    result = next(e['data'] for e in events if e['kind'] == 'run_result')
    if result['status'] != 'deferred' or 'plan_coverage_unestablished' not in result['reasons']:
        raise ContractError('fresh coverage deferral missing')
    observations = {k: Observation(Outcome(v['outcome']), v['reason']) for k, v in result['observations'].items()}
    graph = evaluate(result['expression'], observations).outcome
    answer = {Outcome.TRUE: 'yes', Outcome.FALSE: 'no', Outcome.UNKNOWN: 'unknown', Outcome.CONFLICT: 'conflict'}[graph]
    comparison = ('unknown_review' if not covered else
                  'matches_reference' if answer == reference['expected_answer'] else 'differs_from_reference')
    result_score = {'case_id': reference['case_id'], 'run_sha256': expected_run_sha256, 'reference_sha256': ref_hash,
            'reference_provenance': reference['provenance'], 'request_status': 'deferred', 'request_answer': None,
            'request_deferral_reason': 'plan_coverage_unestablished', 'deferral_assurance': 'not_adjudicated',
            'conditional_answer': answer, 'conditional_comparison': comparison, 'reference_expected_answer': reference['expected_answer'],
            'required_evidence_covered': covered,
            'semantic_assurance': 'not_assessed'}
    if original_run_only:
        result_score['journal_scope'] = 'original_run_prefix'
    return result_score



def fresh_journal_digest(journal, request_id: str) -> str:
    """Hash one complete journal snapshot; the caller must retain the anchor independently."""
    from .journal import Journal
    if not isinstance(journal, Journal) or not isinstance(request_id, str) or not request_id.strip():
        raise ContractError('journal and request identity required')
    encoded = json.dumps([asdict(e) for e in journal.events(request_id)], sort_keys=True,
                         separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _fresh_journal_for_scoring(journal, request_id, expected_digest):
    recorded = journal.events(request_id)
    resolutions = [event for event in recorded if event.kind == 'reconciled']
    if resolutions or expected_digest is not None:
        if (not isinstance(expected_digest, str) or not _SHA.fullmatch(expected_digest)
                or not hmac.compare_digest(fresh_journal_digest(journal, request_id), expected_digest)):
            raise ContractError('fresh reconciliation journal anchor differs')
    base = [event for event in recorded if event.kind != 'reconciled']
    uncertain = {e.call_id:e for e in base if e.kind == 'uncertain'}
    seen, result = set(), []
    for event in resolutions:
        prior = uncertain.get(event.call_id)
        payload = event.payload
        if (prior is None or event.call_id in seen or event.request_seq <= prior.request_seq
                or (event.stage,event.provider,event.model,event.input_sha256) !=
                   (prior.stage,prior.provider,prior.model,prior.input_sha256)
                or not isinstance(payload, dict) or set(payload) != {'resolution','detail'}
                or payload['resolution'] not in ('executed','not_executed')
                or not isinstance(payload['detail'], str) or not payload['detail'].strip()):
            raise ContractError('invalid fresh reconciliation binding')
        seen.add(event.call_id)
        result.append({'call_id':event.call_id, 'resolution':payload['resolution'],
                       'detail':payload['detail'], 'provenance':'operator_assertion'})
    return base, result


def _score_fresh_receipt_failure(context, events, journal, reference, run_hash, ref_hash, recorded, reconciliations):
    """Retain verified post-planning failures without inferring a graph result."""
    request_id = context['request']['request_id']
    pending = {event.call_id for event in journal.pending(request_id)}
    sent = [event for event in events if event['kind'] == 'request']
    if not sent or len(recorded) != 2 * len(sent):
        raise ContractError('incomplete fresh journal call count or reconciliation differs')
    responses = {e['call_id']:e['data'] for e in events if e['kind'] == 'response'}
    validations = {e['call_id']:e['data'] for e in events if e['kind'] == 'validation'}
    failures = {e['call_id']:e['data'] for e in events if e['kind'] == 'failure'}
    outcomes, uncertain = [], set()
    for i, event in enumerate(sent):
        data, call_id = event['data'], event['call_id']
        intent, terminal = recorded[2*i:2*i+2]
        response, validation = responses.get(call_id), validations.get(call_id)
        identity = (data['stage'], data['provider'], data['model'], data['input_sha256'])
        if (intent.kind != 'intent' or intent.call_id != call_id or terminal.call_id != call_id
                or (intent.stage, intent.provider, intent.model, intent.input_sha256) != identity
                or (terminal.stage, terminal.provider, terminal.model, terminal.input_sha256) != identity
                or intent.payload.get('request_max_price') != data.get('max_price')):
            raise ContractError('incomplete fresh journal identity differs')
        if terminal.kind == 'receipt':
            if (not isinstance(response, dict) or not isinstance(validation, dict) or call_id in failures
                    or terminal.payload.get('raw_sha256') != response['body_sha256']
                    or terminal.payload.get('usage') != (response['usage'] or {})
                    or terminal.payload.get('http_status') != response['http_status']
                    or terminal.payload.get('metadata') != response['metadata']
                    or terminal.payload.get('note') != response['note']
                    or terminal.payload.get('validation') != (validation.get('failure') or 'ok')):
                raise ContractError('incomplete fresh receipt differs')
            failure = validation.get('failure')
            if failure is None:
                continue
            if data['stage'] not in ('judge_positive', 'judge_negative', 'plan_review'):
                raise ContractError('unsupported incomplete fresh stage')
            if failure in ('malformed_output', 'schema_violation'):
                outcome = 'malformed'
            elif failure == 'http_error':
                outcome = 'provider_failure'
            else:
                raise ContractError('unsupported incomplete fresh failure')
        elif terminal.kind in ('failure', 'uncertain'):
            if response is not None or validation is not None or data['stage'] not in ('judge_positive', 'judge_negative', 'plan_review'):
                raise ContractError('incomplete fresh failure differs')
            archived = failures.get(call_id)
            if terminal.kind == 'uncertain' and archived == {'failure':'uncertain_outcome'}:
                outcome = 'uncertain_outcome'
                uncertain.add(call_id)
            elif (terminal.kind == 'failure' and archived == {'failure':'provider_failure'}
                  and terminal.payload.get('error') == 'ProviderUnavailable'):
                outcome = 'provider_failure'
            else:
                raise ContractError('incomplete fresh terminal differs')
        else:
            raise ContractError('unsupported incomplete fresh terminal')
        outcomes.append({'call_id':call_id, 'stage':data['stage'], 'classification':outcome})
    results=[e['data'] for e in events if e['kind']=='run_result']
    review=results[0].get('review') if len(results)==1 else None
    no_call_review = (isinstance(review,dict) and review.get('status')=='unavailable'
                      and review.get('call_id') is None and review.get('review_id') is None
                      and isinstance(review.get('failure'),str) and bool(review['failure'])
                      and not any(e['data']['stage']=='plan_review' for e in sent))
    if (not outcomes and not no_call_review) or pending != uncertain - {r['call_id'] for r in reconciliations}:
        raise ContractError('fresh failure reconciliation state differs')
    classes = {item['classification'] for item in outcomes}
    classification = ('uncertain_outcome' if 'uncertain_outcome' in classes else
                      'provider_failure' if 'provider_failure' in classes else 'malformed' if classes else 'unknown_review')
    return {'case_id':reference['case_id'], 'run_sha256':run_hash, 'reference_sha256':ref_hash,
            'reference_provenance':reference['provenance'], 'classification':classification,
            'request_status':'deferred', 'request_answer':None, 'conditional_answer':None,
            'conditional_comparison':'unknown_review', 'reference_expected_answer':reference['expected_answer'],
            'required_evidence_covered':None, 'failures':outcomes, 'failure_verified':bool(outcomes),
            'review_status':'unavailable' if no_call_review else None,
            'review_failure':review['failure'] if no_call_review else None,
            'reconciliation_required':bool(pending), 'reconciliations':reconciliations,
            'semantic_assurance':'not_assessed'}


def _score_fresh_planner_failure(context, events, journal, reference, run_hash, ref_hash, recorded, reconciliations):
    """Check a planner-failure archive against its journal; never infer a result."""
    results = [e for e in events if e['kind'] == 'run_result']
    if len(results) != 1 or results[0]['data'].get('schema') != 'qjig.fresh-failure.v1':
        raise ContractError('incomplete fresh result is not a planner failure record')
    result = results[0]['data']
    request_id, calls, failure = context['request']['request_id'], result['call_ids'], result['failure']
    pending = bool(journal.pending(request_id))
    if result['reconciliation_required'] != (pending or bool(reconciliations)):
        raise ContractError('fresh failure reconciliation state changed')
    classification, verified = 'unknown_review', False
    if calls:
        # This bounded check refuses prior or reconciled calls rather than merging them.
        if len(calls) != 1 or len(recorded) != 2:
            raise ContractError('fresh failure journal has unexpected work')
        intent, terminal = recorded
        sent = [e for e in events if e['kind'] == 'request' and e['call_id'] == calls[0]]
        if len(sent) != 1:
            raise ContractError('fresh failure request missing')
        data = sent[0]['data']; identity = (data['stage'], data['provider'], data['model'], data['input_sha256'])
        if (intent.kind != 'intent' or intent.call_id != calls[0] or terminal.call_id != calls[0]
                or (intent.stage, intent.provider, intent.model, intent.input_sha256) != identity
                or (terminal.stage, terminal.provider, terminal.model, terminal.input_sha256) != identity
                or intent.payload.get('request_max_price') != data.get('max_price')):
            raise ContractError('fresh failure journal binding differs')
        if failure in ('uncertain_outcome', 'provider_unavailable'):
            if (failure == 'uncertain_outcome' and terminal.kind == 'uncertain' and (pending or any(r['call_id'] == terminal.call_id for r in reconciliations))):
                classification, verified = 'uncertain_outcome', True
            elif (failure == 'provider_unavailable' and terminal.kind == 'failure'
                  and terminal.payload.get('error') == 'ProviderUnavailable' and not pending):
                classification, verified = 'provider_failure', True
            else:
                raise ContractError('fresh failure terminal differs')
        else:
            responses = [e['data'] for e in events if e['kind'] == 'response' and e['call_id'] == calls[0]]
            validations = [e['data'] for e in events if e['kind'] == 'validation' and e['call_id'] == calls[0]]
            if len(responses) != 1 or len(validations) != 1:
                raise ContractError('fresh failure response missing')
            response, validation = responses[0], validations[0]
            if (terminal.kind != 'receipt' or validation.get('failure') != failure
                    or terminal.payload.get('validation') != failure or terminal.payload.get('raw_sha256') != response['body_sha256']
                    or terminal.payload.get('usage') != (response['usage'] or {})
                    or terminal.payload.get('http_status') != response['http_status']
                    or terminal.payload.get('metadata') != response['metadata'] or terminal.payload.get('note') != response['note']):
                raise ContractError('fresh failure receipt differs')
            if failure == 'malformed_output' or failure.startswith('plan_invalid:'):
                classification, verified = 'malformed', True
            elif failure == 'http_error':
                classification, verified = 'provider_failure', True
            # Validator errors remain unverified as to their cause.
    return {'case_id': reference['case_id'], 'run_sha256': run_hash, 'reference_sha256': ref_hash,
            'reference_provenance': reference['provenance'], 'classification': classification,
            'request_status': 'deferred', 'request_answer': None, 'conditional_answer': None,
            'conditional_comparison': 'unknown_review', 'reference_expected_answer': reference['expected_answer'],
            'required_evidence_covered': None,
            'failure_verified': verified, 'reconciliation_required': pending, 'reconciliations':reconciliations,
            'semantic_assurance': 'not_assessed'}


def summarize_fresh_intervention_pairs(design: dict, records: list[dict], *, expected_design_sha256: str) -> dict:
    """Compare fresh conditional graphs while explicitly retaining request deferrals.

    Scored records and arm mappings are caller assertions; conditional graph
    outcomes do not establish request-level answers or semantic correctness.
    """
    if not isinstance(records, list):
        raise ContractError('scored assignments must be a list')
    converted, original = [], {}
    answers = ('yes', 'no', 'unknown', 'conflict')
    for record in records:
        if not isinstance(record, dict) or set(record) != {'arm', 'repeat', 'score'} or not isinstance(record['score'], dict):
            raise ContractError('invalid fresh assignment')
        score = record['score']
        required = {'case_id', 'run_sha256', 'reference_sha256', 'reference_provenance', 'request_status',
                    'request_answer', 'conditional_answer', 'reference_expected_answer',
                    'required_evidence_covered', 'semantic_assurance'}
        if not required <= set(score):
            raise ContractError('fresh score is incomplete')
        conditional, expected, covered = (score.get('conditional_answer'), score.get('reference_expected_answer'),
                                           score.get('required_evidence_covered'))
        if (score.get('request_status') != 'deferred' or score.get('request_answer') is not None
                or score.get('semantic_assurance') != 'not_assessed' or expected not in answers
                or (conditional is not None and conditional not in answers)
                or (conditional is None and covered is not None)
                or (conditional is not None and type(covered) is not bool)):
            raise ContractError('fresh request and conditional graph differ')
        mapped = {'case_id':score.get('case_id'), 'run_sha256':score.get('run_sha256'),
                  'reference_sha256':score.get('reference_sha256'), 'reference_provenance':score.get('reference_provenance'),
                  'recorded_answer':conditional, 'reference_expected_answer':expected,
                  'required_evidence_covered':covered, 'answer_matches_reference':None if conditional is None else conditional == expected}
        converted.append({'arm':record['arm'], 'repeat':record['repeat'], 'score':mapped})
        key = (score.get('case_id'), record['arm'], record['repeat'])
        try:
            original[key] = score
        except TypeError as exc:
            raise ContractError('invalid fresh assignment identity') from exc
    report = summarize_intervention_pairs(design, converted, expected_design_sha256=expected_design_sha256)
    for pair in report['pairs']:
        parent = original.get((pair['parent_case'], pair['arm'], pair['repeat']))
        intervention = original.get((pair['intervention_case'], pair['arm'], pair['repeat']))
        pair['parent_request_status'] = parent['request_status'] if parent else None
        pair['intervention_request_status'] = intervention['request_status'] if intervention else None
        pair['parent_request_answer'] = None
        pair['intervention_request_answer'] = None
    report['comparison_scope'] = 'conditional_graph_only'
    return report


def score_reserved_assignment(goal, archive, journal, reference: dict, *, partition: str,
                              expected_plan_sha256: str, expected_run_sha256: str,
                              expected_reference_sha256: str, expected_journal_sha256: str | None = None,
                              original_run_only: bool = False) -> dict:
    """Score an archived assignment against an externally anchored reserved plan.

    This verifies structural bindings and ledger consistency, not source authority,
    independent labels, provider authenticity, or correctness of plan assumptions.
    """
    from .evaluation_budget import validate_assignment_binding, verify_evaluation_assignment
    from .goal_budget import GoalBudget
    from .journal import Journal
    from .run_archive import RunArchive
    if not isinstance(goal, GoalBudget) or not isinstance(journal, Journal) or not isinstance(archive, RunArchive):
        raise ContractError('goal ledger, journal and archive required')
    context = archive.context()
    if not isinstance(context, dict):
        raise ContractError('archive context required')
    assignment = context.get('evaluation_assignment')
    validate_assignment_binding(assignment)
    if (not isinstance(expected_plan_sha256, str) or not _SHA.fullmatch(expected_plan_sha256)
            or not hmac.compare_digest(assignment['plan_sha256'], expected_plan_sha256)):
        raise ContractError('evaluation plan anchor differs')
    schema = context.get('schema')
    if schema in ('qjig.direct-evaluation.v5', 'qjig.direct-evaluation.v6', 'qjig.direct-evaluation.v8'):
        case = context.get('case_binding')
        expected_arm = 'direct_retrieval' if schema.endswith('.v5') else 'direct_full_evidence' if schema.endswith('.v6') else 'retrieval_only'
        scorer = score_direct_archive
    elif schema == 'qjig.applicability-deferral.v1':
        from .evaluation_deferral import score_applicability_deferral
        case = context.get('case_binding')
        expected_arm = 'decomposition_only'
        scorer = score_applicability_deferral
    elif schema == 'qjig.fresh-context.v1':
        case = context.get('evaluation_case_binding')
        expected_arm = 'decomposition_only' if context.get('retrieval_method') == 'full_source_v1' else 'combined'
        scorer = score_fresh_archive
    else:
        raise ContractError('unsupported reserved evaluation archive')
    request = context.get('request')
    if (not isinstance(case, dict) or not isinstance(request, dict) or assignment['arm'] != expected_arm
            or not isinstance(partition, str) or not partition.strip()):
        raise ContractError('reserved evaluation context differs')
    try:
        verify_evaluation_assignment(goal, assignment, case_id=case['case_id'], case_sha256=case['case_sha256'],
                                     design_sha256=case['design_sha256'], request_id=request['request_id'], partition=partition)
    except KeyError as exc:
        raise ContractError('incomplete reserved evaluation context') from exc
    if goal.audit_journal(journal)['status'] != 'verified':
        raise ContractError('goal and journal accounting differ')
    if expected_journal_sha256 is not None and scorer is not score_fresh_archive:
        raise ContractError('this scoring path binds the journal in its run digest')
    if scorer is score_fresh_archive and expected_journal_sha256 is None:
        raise ContractError('fresh assignment resources require a journal anchor')
    if type(original_run_only) is not bool or (original_run_only and scorer not in (score_direct_archive, score_fresh_archive)):
        raise ContractError('original run prefix unsupported for this assignment')
    options = {'expected_journal_sha256':expected_journal_sha256} if scorer is score_fresh_archive else {}
    if original_run_only:
        options['original_run_only'] = True
    score = scorer(archive, journal, reference, expected_run_sha256=expected_run_sha256,
                   expected_reference_sha256=expected_reference_sha256, **options)
    from .costs import summarize_resources
    score['resources'] = summarize_resources(journal, request_id=request['request_id'])
    return {'arm':assignment['arm'], 'repeat':assignment['repeat'], 'score':score}




def unavailable_failure_review(goal,archive,journal,reference,review_archive,*,partition,expected_plan_sha256,
                               expected_run_sha256,expected_reference_sha256,reviewer_spec,
                               expected_journal_sha256=None,expected_review_sha256=None,record=False):
    """Bind a non-review to a verified failure with no unresolved paid attempt."""
    from .semantic_preflight import semantic_review_allocation
    from .run_archive import RunArchive
    if not isinstance(review_archive,RunArchive) or review_archive is archive or type(record) is not bool:
        raise ContractError('separate review archive required')
    score=score_reserved_assignment(goal,archive,journal,reference,partition=partition,
        expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256)
    result=score['score'];context=archive.context();rid=context['request']['request_id']
    settled_failure=(result.get('failure_verified') is True and result.get('classification') in ('malformed','provider_failure'))
    unavailable_review=(context.get('schema')=='qjig.fresh-context.v1' and result.get('classification')=='unknown_review'
                        and result.get('review_status')=='unavailable'
                        and result.get('review_failure')=='review_context_or_storage_error')
    if (not (settled_failure or unavailable_review) or result.get('reconciliation_required') is not False
            or result.get('recorded_answer') is not None or result.get('conditional_answer') is not None):
        raise ContractError('verified settled failure without an answer required')
    slot=semantic_review_allocation(request_id=rid,partition=partition,spec=reviewer_spec)
    assignment=context['evaluation_assignment']
    row=goal._con.execute('SELECT w.attempt_id FROM run_set_work s JOIN required_work w ON s.work_id=w.work_id '
        'WHERE s.set_id=? AND w.work_id=? AND w.request_id=?',
        ('evaluation:'+assignment['plan_id'],slot['work_id'],rid)).fetchone()
    if row is None or row[0] is not None or any(e.stage=='semantic_review' for e in journal.events(rid)):
        raise ContractError('unavailable review slot differs')
    saved={'schema':'qjig.semantic-review-failure.v1','request_id':rid,'reviewed_run_sha256':expected_run_sha256,
           'reference_sha256':expected_reference_sha256,'journal_sha256':expected_journal_sha256,
           'work_id':slot['work_id'],
           'reason':'original_review_unavailable' if unavailable_review else 'original_'+result['classification']}
    outcome={'assessment':'uncertain','assurance':'not_reviewed','reason':saved['reason']}
    if record:
        if (review_archive.events() or review_archive.revision_ids() or review_archive.source_ids()
                or review_archive._con.execute('SELECT COUNT(*) FROM run_context').fetchone()[0]):
            raise ContractError('unused review archive required')
        review_archive.record_context(saved);review_archive.record_run_result(rid,outcome)
    if review_archive.context()!=saved or review_archive.revision_ids() or review_archive.source_ids():
        raise ContractError('failure review binding differs')
    events=review_archive.events()
    if len(events)!=1 or events[0]['kind']!='run_result' or events[0]['call_id']!=rid or events[0]['data']!=outcome:
        raise ContractError('failure review record differs')
    raw=json.dumps({'context':saved,'events':events},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    digest=hashlib.sha256(raw).hexdigest()
    if expected_review_sha256 is not None and (not isinstance(expected_review_sha256,str)
            or not _SHA.fullmatch(expected_review_sha256) or not hmac.compare_digest(digest,expected_review_sha256)):
        raise ContractError('failure review digest differs')
    review={'status':'structurally_verified' if expected_review_sha256 else 'unanchored','sha256':digest,**outcome}
    return {**score,'review':review}


def score_reviewed_reserved_assignment(goal, archive, journal, reference: dict, review_archive, *,
                                       partition: str, expected_plan_sha256: str, expected_run_sha256: str,
                                       expected_reference_sha256: str, expected_review_sha256: str,
                                       reviewer_spec: dict, expected_journal_sha256: str | None = None) -> dict:
    """Bind an unvalidated review to a reserved assignment and its independently pinned digest."""
    from .evaluation_semantic_review import verify_direct_semantic_review, verify_fresh_semantic_review
    from .semantic_preflight import semantic_review_allocation
    from .run_archive import RunArchive
    if not isinstance(review_archive, RunArchive):
        raise ContractError('semantic review archive required')
    if not isinstance(expected_review_sha256, str) or not _SHA.fullmatch(expected_review_sha256):
        raise ContractError('semantic review anchor required')
    context = archive.context()
    request_id = context.get('request', {}).get('request_id')
    slot = semantic_review_allocation(request_id=request_id, partition=partition, spec=reviewer_spec)
    saved = review_archive.context()
    if isinstance(saved,dict) and saved.get('schema') == 'qjig.semantic-review-failure.v1':
        return unavailable_failure_review(goal,archive,journal,reference,review_archive,partition=partition,
            expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256,
            expected_review_sha256=expected_review_sha256,reviewer_spec=reviewer_spec)
    if context.get('schema') == 'qjig.applicability-deferral.v1':
        from .evaluation_semantic_review import verify_unavailable_applicability_review
        assignment=context['evaluation_assignment']
        row=goal._con.execute('SELECT w.attempt_id FROM run_set_work s JOIN required_work w ON s.work_id=w.work_id '
            'WHERE s.set_id=? AND w.work_id=? AND w.request_id=?',
            ('evaluation:'+assignment['plan_id'],slot['work_id'],request_id)).fetchone()
        if row is None or row[0] is not None:
            raise ContractError('unavailable review reserved work differs')
        review=verify_unavailable_applicability_review(archive,journal,review_archive,
            expected_run_sha256=expected_run_sha256,expected_reference_sha256=expected_reference_sha256,
            expected_review_sha256=expected_review_sha256,reviewer_spec=reviewer_spec,partition=partition)
        if review.get('status')!='structurally_verified':
            raise ContractError('unavailable review is not structurally verified')
        score=score_reserved_assignment(goal,archive,journal,reference,partition=partition,
            expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256)
        return {**score,'review':review}
    if (not isinstance(saved, dict) or saved.get('provider') != reviewer_spec['provider']
            or saved.get('model') != reviewer_spec['model']['id']
            or saved.get('max_tokens') != reviewer_spec['output_tokens']
            or saved.get('max_price') != reviewer_spec['max_price']
            or saved.get('route') != reviewer_spec.get('route')):
        raise ContractError('semantic reviewer configuration differs')
    assignment = context.get('evaluation_assignment', {})
    row = goal._con.execute("SELECT w.attempt_id FROM run_set_work s JOIN required_work w ON s.work_id=w.work_id "
                            "WHERE s.set_id=? AND w.work_id=? AND w.request_id=?",
                            ('evaluation:'+assignment.get('plan_id',''),slot['work_id'],request_id)).fetchone()
    intents = [e for e in journal.events(request_id) if e.kind == 'intent' and e.stage == 'semantic_review']
    if (row is None or row[0] is None or len(intents) != 1 or intents[0].payload.get('goal_attempt_id') != row[0]
            or intents[0].payload.get('required_id') != slot['work_id']
            or intents[0].payload.get('work_binding_sha256') != slot['work_binding_sha256']):
        raise ContractError('semantic review reserved work differs')
    if context.get('schema') == 'qjig.fresh-context.v1':
        review = verify_fresh_semantic_review(archive,journal,review_archive,reference=reference,
            expected_reference_sha256=expected_reference_sha256,expected_run_sha256=expected_run_sha256,
            expected_journal_sha256=expected_journal_sha256,expected_review_sha256=expected_review_sha256)
    else:
        review = verify_direct_semantic_review(archive,journal,review_archive,expected_run_sha256=expected_run_sha256,
                                               expected_review_sha256=expected_review_sha256)
    if review.get('status') != 'structurally_verified':
        raise ContractError('semantic review is not structurally verified')
    score = score_reserved_assignment(goal,archive,journal,reference,partition=partition,
        expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_journal_sha256=expected_journal_sha256,
        original_run_only=True)
    return {**score,'review':review}




def unavailable_outcome_review(goal, archive, journal, reference: dict, review_archive, outcome_archive, *,
                               partition: str, expected_plan_sha256: str, expected_run_sha256: str,
                               expected_reference_sha256: str, expected_review_sha256: str, reviewer_spec: dict,
                               outcome_reviewer_spec: dict, expected_journal_sha256: str | None = None,
                               expected_outcome_review_sha256: str | None = None, record: bool = False) -> dict:
    """Record a non-review for an anchored deferral, settled failure or unavailable review."""
    from .outcome_preflight import outcome_review_allocation
    from .run_archive import RunArchive
    if (not isinstance(outcome_archive,RunArchive) or outcome_archive is archive or outcome_archive is review_archive
            or type(record) is not bool):
        raise ContractError('separate outcome archive required')
    result=score_reviewed_reserved_assignment(goal,archive,journal,reference,review_archive,partition=partition,
        expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_review_sha256=expected_review_sha256,
        reviewer_spec=reviewer_spec,expected_journal_sha256=expected_journal_sha256)
    context=archive.context(); request_id=context['request']['request_id']; assignment=context['evaluation_assignment']
    score=result['score']
    applicability=(context.get('schema')=='qjig.applicability-deferral.v1' and not journal.events(request_id)
                   and score.get('request_status')=='deferred')
    settled=(score.get('failure_verified') is True and score.get('classification') in ('malformed','provider_failure')
             and score.get('reconciliation_required') is False and not journal.pending(request_id)
             and score.get('recorded_answer') is None and score.get('conditional_answer') is None
             and not any(e.stage=='outcome_review' for e in journal.events(request_id)))
    unavailable=(context.get('schema')=='qjig.fresh-context.v1' and score.get('classification')=='unknown_review'
                 and score.get('review_status')=='unavailable' and score.get('review_failure')=='review_context_or_storage_error'
                 and score.get('reconciliation_required') is False and not journal.pending(request_id)
                 and score.get('conditional_answer') is None and not any(e.stage=='outcome_review' for e in journal.events(request_id)))
    if result['review'].get('assurance')!='not_reviewed' or not (applicability or settled or unavailable):
        raise ContractError('eligible deferral, settled failure or unavailable review required')
    slot=outcome_review_allocation(request_id=request_id,partition=partition,spec=outcome_reviewer_spec)
    row=goal._con.execute("SELECT w.attempt_id FROM run_set_work s JOIN required_work w ON s.work_id=w.work_id "
        "WHERE s.set_id=? AND w.work_id=? AND w.request_id=?",
        ('evaluation:'+assignment['plan_id'],slot['work_id'],request_id)).fetchone()
    if row is None or row[0] is not None:
        raise ContractError('unavailable outcome review slot differs')
    saved={'schema':'qjig.outcome-review-unavailable.v1','reviewed_run_sha256':expected_run_sha256,
           'reference_sha256':expected_reference_sha256,'semantic_review_sha256':expected_review_sha256,
           'request_id':request_id,'work_id':slot['work_id'],
           'reason':'source_applicability_unestablished' if applicability else 'original_review_unavailable' if unavailable else 'original_'+score['classification'],
           **({'journal_sha256':expected_journal_sha256} if settled or unavailable else {})}
    outcome={'assessment':'uncertain','assurance':'not_reviewed','reason':saved['reason']}
    if record:
        if (outcome_archive.events() or outcome_archive.revision_ids() or outcome_archive.source_ids()
                or outcome_archive._con.execute('SELECT COUNT(*) FROM run_context').fetchone()[0]):
            raise ContractError('unused outcome archive required')
        outcome_archive.record_context(saved);outcome_archive.record_run_result(request_id,outcome)
    if outcome_archive.context()!=saved or outcome_archive.revision_ids() or outcome_archive.source_ids():
        raise ContractError('unavailable outcome review binding differs')
    events=outcome_archive.events()
    if len(events)!=1 or events[0]['kind']!='run_result' or events[0]['call_id']!=request_id or events[0]['data']!=outcome:
        raise ContractError('unavailable outcome review record differs')
    raw=json.dumps({'context':saved,'events':events},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    digest=hashlib.sha256(raw).hexdigest()
    if expected_outcome_review_sha256 is not None and (not isinstance(expected_outcome_review_sha256,str)
            or not _SHA.fullmatch(expected_outcome_review_sha256) or not hmac.compare_digest(digest,expected_outcome_review_sha256)):
        raise ContractError('outcome review digest differs')
    review={'status':'structurally_verified' if expected_outcome_review_sha256 else 'unanchored','sha256':digest,**outcome}
    return {**result,'outcome_review':review,'outcome_category':'failed' if settled else 'unknown_assessment','outcome_assurance':'not_reviewed'}

def score_outcome_reviewed_assignment(goal, archive, journal, reference: dict, review_archive, outcome_archive, *,
                                      partition: str, expected_plan_sha256: str, expected_run_sha256: str,
                                      expected_reference_sha256: str, expected_review_sha256: str,
                                      reviewer_spec: dict, expected_outcome_review_sha256: str,
                                      outcome_reviewer_spec: dict, expected_journal_sha256: str | None = None) -> dict:
    """Bind both reviews to reserved work; classify only reference-relative, unvalidated outcomes."""
    from .evaluation_outcome_review import verify_direct_outcome_review, verify_fresh_outcome_review
    from .outcome_preflight import outcome_review_allocation
    from .run_archive import RunArchive
    if not isinstance(outcome_archive,RunArchive) or not isinstance(expected_outcome_review_sha256,str) or not _SHA.fullmatch(expected_outcome_review_sha256):
        raise ContractError('anchored outcome review archive required')
    saved_outcome=outcome_archive.context()
    if isinstance(saved_outcome,dict) and saved_outcome.get('schema')=='qjig.outcome-review-unavailable.v1':
        return unavailable_outcome_review(goal,archive,journal,reference,review_archive,outcome_archive,
            partition=partition,expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
            expected_reference_sha256=expected_reference_sha256,expected_review_sha256=expected_review_sha256,
            reviewer_spec=reviewer_spec,outcome_reviewer_spec=outcome_reviewer_spec,
            expected_journal_sha256=expected_journal_sha256,expected_outcome_review_sha256=expected_outcome_review_sha256)
    result=score_reviewed_reserved_assignment(goal,archive,journal,reference,review_archive,partition=partition,
        expected_plan_sha256=expected_plan_sha256,expected_run_sha256=expected_run_sha256,
        expected_reference_sha256=expected_reference_sha256,expected_review_sha256=expected_review_sha256,
        reviewer_spec=reviewer_spec,expected_journal_sha256=expected_journal_sha256)
    context=archive.context(); request_id=context['request']['request_id']; saved=outcome_archive.context()
    slot=outcome_review_allocation(request_id=request_id,partition=partition,spec=outcome_reviewer_spec)
    if (not isinstance(saved,dict) or saved.get('provider')!=outcome_reviewer_spec['provider']
            or saved.get('model')!=outcome_reviewer_spec['model']['id']
            or saved.get('max_tokens')!=outcome_reviewer_spec['output_tokens']
            or saved.get('max_price')!=outcome_reviewer_spec['max_price']
            or saved.get('route')!=outcome_reviewer_spec.get('route')):
        raise ContractError('outcome reviewer configuration differs')
    assignment=context['evaluation_assignment']
    row=goal._con.execute("SELECT w.attempt_id FROM run_set_work s JOIN required_work w ON s.work_id=w.work_id "
        "WHERE s.set_id=? AND w.work_id=? AND w.request_id=?",
        ('evaluation:'+assignment['plan_id'],slot['work_id'],request_id)).fetchone()
    intents=[e for e in journal.events(request_id) if e.kind=='intent' and e.stage=='outcome_review']
    if (row is None or row[0] is None or len(intents)!=1 or intents[0].payload.get('goal_attempt_id')!=row[0]
            or intents[0].payload.get('required_id')!=slot['work_id']
            or intents[0].payload.get('work_binding_sha256')!=slot['work_binding_sha256']):
        raise ContractError('outcome review reserved work differs')
    if context.get('schema')=='qjig.fresh-context.v1':
        review=verify_fresh_outcome_review(archive,journal,outcome_archive,reference=reference,
            expected_reference_sha256=expected_reference_sha256,expected_run_sha256=expected_run_sha256,
            expected_journal_sha256=expected_journal_sha256,expected_review_sha256=expected_outcome_review_sha256)
    else:
        review=verify_direct_outcome_review(archive,journal,outcome_archive,expected_run_sha256=expected_run_sha256,
                                             expected_review_sha256=expected_outcome_review_sha256)
    if review.get('status')!='structurally_verified':
        raise ContractError('outcome review is not structurally verified')
    score=result['score']; expected=score['reference_expected_answer']; assessed=review['assessment']
    category='unknown_assessment'
    citations=review.get('citations',[]); required=reference['evidence']
    review_covers_reference=bool(required) and all(any(c['revision_id']==item['revision_id'] and item['quote'] in c['quote']
        for c in citations) for item in required)
    if review.get('evidence_checked') is True and review_covers_reference and assessed==expected:
        actual=score.get('recorded_answer') if 'recorded_answer' in score else score.get('request_answer')
        if expected=='unknown' and actual in (None,'unknown'):
            category='supported_match'
        elif expected in ('yes','no','conflict') and actual!=expected:
            category='reference_misaligned'
        elif expected in ('yes','no','conflict') and result['review']['assessment']=='supported' and score.get('required_evidence_covered') is True:
            category='supported_match'
    return {**result,'outcome_review':review,'outcome_category':category,'outcome_assurance':review['assurance']}

def summarize_holdout_comparison(design: dict, records: list[dict], *, expected_design_sha256: str,
                                 baseline_arm: str, candidate_arm: str) -> dict:
    """Pair request-level mechanical scores; records and arm mappings are caller assertions.

    Conditional fresh graph answers do not count as request answers. This does
    not authenticate source authority, semantic relevance, or reference labels.
    """
    from .evaluation import validate_evaluation_design
    if not isinstance(expected_design_sha256, str) or not _SHA.fullmatch(expected_design_sha256):
        raise ContractError('design anchor required')
    validate_evaluation_design(design, expected_digest=expected_design_sha256)
    arms = {'direct_full_evidence', 'direct_retrieval', 'retrieval_only', 'decomposition_only', 'combined'}
    if (baseline_arm not in arms or candidate_arm not in arms or baseline_arm == candidate_arm
            or not isinstance(records, list)):
        raise ContractError('unsupported holdout comparison')
    families = {f['id']:f['partition'] for f in design['families']}
    cases = {c['id'] for c in design['cases'] if families[c['family']] == 'holdout'}
    repeats = design['repeats']['holdout']
    if len(cases) * repeats > 100_000:
        raise ContractError('holdout comparison exceeds limit')
    indexed, references, run_ids = {}, {}, set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {'arm','repeat','score'} or not isinstance(record['score'], dict):
            raise ContractError('invalid holdout score')
        arm, repeat, score = record['arm'], record['repeat'], record['score']
        case = score.get('case_id'); run_id = score.get('run_sha256'); ref = score.get('reference_sha256')
        expected, provenance = score.get('reference_expected_answer'), score.get('reference_provenance')
        if (arm not in (baseline_arm,candidate_arm) or not isinstance(case,str) or case not in cases
                or type(repeat) is not int or not 1 <= repeat <= repeats
                or not isinstance(run_id,str) or not _SHA.fullmatch(run_id) or run_id in run_ids
                or not isinstance(ref,str) or not _SHA.fullmatch(ref)
                or expected not in ('yes','no','unknown','conflict')
                or provenance not in ('authored_unvalidated','ai_reviewed_unvalidated')
                or score.get('semantic_assurance') != 'not_assessed'):
            raise ContractError('invalid holdout score identity')
        key = (case,repeat,arm)
        if key in indexed or (case in references and references[case] != (ref,expected,provenance)):
            raise ContractError('duplicate assignment or changed reference')
        references[case] = (ref,expected,provenance); run_ids.add(run_id)
        if arm in ('combined', 'decomposition_only'):
            if score.get('request_status') != 'deferred' or 'request_answer' not in score or score['request_answer'] is not None:
                raise ContractError('invalid fresh request result')
            status = 'unknown'
        else:
            if 'recorded_answer' not in score or 'required_evidence_covered' not in score or 'answer_matches_reference' not in score:
                raise ContractError('incomplete direct score')
            answer, covered, matched = score['recorded_answer'], score['required_evidence_covered'], score['answer_matches_reference']
            if (answer not in ('yes','no','unknown','conflict',None) or type(covered) not in (bool,type(None))
                    or type(matched) not in (bool,type(None))
                    or (answer is None and (covered is not None or matched is not None))
                    or (answer is not None and (type(covered) is not bool or matched is not (answer == expected)))):
                raise ContractError('invalid direct outcome')
            status = 'unknown' if answer is None or not covered else 'reference_match' if matched else 'reference_mismatch'
        indexed[key] = status
    pairs = []
    for case in sorted(cases):
        for repeat in range(1,repeats+1):
            before = indexed.get((case,repeat,baseline_arm)); after = indexed.get((case,repeat,candidate_arm))
            pairs.append({'case_id':case,'repeat':repeat,'baseline_status':before or 'missing',
                          'candidate_status':after or 'missing'})
    total = len(pairs)
    recorded = sum(p['baseline_status'] != 'missing' and p['candidate_status'] != 'missing' for p in pairs)
    def count(side,status): return sum(p[side+'_status'] == status for p in pairs)
    def rate(side):
        return count(side,'reference_match') / total if total and count(side,'unknown') == 0 and count(side,'missing') == 0 else None
    base_rate, candidate_rate = rate('baseline'), rate('candidate')
    return {'schema':'qjig.holdout-comparison.v2','design_sha256':expected_design_sha256,'baseline_arm':baseline_arm,'candidate_arm':candidate_arm,
            'assigned_pairs':total,'recorded_pairs':recorded,'missing_pairs':total-recorded,
            'baseline_reference_matches':count('baseline','reference_match'),'candidate_reference_matches':count('candidate','reference_match'),
            'baseline_unknown':count('baseline','unknown'),'candidate_unknown':count('candidate','unknown'),
            'baseline_mechanical_match_rate':base_rate,'candidate_mechanical_match_rate':candidate_rate,
            'paired_mechanical_difference':None if base_rate is None or candidate_rate is None else candidate_rate-base_rate,
            'outcome_support':None,
            'pairs':pairs,'semantic_assurance':'not_assessed'}


def build_reserved_holdout_comparison(goal, design: dict, entries: list[dict], *, plan_id: str,
                                      expected_plan_sha256: str, expected_design_sha256: str,
                                      baseline_arm: str, candidate_arm: str,
                                      expected_config_sha256: str | None = None) -> dict:
    """Rebuild paired holdout scores from pinned archives and a persisted plan.

    Input anchors, source authority, the journal's quiescence and reference truth
    remain external assertions. This makes no provider call or semantic judgment.
    """
    from .evaluation_budget import make_evaluation_plan, validate_assignment_binding
    from .goal_budget import GoalBudget
    if not isinstance(goal, GoalBudget) or not isinstance(entries, list):
        raise ContractError('goal ledger and archive entries required')
    validate_assignment_binding({'plan_id':plan_id,'plan_sha256':expected_plan_sha256,'arm':'combined','repeat':1})
    row = goal._con.execute('SELECT set_id,manifest,sha256 FROM evaluation_plans WHERE plan_id=?',(plan_id,)).fetchone()
    if row is None:
        raise ContractError('evaluation plan unavailable')
    set_id, encoded, digest = row
    if (set_id != 'evaluation:'+plan_id or not hmac.compare_digest(digest,expected_plan_sha256)
            or hashlib.sha256(encoded.encode('utf-8')).hexdigest() != digest):
        raise ContractError('evaluation plan anchor differs')
    try:
        manifest = json.loads(encoded)
        rebuilt = make_evaluation_plan(manifest['design'],manifest['case_hashes'],manifest['stage_templates'],
                                       manifest['assignments'],expected_design_sha256=manifest['design_sha256'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ContractError('evaluation plan invalid') from exc
    if (rebuilt['sha256'] != digest or rebuilt['manifest'] != manifest or manifest['design'] != design
            or manifest['design_sha256'] != expected_design_sha256):
        raise ContractError('evaluation design differs')
    frozen = goal._con.execute('SELECT manifest,sha256 FROM run_sets WHERE set_id=?',(set_id,)).fetchone()
    if frozen is None:
        raise ContractError('evaluation run set unavailable')
    goal._verify_run_set(set_id,*frozen)
    config_row = None
    if goal._con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='evaluation_campaign_config'").fetchone():
        config_row=goal._con.execute('SELECT value,sha256 FROM evaluation_campaign_config WHERE plan_id=?',(plan_id,)).fetchone()
    config=None
    if config_row is not None:
        config_value,config_hash=config_row
        if hashlib.sha256(config_value.encode('utf-8')).hexdigest()!=config_hash:
            raise ContractError('campaign configuration integrity differs')
        config=json.loads(config_value)
    has_semantic=any('semantic_review' in template for template in manifest['stage_templates'].values())
    outcome_enabled=config is not None and config.get('schema')=='qjig.campaign-config.v7'
    semantic=config is not None and config.get('schema') in ('qjig.campaign-config.v4','qjig.campaign-config.v5','qjig.campaign-config.v6','qjig.campaign-config.v7')
    if (has_semantic and config is not None and not semantic) or (semantic and (not has_semantic
            or not isinstance(expected_config_sha256,str) or not _SHA.fullmatch(expected_config_sha256)
            or not hmac.compare_digest(config_row[1],expected_config_sha256))):
        raise ContractError('semantic campaign configuration anchor required')
    records = []
    reviews = []
    outcome_records = []
    for entry in entries:
        entry_keys={'archive','journal','reference','run_sha256','reference_sha256','journal_sha256'}
        if not isinstance(entry,dict) or set(entry) != (entry_keys | ({'review_archive','review_sha256'} if semantic else set()) | ({'outcome_archive','outcome_sha256'} if outcome_enabled else set())):
            raise ContractError('invalid holdout archive entry')
        archive = entry['archive']
        try:
            assignment = archive.context()['evaluation_assignment']
        except (AttributeError,KeyError,TypeError) as exc:
            raise ContractError('holdout archive assignment unavailable') from exc
        validate_assignment_binding(assignment)
        if assignment['plan_id'] != plan_id or assignment['plan_sha256'] != digest:
            raise ContractError('holdout archive plan differs')
        options=dict(partition='holdout',expected_plan_sha256=digest,expected_run_sha256=entry['run_sha256'],
                     expected_reference_sha256=entry['reference_sha256'],expected_journal_sha256=entry['journal_sha256'])
        if semantic:
            from .evaluation_campaign import check_archive_config
            rid=archive.context()['request']['request_id']
            assigned=next((a for a in manifest['assignments'] if a['request_id']==rid),None)
            if assigned is None:
                raise ContractError('campaign assignment unavailable')
            check_archive_config(config,archive.context(),assigned)
            if outcome_enabled:
                record=score_outcome_reviewed_assignment(goal,archive,entry['journal'],entry['reference'],entry['review_archive'],entry['outcome_archive'],
                    expected_review_sha256=entry['review_sha256'],reviewer_spec=config['stages']['semantic_reviewer'],
                    expected_outcome_review_sha256=entry['outcome_sha256'],outcome_reviewer_spec=config['stages']['outcome_reviewer'],**options)
                outcome_records.append({'case_id':record['score']['case_id'],'repeat':record['repeat'],'arm':record['arm'],
                                        'category':record['outcome_category'],'assurance':record['outcome_assurance']})
            else:
                record=score_reviewed_reserved_assignment(goal,archive,entry['journal'],entry['reference'],entry['review_archive'],
                    expected_review_sha256=entry['review_sha256'],reviewer_spec=config['stages']['semantic_reviewer'],**options)
            row=goal._con.execute("SELECT payload FROM evaluation_campaign_events WHERE plan_id=? AND request_id=? AND kind='scored'",(plan_id,rid)).fetchone()
            if row is None:
                raise ContractError('campaign score receipt unavailable')
            receipt=json.loads(row[0])
            encoded_score=json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
            if ((outcome_enabled and receipt.get('outcome_review_sha256')!=entry['outcome_sha256'])
                    or receipt.get('semantic_review_sha256')!=entry['review_sha256'] or receipt.get('run_sha256')!=entry['run_sha256']
                    or receipt.get('reference_sha256')!=entry['reference_sha256'] or receipt.get('journal_sha256')!=entry['journal_sha256']
                    or receipt.get('score_sha256')!=hashlib.sha256(encoded_score).hexdigest()):
                raise ContractError('campaign score receipt differs')
            reviews.append({**record['review'],'arm':record['arm'],'repeat':record['repeat'],
                            'case_id':record['score']['case_id'],'run_sha256':record['score']['run_sha256']})
            records.append({k:record[k] for k in ('arm','repeat','score')})
        else:
            records.append(score_reserved_assignment(goal,archive,entry['journal'],entry['reference'],**options))
    report = summarize_holdout_comparison(design,records,expected_design_sha256=expected_design_sha256,
                                          baseline_arm=baseline_arm,candidate_arm=candidate_arm)
    report['plan_sha256'] = digest
    report['scored_assignments'] = records
    if semantic:
        review_index={(review['case_id'],review['repeat'],review['arm']):review for review in reviews}
        def review_side(case, repeat, arm):
            review=review_index.get((case,repeat,arm))
            if review is None:
                return None
            scope=('not_reviewed' if review['assurance']=='not_reviewed' else
                   'conditional_graph' if arm in ('combined','decomposition_only') else 'request_answer')
            return {'assessment':review['assessment'],'assurance':review['assurance'],'scope':scope}
        review_pairs=[{'case_id':pair['case_id'],'repeat':pair['repeat'],
                       'baseline':review_side(pair['case_id'],pair['repeat'],baseline_arm),
                       'candidate':review_side(pair['case_id'],pair['repeat'],candidate_arm)} for pair in report['pairs']]
        report['semantic_reviews']={'assurance':'unvalidated',
            **{name:sum(review['assessment']==name for review in reviews) for name in ('supported','unsupported','uncertain')},
            'not_reviewed':sum(review['assurance']=='not_reviewed' for review in reviews),
            'records':reviews,'pairs':review_pairs}
    if outcome_enabled:
        by_key={(r['case_id'],r['repeat'],r['arm']):r['category'] for r in outcome_records}
        outcome_pairs=[]
        for pair in report['pairs']:
            key=(pair['case_id'],pair['repeat'])
            before=by_key.get((*key,baseline_arm));after=by_key.get((*key,candidate_arm))
            if before is not None and after is not None:
                outcome_pairs.append({'case_id':key[0],'repeat':key[1],'baseline':before,'candidate':after})
        if baseline_arm in ('direct_full_evidence','direct_retrieval') and candidate_arm=='combined':
            paired=summarize_paired_outcome_assertions(design,outcome_pairs,expected_design_sha256=expected_design_sha256,
                                                       baseline_arm=baseline_arm,candidate_arm=candidate_arm)
            paired['assurance']='structurally_verified_unvalidated'
            report['outcome_support']=paired['outcome_support']
        else:
            paired=None
        report['outcome_reviews']={'records':outcome_records,'paired':paired}
    return report


def summarize_paired_outcome_assertions(design: dict, records: list[dict], *, expected_design_sha256: str,
                                        baseline_arm: str, candidate_arm: str) -> dict:
    """Apply draft pair arithmetic to caller assertions, never to an unverified decision.

    This function does not inspect receipts, perform outcome review, or establish
    the truth of categories. Missing and unknown pairs prevent a numeric metric.
    """
    from .evaluation import validate_evaluation_design
    if not isinstance(expected_design_sha256,str) or not _SHA.fullmatch(expected_design_sha256):
        raise ContractError('design anchor required')
    validate_evaluation_design(design,expected_digest=expected_design_sha256)
    if (baseline_arm not in ('direct_full_evidence','direct_retrieval') or candidate_arm != 'combined'
            or not isinstance(records,list)):
        raise ContractError('unsupported paired comparison')
    partition={family['id']:family['partition'] for family in design['families']}
    cases=sorted(case['id'] for case in design['cases'] if partition[case['family']]=='holdout')
    repeats=design['repeats']['holdout']
    if len(cases)*repeats>100_000:
        raise ContractError('holdout comparison exceeds limit')
    possible={(case,repeat) for case in cases for repeat in range(1,repeats+1)}
    ranks={'supported_match':2,'reference_misaligned':1,'failed':0}
    categories=set(ranks)|{'unknown_assessment'}
    indexed={}
    for record in records:
        if not isinstance(record,dict) or set(record)!={'case_id','repeat','baseline','candidate'}:
            raise ContractError('invalid paired outcome record')
        case,repeat=record['case_id'],record['repeat']
        if (not isinstance(case,str) or type(repeat) is not int or (case,repeat) not in possible
                or not isinstance(record['baseline'],str) or record['baseline'] not in categories
                or not isinstance(record['candidate'],str) or record['candidate'] not in categories
                or (case,repeat) in indexed):
            raise ContractError('invalid or duplicate paired outcome')
        indexed[(case,repeat)]=record
    pairs=[]; points=0; unknown=0; missing=0
    for case,repeat in sorted(possible):
        record=indexed.get((case,repeat))
        if record is None:
            missing+=1
            pairs.append({'case_id':case,'repeat':repeat,'baseline':None,'candidate':None,'points':None})
            continue
        before,after=record['baseline'],record['candidate']
        if before=='unknown_assessment' or after=='unknown_assessment':
            unknown+=1; value=None
        else:
            value=1 if ranks[after]>ranks[before] else 0.5 if ranks[after]==ranks[before] else 0
            points+=value
        pairs.append({'case_id':case,'repeat':repeat,'baseline':before,'candidate':after,'points':value})
    total=len(pairs)
    return {'schema':'qjig.paired-outcome-assertions.v1','design_sha256':expected_design_sha256,
            'baseline_arm':baseline_arm,'candidate_arm':candidate_arm,'assigned_pairs':total,
            'recorded_pairs':len(indexed),'missing_pairs':missing,'unknown_pairs':unknown,
            'outcome_support':points/total if total and not missing and not unknown else None,
            'pairs':pairs,'assurance':'caller_asserted_unverified','decision':None}
