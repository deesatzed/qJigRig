"""Structural archive checks without inference or claims of semantic correctness."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .acquisition import COVERAGE_ID
from .applicability import Applicability, ApplicabilityInputs, combine_applicability, scope_applicability
from .contracts import ContractError, Request
from .judge import SIDE_SCHEMA, _PROMPT, _combine_sides, _side_from_value
from .packets import EvidencePacket, PacketItem
from .planner import _plan_validator, _planner_prompt, corpus_manifest_sha256
from .plans import parse_plan
from .providers import ProviderRequest, _validate
from .program_review import _REVIEW_SCHEMA, _review_prompt
from .programs import make_draft, verify_review
from .run_archive import RunArchive
from .spans import Span, verify_span


@dataclass(frozen=True)
class ReplayReport:
    status: str  # structurally_verified | unanchored | incomplete | invalid
    digest: str | None
    issues: tuple[str, ...]
    checked_requests: int
    checked_responses: int
    checked_traces: int
    semantic_assurance: str = "not_assessed"


def _check_review(record, call_id, request, response, validation, context, plan):
    if plan is None or validation.get('failure') is not None or validation.get('value') is None:
        raise ContractError('review has no validated response or plan')
    payload = record['payload']
    binding, actor = payload['binding'], payload['reviewer']
    if verify_review(record, binding, actor)['status'] != 'matching_unvalidated':
        raise ContractError('invalid review record')
    inputs = ApplicabilityInputs.from_dict(context['applicability_inputs'])
    members = {row['revision_id']: {k: v for k, v in row.items() if k != 'revision_id'} for row in inputs.to_dict()['members']}
    ids = sorted(context['corpus'])
    planner = context['planner']
    planner_prompt = _planner_prompt(Request.from_dict(context['request']), corpus_manifest_sha256(ids), context['planning_evidence'])
    expected = {'request': context['request'], 'plan': {'origin': plan.origin,
                'predicates': [{'id': p.id, 'question': p.question, 'depends_on': list(p.depends_on),
                                **({'exact_operator': p.exact_operator} if p.exact_operator is not None else {})}
                               for p in plan.predicates], 'expression': plan.expression},
                'corpus_revision_ids': ids, 'source_metadata': {ident: members[ident] for ident in ids},
                'as_of': inputs.as_of, 'entities': sorted(inputs.request_entities),
                'historical_as_known': inputs.historical_as_known,
                'planner': {'provider': planner['provider'], 'model': planner['model'],
                            'prompt_sha256': hashlib.sha256(planner_prompt.encode('utf-8')).hexdigest(),
                            'config': {'max_tokens': planner['max_tokens'], 'max_price': planner.get('max_price')}}}
    settings = context['reviewer']
    prompt_version = settings.get('prompt_version')
    if prompt_version not in (None, 'request_id_redacted_v2'):
        raise ContractError('unknown review prompt version')
    if binding != expected or request.prompt != _review_prompt(binding, context['planning_evidence']['packet'], legacy_request_id=prompt_version is None):
        raise ContractError('review inputs differ from plan or prompt')
    expected_kind = {'STAND_IN: authored responses, not a model': 'synthetic',
                     'LIVE: openrouter, real model call': 'ai'}.get(context['transport'])
    if (expected_kind is None or actor != {'kind': expected_kind, 'provider': settings['provider'], 'model': settings['model'],
            'prompt_sha256': hashlib.sha256(request.prompt.encode('utf-8')).hexdigest(),
            'config': {'max_tokens': settings['max_tokens'], 'max_price': settings.get('max_price'),
                       **({'prompt_version': prompt_version} if prompt_version is not None else {})}}):
        raise ContractError('reviewer provenance differs')
    expected_result = {**validation['value'], 'call_id': call_id, 'raw_sha256': response['body_sha256'], 'usage': response['usage']}
    if payload['result'] != expected_result:
        raise ContractError('review result differs from response')


def verify_archive(archive: RunArchive, *, expected_digest: str | None = None) -> ReplayReport:
    """Validate saved structure and optionally compare to an externally saved digest.

    A digest detects changes relative to the supplied anchor; it does not authenticate
    the archive, prove source authority, or establish a model's semantic correctness.
    """
    issues = []
    incomplete = []
    try:
        context = archive.context()
        events = archive.events()
        if context.get("schema") != "qjig.fresh-context.v1" or not isinstance(context.get("corpus"), dict):
            raise ContractError("unsupported or missing context schema")
        if 'evaluation_case_binding' in context:
            import re
            b = context['evaluation_case_binding']
            if (not isinstance(b, dict) or set(b) != {'case_id', 'design_sha256', 'case_sha256', 'reference_sha256'}
                    or not isinstance(b['case_id'], str) or not b['case_id'].strip()
                    or any(not isinstance(b[k], str) or not re.fullmatch(r'[0-9a-f]{64}', b[k])
                           for k in ('design_sha256', 'case_sha256', 'reference_sha256'))):
                raise ContractError('invalid evaluation case binding')
        revisions = {revision_id: archive.revision(revision_id) for revision_id in archive.revision_ids()}
        if set(revisions) != set(context["corpus"]):
            raise ContractError("corpus revision set differs from context")
        sources = {source_id: hashlib.sha256(archive.source(source_id)).hexdigest() for source_id in archive.source_ids()}
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        return ReplayReport("invalid", None, (f"archive_structure:{type(exc).__name__}",), 0, 0, 0)
    try:
        inputs = context.get("applicability_inputs")
        if context.get("applicability_provenance") != "recorded_inputs" or inputs is None:
            incomplete.append("applicability_inputs_unavailable")
        else:
            reconstructed = ApplicabilityInputs.from_dict(inputs)
            recorded_entity_date = context.get("entity_date_verdicts", context["corpus"])
            if set(recorded_entity_date) != set(context["corpus"]) or any(
                reconstructed.verdict(key).value != value for key, value in recorded_entity_date.items()
            ):
                raise ContractError("entity/date applicability verdict mismatch")
        if context.get("scope_policy") == "exact_nonempty_v1":
            source_scopes = context["source_scopes"]
            scope_verdicts = context["scope_verdicts"]
            entity_date = context["entity_date_verdicts"]
            ids = set(context["corpus"])
            if any(not isinstance(mapping, dict) or set(mapping) != ids for mapping in (source_scopes, scope_verdicts, entity_date)):
                raise ContractError("scope binding set mismatch")
            request_scope = Request.from_dict(context["request"]).scope
            for key in ids:
                scope = scope_applicability(request_scope, source_scopes[key])
                if scope.value != scope_verdicts[key] or combine_applicability(scope, Applicability(entity_date[key])).value != context["corpus"][key]:
                    raise ContractError("scope applicability mismatch")
            if inputs is not None:
                for member in reconstructed.collection.members:
                    if member.revision_id in ids and source_scopes[member.revision_id] is not None and source_scopes[member.revision_id] != member.scope:
                        raise ContractError("source scope contradicts applicability inputs")
        else:
            incomplete.append("scope_provenance_unavailable")
        planning = context.get("planning_evidence")
        if not isinstance(planning, dict) or planning.get("schema") != "qjig.planning-evidence.v1":
            incomplete.append("planning_evidence_unavailable")
        else:
            for evidence in planning["packet"]["items"]:
                revision = revisions[evidence["revision_id"]]
                verify_span(revision, Span(evidence["revision_id"], evidence["text_sha256"], evidence["start"], evidence["end"], evidence["text"]))
    except (ContractError, KeyError, TypeError, ValueError):
        issues.append("invalid_planning_or_applicability")
    requests, responses, validations, failures = {}, {}, {}, {}
    planner_calls, plan_predicates, plan_expression, plan = set(), None, None, None
    request_data, response_data, validation_data, pending_judges, plan_questions = {}, {}, {}, [], {}
    trace_observations = {}
    trace_rounds = {}
    final_result = None
    review_record, review_call = None, None
    traces = 0
    for event in events:
        kind, call_id, data = event["kind"], event["call_id"], event["data"]
        try:
            if kind == "request":
                request = ProviderRequest(data["stage"], data["provider"], data["model"], data["prompt"], data["max_tokens"], max_price=data.get("max_price"))
                if request.input_sha256() != data["input_sha256"]:
                    raise ContractError("request hash mismatch")
                requests[call_id] = event["seq"]
                request_data[call_id] = request
                if data["stage"] in ("judge_positive", "judge_negative"):
                    pending_judges.append((call_id, request))
                elif data["stage"] == "plan_review":
                    settings = context.get('reviewer')
                    if (not isinstance(settings, dict) or review_call is not None or
                            (request.provider, request.model, request.max_tokens, request.max_price) !=
                            (settings['provider'], settings['model'], settings['max_tokens'], settings.get('max_price'))):
                        raise ContractError('review request differs from context')
                    review_call = call_id
                elif data["stage"] != "planner":
                    incomplete.append(f"unsupported_stage:{call_id}")
                if data["stage"] == "planner":
                    planner_calls.add(call_id)
                    if not {"planner", "request", "planning_evidence"} <= context.keys():
                        incomplete.append("planner_context_unavailable")
                    else:
                        settings = context["planner"]
                        expected_prompt = _planner_prompt(Request.from_dict(context["request"]),
                                                          corpus_manifest_sha256(context["corpus"]),
                                                          context["planning_evidence"])
                        if (request.prompt != expected_prompt or request.model != settings["model"] or
                            request.provider != settings["provider"] or request.max_tokens != settings["max_tokens"] or
                            request.max_price != settings.get("max_price")):
                            raise ContractError("planner request does not match recorded context")
            elif kind == "response":
                if call_id not in requests or requests[call_id] >= event["seq"]:
                    raise ContractError("response without prior request")
                if hashlib.sha256(data["body"].encode("utf-8")).hexdigest() != data["body_sha256"]:
                    raise ContractError("response hash mismatch")
                responses[call_id] = event["seq"]
                response_data[call_id] = data
            elif kind == "validation":
                if call_id not in responses or responses[call_id] >= event["seq"]:
                    raise ContractError("validation without prior response")
                validations[call_id] = event["seq"]
                saved_response = response_data[call_id]
                stage = request_data[call_id].stage
                if data.get("failure") == "validator_error":
                    incomplete.append(f"validator_error:{call_id}")
                elif stage == "planner" or stage in ("judge_positive", "judge_negative", "plan_review"):
                    if not 200 <= saved_response["http_status"] < 300:
                        expected_value, expected_failure = None, "http_error"
                    elif stage == "planner":
                        expected_value, expected_failure = _plan_validator(saved_response["body"])
                    elif stage == 'plan_review':
                        expected_value, expected_failure = _validate(saved_response['body'], _REVIEW_SCHEMA)
                    else:
                        expected_value, expected_failure = _validate(saved_response["body"], SIDE_SCHEMA)
                    if data.get("value") != expected_value or data.get("failure") != expected_failure:
                        raise ContractError("typed validation differs from recorded response")
                validation_data[call_id] = data
                if call_id in planner_calls and data.get("failure") is None:
                    plan = parse_plan({**data["value"], "origin": "fresh"})
                    plan_predicates = {p.id for p in plan.predicates}
                    plan_questions = {p.id: p.question for p in plan.predicates}
                    plan_expression = plan.expression
                if data.get("failure") is not None:
                    incomplete.append(f"validation_failure:{call_id}")
            elif kind == "failure":
                if call_id not in requests or requests[call_id] >= event["seq"]:
                    raise ContractError("failure without prior request")
                failures[call_id] = event["seq"]
                incomplete.append(f"provider_failure:{call_id}")
            elif kind == 'review_record':
                if review_record is not None or call_id != review_call or call_id not in validation_data:
                    raise ContractError('review record is not uniquely linked')
                _check_review(data, call_id, request_data[call_id], response_data[call_id], validation_data[call_id], context, plan)
                review_record = data
            elif kind == "trace":
                traces += 1
                if plan_predicates is None or data["predicate_id"] not in plan_predicates:
                    raise ContractError("trace predicate absent from validated plan")
                if data["sequence"] != traces:
                    raise ContractError("trace sequence mismatch")
                policy = context.get("followup_policy")
                if policy == "request_question_on_no_primary_hit_v1":
                    pid = data["predicate_id"]
                    round_number = trace_rounds.get(pid, 0) + 1
                    if type(data["round_number"]) is not int or data["round_number"] != round_number or round_number > 2:
                        raise ContractError("invalid followup round")
                    if round_number == 1:
                        expected_query = plan_questions[pid]
                    else:
                        prior = trace_observations[pid]
                        if prior.get("outcome") != "unknown" or prior.get("reason") != "no_retrieval_hit":
                            raise ContractError("followup lacks no-hit predecessor")
                        expected_query = context["request"]["question"]
                        if expected_query.strip() == plan_questions[pid].strip():
                            raise ContractError("followup repeats first query")
                    if data["query"] != expected_query:
                        raise ContractError("trace query differs from followup policy")
                    if data["observation"].get("reason") == "no_retrieval_hit" and data["hit_count"] != 0:
                        raise ContractError("no-hit observation has hits")
                    trace_rounds[pid] = round_number
                elif policy is not None:
                    incomplete.append("followup_policy_unavailable")
                trace_observations[data["predicate_id"]] = data["observation"]
                rendered = "\n".join(f"[{item['entry_id'][:12]}]\n{item['text']}" for item in data["evidence"])
                seen_sides = set()
                side_ids = {}
                for judge_id, judge_request in pending_judges:
                    side = judge_request.stage.removeprefix("judge_")
                    expected = _PROMPT.format(claim=f"The answer to '{plan_questions[data['predicate_id']]}' is {'YES' if side == 'positive' else 'NO'}.", evidence=rendered)
                    settings = context["judge"]
                    if (side in seen_sides or judge_request.prompt != expected or judge_request.model != settings["model"] or
                        judge_request.provider != settings["provider"] or judge_request.max_tokens != settings["max_tokens"] or
                        judge_request.max_price != settings.get("max_price")):
                        issues.append(f"invalid_judge_binding:{judge_id}")
                    seen_sides.add(side)
                    side_ids[side] = judge_id
                if set(side_ids) == {"positive", "negative"} and all(
                    key in validation_data and validation_data[key].get("failure") is None for key in side_ids.values()
                ):
                    packet_items = tuple(PacketItem(item["entry_id"], Span(item["revision_id"], item["text_sha256"],
                                                item["start"], item["end"], item["text"]), item["truncated"])
                                         for item in data["evidence"])
                    packet = EvidencePacket(packet_items, (), (), 0, 0)
                    pos = _side_from_value(validation_data[side_ids["positive"]]["value"], side_ids["positive"])
                    neg = _side_from_value(validation_data[side_ids["negative"]]["value"], side_ids["negative"])
                    judgment = _combine_sides(pos, neg, packet, lambda rid: Applicability(context["corpus"].get(rid, "unknown")))
                    expected_observation = {"outcome": judgment.observation.outcome.value, "reason": judgment.observation.reason}
                    if data["observation"] != expected_observation:
                        issues.append(f"invalid_judge_outcome:{data['predicate_id']}")
                elif pending_judges:
                    incomplete.append(f"judge_outcome_not_replayed:{data['predicate_id']}")
                elif str(data["observation"].get("reason", "")).startswith("judge_"):
                    issues.append(f"invalid_judge_outcome:{data['predicate_id']}")
                pending_judges.clear()
                for evidence in data["evidence"]:
                    revision = revisions[evidence["revision_id"]]
                    verify_span(revision, Span(evidence["revision_id"], evidence["text_sha256"], evidence["start"], evidence["end"], evidence["text"]))
            elif kind == "run_result":
                if final_result is not None or event["seq"] != events[-1]["seq"]:
                    raise ContractError("run result is duplicated or not final")
                if data.get('schema') == 'qjig.fresh-failure.v1':
                    keys = {'schema', 'request_id', 'stage', 'status', 'failure', 'call_ids', 'reconciliation_required'}
                    if (set(data) != keys or data['request_id'] != context['request']['request_id']
                            or data['stage'] != 'planner' or data['status'] != 'deferred'
                            or not isinstance(data['failure'], str) or not data['failure']
                            or not isinstance(data['call_ids'], list) or len(data['call_ids']) > 1
                            or set(data['call_ids']) != planner_calls or type(data['reconciliation_required']) is not bool
                            or plan is not None or traces or pending_judges or review_record is not None
                            or set(requests) != planner_calls):
                        raise ContractError('invalid planner failure result')
                    if data['call_ids']:
                        call_id = data['call_ids'][0]
                        if call_id in validation_data:
                            if validation_data[call_id].get('failure') != data['failure']:
                                raise ContractError('planner validation failure differs')
                        elif call_id in failures:
                            failure_data = next(e['data'] for e in events if e['kind'] == 'failure' and e['call_id'] == call_id)
                            expected = 'uncertain_outcome' if data['failure'] == 'uncertain_outcome' else 'provider_failure' if data['failure'] == 'provider_unavailable' else None
                            if failure_data.get('failure') != expected or (expected == 'uncertain_outcome' and not data['reconciliation_required']):
                                raise ContractError('planner transport failure differs')
                        else:
                            raise ContractError('planner failure terminal missing')
                    elif data['failure'] not in ('budget_exceeded', 'reconciliation_required'):
                        raise ContractError('unexplained missing planner call')
                    incomplete.append('planner_failure:' + data['failure'])
                    final_result = data
                    continue
                if (data.get("schema") != "qjig.fresh-result.v1" or data.get("status") != "deferred" or
                    data.get("request_id") != context.get("request", {}).get("request_id") or
                    data.get("expression") != plan_expression or data.get("trace_count") != traces or
                    data.get("observations") != trace_observations or
                    "plan_coverage_unestablished" not in data.get("reasons", []) or
                    COVERAGE_ID not in data.get("blocking_obligations", [])):
                    raise ContractError("run result does not match recorded trace or plan")
                review = data.get('review')
                if 'reviewer' in context:
                    base_fields = {'status', 'failure', 'call_id', 'review_id'}
                    if not isinstance(review, dict) or set(review) not in (base_fields, base_fields | {'draft_id'}):
                        raise ContractError('configured review result missing')
                    if review['status'] == 'recorded':
                        if review_record is None:
                            incomplete.append('review_record_unavailable')
                        elif review != {'status': 'recorded', 'failure': None, 'call_id': review_call, 'review_id': review_record['sha256'],
                                        **({'draft_id': make_draft(review_record['payload']['binding'])['sha256']} if 'draft_id' in review else {})}:
                            raise ContractError('review result differs from record')
                    elif (review['status'] == 'unavailable' and review['review_id'] is None and review.get('draft_id') is None
                          and isinstance(review['failure'], str) and review_record is None):
                        incomplete.append('review_unavailable')
                    else:
                        raise ContractError('invalid review result')
                elif review is not None or review_record is not None:
                    raise ContractError('review has no configured context')
                final_result = data
            else:
                raise ContractError("unknown event kind")
        except (ContractError, KeyError, TypeError, ValueError, AttributeError):
            issues.append(f"invalid_{kind}:{call_id}")
    for call_id in requests:
        if call_id not in responses and call_id not in failures:
            incomplete.append(f"pending_request:{call_id}")
        if call_id in responses and call_id not in validations:
            incomplete.append(f"missing_validation:{call_id}")
        if call_id in responses and call_id in failures:
            issues.append(f"conflicting_terminal:{call_id}")
    if pending_judges:
        incomplete.append("untraced_judge_calls")
    if not requests or not traces:
        incomplete.append("missing_request_or_trace")
    if final_result is None:
        incomplete.append("missing_run_result")
    snapshot = {"context": context, "sources": sources, "revisions": {
        key: {"source_id": rev.source_id, "origin": rev.origin, "encoding": rev.decoded.encoding,
              "raw_sha256": rev.decoded.raw_sha256, "text_sha256": rev.decoded.text_sha256}
        for key, rev in sorted(revisions.items())}, "events": events}
    try:
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return ReplayReport("invalid", None, tuple(issues + incomplete + ["snapshot_not_serializable"]), len(requests), len(responses), traces)
    if expected_digest is not None and digest != expected_digest:
        issues.append("archive_digest_mismatch")
    status = "invalid" if issues else "incomplete" if incomplete else "unanchored" if expected_digest is None else "structurally_verified"
    return ReplayReport(status, digest, tuple(issues + incomplete), len(requests), len(responses), traces)
