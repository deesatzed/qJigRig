"""Structural archive checks without inference or claims of semantic correctness."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .acquisition import COVERAGE_ID
from .applicability import ApplicabilityInputs
from .contracts import ContractError, Request
from .planner import _planner_prompt, corpus_manifest_sha256
from .plans import parse_plan
from .providers import ProviderRequest
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
            if any(reconstructed.verdict(key).value != value for key, value in context["corpus"].items()):
                raise ContractError("applicability verdict mismatch")
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
    planner_calls, plan_predicates, plan_expression = set(), None, None
    trace_observations = {}
    final_result = None
    traces = 0
    for event in events:
        kind, call_id, data = event["kind"], event["call_id"], event["data"]
        try:
            if kind == "request":
                request = ProviderRequest(data["stage"], data["provider"], data["model"], data["prompt"], data["max_tokens"])
                if request.input_sha256() != data["input_sha256"]:
                    raise ContractError("request hash mismatch")
                requests[call_id] = event["seq"]
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
                            request.provider != settings["provider"] or request.max_tokens != settings["max_tokens"]):
                            raise ContractError("planner request does not match recorded context")
            elif kind == "response":
                if call_id not in requests or requests[call_id] >= event["seq"]:
                    raise ContractError("response without prior request")
                if hashlib.sha256(data["body"].encode("utf-8")).hexdigest() != data["body_sha256"]:
                    raise ContractError("response hash mismatch")
                responses[call_id] = event["seq"]
            elif kind == "validation":
                if call_id not in responses or responses[call_id] >= event["seq"]:
                    raise ContractError("validation without prior response")
                validations[call_id] = event["seq"]
                if call_id in planner_calls and data.get("failure") is None:
                    plan = parse_plan({**data["value"], "origin": "fresh"})
                    plan_predicates = {p.id for p in plan.predicates}
                    plan_expression = plan.expression
                if data.get("failure") is not None:
                    incomplete.append(f"validation_failure:{call_id}")
            elif kind == "failure":
                if call_id not in requests or requests[call_id] >= event["seq"]:
                    raise ContractError("failure without prior request")
                failures[call_id] = event["seq"]
                incomplete.append(f"provider_failure:{call_id}")
            elif kind == "trace":
                traces += 1
                if plan_predicates is None or data["predicate_id"] not in plan_predicates:
                    raise ContractError("trace predicate absent from validated plan")
                if data["sequence"] != traces:
                    raise ContractError("trace sequence mismatch")
                trace_observations[data["predicate_id"]] = data["observation"]
                for evidence in data["evidence"]:
                    revision = revisions[evidence["revision_id"]]
                    verify_span(revision, Span(evidence["revision_id"], evidence["text_sha256"], evidence["start"], evidence["end"], evidence["text"]))
            elif kind == "run_result":
                if final_result is not None or event["seq"] != events[-1]["seq"]:
                    raise ContractError("run result is duplicated or not final")
                if (data.get("schema") != "qjig.fresh-result.v1" or data.get("status") != "deferred" or
                    data.get("request_id") != context.get("request", {}).get("request_id") or
                    data.get("expression") != plan_expression or data.get("trace_count") != traces or
                    data.get("observations") != trace_observations or
                    "plan_coverage_unestablished" not in data.get("reasons", []) or
                    COVERAGE_ID not in data.get("blocking_obligations", [])):
                    raise ContractError("run result does not match recorded trace or plan")
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
