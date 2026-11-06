# Proposed canonical contracts, version 1

These contracts are design targets. Dataclasses, validators and migrations are T001–T010; no runtime implementation is claimed.

| Record | Required meaning |
|---|---|
| SourceRevision | Portable source_id, revision_id, origin, raw_sha256, text_sha256, decoding/extractor/normalization version, blob references, observed_at; optional recorded authority_id, entity keys, scope and effective interval with provenance |
| Span | revision_id, text_sha256, start/end code-point offsets (end-exclusive), exact text, optional derived line/page anchors, extraction_assurance; no span crosses source members |
| IndexEntry | entry_id, revision_id, span reference, structural/topic kind, derived method/version, proposed/accepted/rejected/stale state; separate from source text |
| RoleDefinition | role_id, version, purpose; immutable once used |
| RoleEstimate | role/version, span or record target and revision, estimated usefulness, method/model, proposal state and receipt; never an authority or truth score |
| AgentClaim | claim_id, producer, text, creation time, evidence references, lifecycle; even accepted evidence links do not make text source evidence |
| Request | request_id, question, entity keys, scope, as_of, historical_as_known, role/version, corpus manifest hash, evidence policy, budget policy, experiment arm |
| Predicate | id, question, evidence_requirement, dependency refs, exact operator or semantic claims, required source/authority/entity/time constraints, exception obligations; planner may only use whitelisted operators |
| Plan | schema_version, predicates (1–6), bounded AND/OR/NOT expression, answer labels, origin authored/fresh/reused, validation state, explicit known coverage gaps; no executable model code |
| EvidencePacket | request/plan/predicate binding, requested and returned span IDs, exclusion and truncation reasons, coverage observations, per-span assurance, serialized size and tokenizer identity; transport framing budget counted separately |
| PredicateObservation | true/false/unknown/conflict, reason code, exact span refs, applicability result, evaluator kind/exact operator/model receipt; unknown reasons preserve missing source/no match/truncation/provider failure/budget |
| RunEvent | request_id, monotonic sequence, stage, pinned config/input hashes, intent/receipt/failure, usage/cost known or unknown, timestamp; immutable append-only |
| DecisionResult | decided/deferred/failed, candidate answer, conditional graph outcome, unresolved facts/conflicts, exclusions, stopping witness, evidence refs, assurance, costs/coverage; never omit caveats when rendering |

Raw identity uses raw bytes. Text identity uses decoded immutable UTF-8 text with a declared normalizer (initially identity); do not normalize an input silently. Legacy QUIXER's universal-newline hash is stored as legacy_normalized_sha256 and mapped through a translation table; its start/end lines are resolved against the named legacy normalized text, then translated to canonical offsets and checked. Legacy JIG offsets refer to its raw text and must be verified against that source hash. PDF bytes and extracted text have separate hashes/extractor versions; page numbers alone cannot establish an exact text span.

Each member of a collection has independent scope, authority, entity and dates. Do not join sources into a new apparent authority. Dates are ISO calendar dates. Initial intervals are inclusive [from,to], with unknown boundaries represented explicitly. An unknown date is not automatically compatible. historical_as_known additionally requires observed_at <= request.as_of; an unknown observation date remains an unresolved obligation.

Plan syntax validity, span identity, applicable metadata, semantic support and independent adjudication are separate checks. Every rendering and export must preserve that distinction. No scalar confidence collapses them.
