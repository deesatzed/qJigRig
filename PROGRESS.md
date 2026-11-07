# qJig progress

## 2026-11-06: checkpoint, review and proposed build design

The user requested an algorithmic combination of QUIXER and the moved JIG workbench, a checkpoint of QUIXER, a thorough review and granular small-test build steps. This pass creates that repository and review packet; it does not claim a combined runtime.

Completed:

- Verified QUIXER `research-slice` at `1790086a5d3b178957ce80324c0f283dbcf78c97` on GitHub and pushed annotated tag `checkpoint/quixer-before-qjig-2026-11-06`.
- Initialized `/Volumes/WS4TB/qJig` as a new local main-branch repository. The existing moved JIG folder was preserved. QUIXER's exact committed tracked tree is archived under `sources/quixer`.
- Read both goals/plans/current audits and inspected storage, identity, indexing, role ranking, recovery, bounded reasoning, stopping, model adapters, programs and experiment recovery. Found stale JIG instructions and historical test counts.
- Reran QUIXER 263 Python tests, switch 33 tests/typecheck and JIG 250 offline tests. A frozen source copy passed JIG's 250 tests after correcting audit copy/cwd setup errors; preserved logs distinguish those from source defects.
- Reproduced JIG private-KB authored fixture results and ran four explicit compatibility probes without live provider calls.
- Proposed one canonical source/trace contract, bounded deterministic acquisition and exact reasoning, then real providers/shared agents/measurement in later phases.
- Wrote 74 pending runtime tasks with dependencies, target modules, named focused tests, acceptance behavior and red/green/commit actions. No source test result closes these tasks.

Assumptions and choices:

- qJig root is the new app repository; the moved JIG folder is reference material, not the future package root.
- The user's approval to combine the ideas authorizes this review/repository/planning work. The detailed implementation design remains proposed for review before app-code changes.
- Start with a non-sensitive software-project evidence family and a deterministic fixture graph. Keep provider-backed fresh planning, real-agent outcomes and independent judgments distinct.
- Preserve existing Hy4 selection; no new live model expenditure or model promotion during review.
- Credentials/environments/generated data remain local and excluded. No remote was supplied for qJig, so it is a local repository.
- No top-level source license was located; source references are retained locally, and distribution rights remain an explicit publication consideration.

Next: review SYNTHESIS.md, docs/ALGORITHM.md and GOAL.md, then implement T001–T005 one tested behavior per commit. Do not start a wholesale merge or UI-first build.

Repository checkpoint: initial qJig source/provenance commit `da1397b`. Staged path and credential-pattern checks found no credential files, generated data, virtualenvs or private-key/API-key patterns in the 310 checkpoint files. Two inherited whitespace warnings were recorded rather than changing source bytes. This is a narrow pattern check, not a general security audit.

## 2026-11-06: T001 complete

- Added `pyproject.toml` (Python >=3.11, no runtime dependencies, pytest limited to `tests/` with `pythonpath=src`, so nested source suites are not collected), `src/qjig/__init__.py`, `tests/test_bootstrap.py`.
- Red: `test_import_has_no_io` failed with `ModuleNotFoundError: No module named 'qjig'` (allowed initial contract failure).
- Green: focused test 1 passed; `tests/test_bootstrap.py` 1 passed; full `python -m pytest -q` 1 passed.
- Sensitivity check: temporarily appending a file write to `__init__.py` made the test fail; reverted.
- Limits: the test uses a Python audit hook in a subprocess, which sees open/socket/mkdir/remove events during import only. Not verified: a clean `pip install` of the package (not attempted). `verify_packet.py` asserts all tasks pending and will now fail by design; implementation-aware validation is still to be added.

## 2026-11-06: T002 complete

- `Request` (frozen dataclass: request_id, question, role, role_version, scope) with `to_dict`/`from_dict` in `src/qjig/contracts.py`; schema tag `qjig.request.v1`.
- Red: `ModuleNotFoundError: qjig.contracts`. Green: focused 1 passed, `tests/test_contracts.py` 1 passed, full suite 2 passed.
- Behavior: JSON round trip equals the original; role and scope kept byte-exact (no trimming/case folding); wrong or missing schema_version, missing fields and unknown fields raise `ContractError`.
- Limits: only the minimal fields exist; entity keys, as_of, evidence policy, corpus hash and experiment arm from docs/CONTRACTS.md are not yet modeled (later tasks).

## 2026-11-06: T003 complete

- Added `Budget` and optional `Request.budget`; validation runs at construction and in `from_dict`.
- Red: `ImportError: Budget` at collection. Green: `test_reject_invalid_budget` 10 cases passed; `tests/test_contracts.py` 12 passed; full suite 13 passed.
- Rejected: True/False, negatives, floats or strings for counts, NaN/inf/negative cost, non-object budget, unknown/missing budget fields. Accepted: zero limits.
- Limit: this only validates shape. Nothing enforces or spends a budget yet.

## 2026-11-06: T004 complete

- `decode_source(raw, *, encoding)` in `src/qjig/sources.py` returns a frozen `DecodedSource`: original bytes, `raw_sha256` (of the bytes), named `encoding`, `normalizer="identity"`, decoded `text` (CRLF kept) and `text_sha256` (of the UTF-8 encoding of the text).
- Red: `ModuleNotFoundError: qjig.sources`. Green: focused test passed; `tests/test_sources.py` 3 passed; full suite 16 passed.
- Test uses latin-1 `café` + CRLF so the two hashes differ; strict decoding raises `ContractError` rather than substituting characters; the encoding argument is required.
- Limits: in-memory only. No blob storage, no revision record, no BOM handling policy (a UTF-8 BOM would stay as U+FEFF in text under `utf-8`), no PDF extractor.

## 2026-11-06: T005 complete

- Added `SourceRevision.create(source_id, origin, decoded)` and `require_pin(...)` in `src/qjig/sources.py`.
- Red: `ImportError: SourceRevision`. Green: focused test passed; `tests/test_sources.py` 11 passed; full suite 24 passed.
- Shown: the same content read from two different absolute origins gives the same `revision_id`; changed bytes, a different encoding choice or a different `source_id` give a different one; `require_pin` fails on changed content but not on a move; path-like source ids are rejected.
- Limits: the id attests content identity only, not authority or semantics. There is no store, no entity/scope/date fields and no check that an origin really holds these bytes (later P1 tasks). Hash scheme is a new qJig contract and is not yet reconciled with QUIXER/JIG hashes (T007+).

## Phase note (T001-T005)

Full qJig suite after T005: 24 passed (`python -m pytest -q`, Python 3.13.9). T006-T012 remain in P1. `reports/verify_packet.py` still asserts all tasks pending, so it fails by design now; an implementation-aware check has not been written.

## 2026-11-06: T006 complete

- `Span`, `make_span`, `verify_span` in `src/qjig/spans.py`: offsets are code-point, end-exclusive; an astral emoji counts as one position; altered quote, shifted offsets, other revision, wrong text hash and bad offsets (bool, negative, empty, out of range) all raise `ContractError`. Limit: line/page anchors and extraction assurance fields from CONTRACTS.md are not modeled yet.
- Red: ModuleNotFoundError qjig.spans (initial contract). Green: focused 1 passed in 0.08s; tests/test_spans.py 7 passed in 0.04s; full suite 31 passed in 0.10s. 2026-11-06.

## 2026-11-06: T007 complete

- `translate_quix_lines` in `src/qjig/legacy_quix.py` maps legacy 1-based inclusive line spans over universal-newline text to a canonical raw-text `Span`. Test pins the real QUIXER hash (2fcfb783...) and JIG raw hash (6a3b3844...) recorded in reports/compatibility-probes.json for b'One\\r\\nTwo\\r\\n' — they stay distinct. Handles CRLF, lone CR and LF; wrong legacy hash, bad line numbers raise. Limits: blank-line-only spans are rejected as empty; no QUIXER import (legacy code not run in this test); PDF page anchors not translated.
- Red: ModuleNotFoundError qjig.legacy_quix (initial contract). Green: focused 1 passed in 0.04s; tests/test_legacy_quix.py 3 passed in 0.05s; full suite 34 passed in 0.11s. 2026-11-06.

## 2026-11-06: T008 complete

- `translate_jig_offsets` and `translate_jig_quote` in `src/qjig/legacy_jig.py`. JIG's hash must equal the revision's `text_sha256` (real JIG hash 6a3b3844... pinned in the test); a changed revision that still contains the same quote at the same offsets is rejected; mismatched, missing, ambiguous and blank quotes are rejected. Limits: JIG's collection/source-boundary check (span_ref) is not translated; JIG code is not imported.
- Red: ModuleNotFoundError qjig.legacy_jig (initial contract). Green: focused 1 passed in 0.03s; tests/test_legacy_jig.py 3 passed in 0.03s; full suite 37 passed in 0.14s. 2026-11-06.

## 2026-11-06: T009 complete

- `Catalog` in `src/qjig/store.py` (SQLite, explicit open, context manager). Two revisions of one source survive close/reopen with raw bytes and encoding intact; same-id re-add is idempotent and keeps the first origin; UPDATE/DELETE blocked by triggers; reads detect tampering; unknown schema version refused. Limits: single-writer only (not tested concurrently); no entity/scope/date metadata yet (T010); no atomic multi-record writes beyond single inserts.
- Red: ModuleNotFoundError qjig.store (initial contract). Green: focused 1 passed in 0.04s; tests/test_store.py 4 passed in 0.04s; full suite 41 passed in 0.10s. 2026-11-06.

## 2026-11-06: T010 complete

- `Interval`, `MemberMetadata`, `Collection`, `Applicability` (match/no_match/unknown) in `src/qjig/applicability.py`. Old [2026-01-01,2026-10-31] and new [2026-11-01, open] policy coexist in one collection with no shared interval; inclusive bounds; unknown boundary gives UNKNOWN unless the other bound already excludes the date; strict ISO dates; duplicate revision in a collection rejected. Limit: metadata is not yet persisted in the catalog.
- Red: ModuleNotFoundError qjig.applicability (initial contract). Green: focused 1 passed in 0.04s; tests/test_applicability.py 10 passed in 0.03s; full suite 51 passed in 0.11s. 2026-11-06.

## 2026-11-06: T011 complete

- `entity_applicability` returns a `Verdict(value, reason)`: unrecorded source subject or missing request subject -> UNKNOWN (reasons source_entity_unrecorded / request_entity_missing); disjoint recorded subjects -> NO_MATCH; overlap -> MATCH; exact, case-sensitive keys. Limit: a source deliberately written for all subjects also reads as UNKNOWN until a way to declare that is added.
- Red: ImportError entity_applicability (initial contract). Green: focused 1 passed in 0.04s; tests/test_applicability.py 12 passed in 0.04s; full suite 53 passed in 0.11s. 2026-11-06.

## 2026-11-06: T012 complete

- `date_applicability` returns separate effective-date and observation-date verdicts plus a combined result (NO_MATCH beats UNKNOWN beats MATCH). A review observed 2026-12-01 is effective for a 2026-06-01 request but is rejected under historical-as-known (reason observed_after_request); unknown observation date is UNKNOWN only for historical requests. `MemberMetadata.observed_at` added, validated as ISO date. Limit: dates are recorded claims, not authenticated; effective_to/observed_at are not persisted in the catalog yet.
- Red: ImportError date_applicability (initial contract). Green: focused 1 passed in 0.03s; tests/test_applicability.py 14 passed in 0.03s; full suite 55 passed in 0.10s. 2026-11-06.

## 2026-11-06: T013 complete

- `index_markdown_headings`, `save_entries`, `load_entries`, `resolve_entry` in `src/qjig/indexing.py`; catalog schema v2 adds `index_entries` (migration from v1 tested). Refunds section resolves after close/reopen to the exact CRLF slice '## Refunds\\r\\nRefund within 30 days.' and re-verifies against the stored revision; fenced/indented/hashtag lines ignored; entries for unstored revisions refused. Limits: ATX headings only; a 'heading' entry's accepted state is structural, not a relevance claim.
- Red: ModuleNotFoundError qjig.indexing (initial contract). Green: focused 1 passed in 0.07s; tests/test_indexing.py 4 passed in 0.05s; full suite 60 passed in 0.14s. 2026-11-06.

## 2026-11-06: T014 complete

- `index_entries` adds a proposed, title-less `extractive_fallback` entry for unheaded text (whole doc, or text before the first heading); documents whose text is all under headings are unchanged; blank documents give none. Limit: text between or after sections is already inside heading sections, so only leading text is a fallback case; fallback method name is a provisional label.
- Red: ImportError index_entries (initial contract). Green: focused 1 passed in 0.04s; tests/test_indexing.py 7 passed in 0.05s; full suite 63 passed in 0.13s. 2026-11-06.

## 2026-11-06: T015 complete

- `split_broad_section(revision, section, max_chars=...)` proposes paragraph children (blank-line separated) as exact, non-overlapping slices inside the parent span with `parent_entry_id` and state `proposed`; sections within the limit or with one paragraph return nothing; invalid max_chars rejected. Limit: the heading line stays attached to the first paragraph; what counts as 'broad' is a caller-supplied character limit, not a tuned value.
- Red: ImportError split_broad_section (initial contract). Green: focused 1 passed in 0.04s; tests/test_indexing.py 9 passed in 0.06s; full suite 65 passed in 0.15s. 2026-11-06.

## 2026-11-06: T016 complete

- `invalidate_superseded` marks live entries of a source's other revisions `stale` (rejected stay rejected); `current_entries` returns only proposed/accepted entries of the revision the caller names as current. Old entries stay loadable and resolve to the old pinned text; the new revision has none until indexed; unrelated sources untouched; repeat is a no-op. Limit: the catalog does not itself decide which revision is current — the caller passes it (a current-revision policy arrives with T037).
- Red: ImportError current_entries/invalidate_superseded (initial contract). Green: focused 1 passed in 0.04s; tests/test_indexing.py 11 passed in 0.05s; full suite 67 passed in 0.13s. 2026-11-06.

## 2026-11-06: T017 complete

- `bm25_candidates` and `tokenize` in `src/qjig/retrieval.py`: Okapi BM25 (k1=1.2, b=0.75) over entry span text, unicode lowercase \\w+ tokens, no stemming or stopwords. Each candidate carries per-term frequency/document frequency/contribution, corpus size and average length. Identical documents tie exactly and order by entry_id; repeated runs and reversed input give identical results; non-matching entries are omitted; empty/punctuation queries give none. Limits: parameters are standard defaults, not tuned; scores are uncalibrated and only meaningful within one corpus; one test expectation was initially wrong (my miscount of 'Refunds' vs 'refund') and was corrected, not the code.
- Red: ModuleNotFoundError qjig.retrieval (initial contract). Green: focused 1 passed in 0.05s; tests/test_retrieval.py 3 passed in 0.03s; full suite 70 passed in 0.15s. 2026-11-06.

## 2026-11-06: T018 complete

- `TopicIndex.attach` creates proposed `TopicLink`s holding a `SpanRef` (revision, offsets, text hash) and no text; two topics on one entry share an identical span reference; attach is idempotent; blank topics rejected. Limits: in-memory only, not persisted in the catalog and lost on exit; topics are exact strings; method name is a placeholder for manual attachment.
- Red: ModuleNotFoundError qjig.topics (initial contract). Green: focused 1 passed in 0.04s; tests/test_topics.py 2 passed in 0.03s; full suite 72 passed in 0.16s. 2026-11-06.

## 2026-11-06: T019 complete

- `RoleDefinition`, `RoleEstimate` (field `estimated_usefulness`, finite [0,1], state proposed) and `RoleEstimateStore`. `current_prior` returns an estimate only for the exact role id, role version, entry and revision; a version change or source change makes it unavailable while `all_for` still lists the old estimate; overwriting an existing key is refused; bad scores (bool, NaN, out of range, string, None) rejected. Limits: in-memory only; nothing produces estimates yet; scores are uncalibrated and are not truth or authority.
- Red: ModuleNotFoundError qjig.roles (initial contract). Green: focused 1 passed in 0.03s; tests/test_roles.py 9 passed in 0.04s; full suite 81 passed in 0.15s. 2026-11-06.

## 2026-11-06: T020 complete

- `select_with_mandatory(channels, required_channels, limit, role_priors)` in `src/qjig/retrieval.py`: order is lexical score, then role prior (tie-breaker only; absent prior = neutral 0.5), then entry_id; every required channel that has a candidate gets its best one reserved before general fill; required channels with no candidate are returned as `missing_required` and ones squeezed out by the limit as `omitted_required`. A zero role score on the only exception source does not drop it (checked at priors 0, 0.5, 1). Limits: channel assignment (which query/source feeds which channel) is caller-supplied; two test expectations were my own miscounts and were corrected; omitted_required would also need to become an unresolved obligation (T024).
- Red: ImportError select_with_mandatory (initial contract). Green: focused 1 passed in 0.04s; tests/test_retrieval.py 6 passed in 0.03s; full suite 84 passed in 0.16s. 2026-11-06.

## 2026-11-06: T021 complete

- `build_packet(candidates, max_bytes=)` in `src/qjig/packets.py`. Size = UTF-8 bytes of canonical JSON of the whole packet including omission records (unit named `utf8_json_bytes`; no model tokenizer). Swept limits from the full size down to 700: the serialized packet never exceeded the limit; every candidate is either included or omitted with reason `exceeds_budget`; the first overflow may be cut to an exact, verified prefix and is flagged truncated with its original end; a sweep covered both omission and truncation. Too-small or invalid limits raise. Limits: transport framing and model tokens are not counted; prefix cuts are character-based and may land mid-sentence; truncation does not yet create an unresolved obligation (T024).
- Red: ModuleNotFoundError qjig.packets (initial contract). Green: focused 1 passed in 0.03s; tests/test_packets.py 3 passed in 0.04s; full suite 87 passed in 0.15s. 2026-11-06.

## 2026-11-06: T022 complete

- `recover_packet(catalog, candidates, want=, max_bytes=)` in `src/qjig/recovery.py` re-verifies each ranked candidate against the stored revision. Top candidate whose source was never stored -> exclusion `source_missing`, next verified span used and linked in `alternatives`; forged span text -> `span_mismatch`; tampered store -> `source_changed`; nothing available -> empty packet, no alternatives. Limits: exclusions live in `RecoveryResult`, not inside the serialized packet body; 'alternative' means the next verified candidate in rank order and does NOT yet check that it is about the right subject/entity (T023), so by itself it can substitute irrelevant text.
- Red: ModuleNotFoundError qjig.recovery (initial contract). Green: focused 1 passed in 0.04s; tests/test_recovery.py 4 passed in 0.05s; full suite 91 passed in 0.16s. 2026-11-06.

## 2026-11-06: T023 complete

- `recover_packet` now takes an optional `applicability` check; `applicability_filter` combines per-source entity and date verdicts. A different-customer source is excluded as `inapplicable`, a source with no recorded subject or no metadata as `applicability_unknown`, a not-yet-effective one as `inapplicable`; none fills the slot, so the packet is empty and `unfilled` reports the shortfall. A correct-subject alternative is still used. Limits: `applicability` is optional and defaults to accepting everything (T022 behavior), so callers must pass it; relevance of text to the question is not judged, only subject/date applicability.
- Red: ImportError applicability_filter (initial contract). Green: focused 1 passed in 0.04s; tests/test_recovery.py 7 passed in 0.06s; full suite 94 passed in 0.16s. 2026-11-06.

## 2026-11-06: T024 complete

- `Obligation` and `ObligationLedger` in `src/qjig/obligations.py`. A retrieval with zero hits leaves a material exception obligation `unresolved` with reason `no_retrieval_hit` and it keeps blocking; `absence_established` is always False; only `satisfy` with evidence references closes it. Distinct reasons recorded: no_retrieval_hit, source_unavailable, only_inapplicable_candidates, applicability_unknown, truncated, budget_omission. Evidence found is `evidence_found`, not satisfied. Limits: in-memory ledger; 'satisfied' semantics (what counts as proof) are left to later evaluation tasks; `absence_established` is a contract marker, not a computation.
- Red: ModuleNotFoundError qjig.obligations (initial contract). Green: focused 1 passed in 0.03s; tests/test_obligations.py 4 passed in 0.03s; full suite 98 passed in 0.16s. 2026-11-06.

## Phase note: P1-P2 (T006-T024)

Full qJig suite after T024: see the T024 receipt above. All P2 behavior is offline and deterministic; test inputs are a few authored strings in test files, not services or datasets. Phase P3 (T025-T038) follows.

## 2026-11-06: T025 complete

- `Support`, `Outcome`, `combine_support` in `src/qjig/logic.py`: (supported,unknown)->TRUE, (unknown,supported)->FALSE, (unknown,unknown)->UNKNOWN, (supported,supported)->CONFLICT, all four distinct; booleans, strings, None and numbers are rejected. Limit: this is the mapping only; nothing yet decides when a side counts as supported (T044/T045).
- Red: ModuleNotFoundError qjig.logic (initial contract). Green: focused 4 passed in 0.03s; tests/test_logic.py 10 passed in 0.03s; full suite 108 passed in 0.16s. 2026-11-06.

## 2026-11-06: T026 complete

- `parse_plan` in `src/qjig/plans.py` validates untrusted plan data into frozen `Plan`/`Predicate`, raising `PlanError` with a named `code`: 17 invalid shapes each give their own code (dangling_ref, dangling_dependency, duplicate_predicate, unknown_operator, dependency_cycle, self_dependency, too_many_predicates, no_predicates, too_deep, not_arity, and_arity, unknown_exact_operator, bad_origin, bad_id, extra_node_key, executable_code_field, bad_node). Boundaries pass: 6 predicates, expression depth 12; depth 13 fails. Limits: a valid plan is not known complete; `exact_operator` names a whitelist only (evaluation is T031); the plan's `origin` is a self-declared label.
- Red: ModuleNotFoundError qjig.plans (initial contract). Green: focused 1 passed in 0.03s; tests/test_plans.py 19 passed in 0.03s; full suite 127 passed in 0.18s. 2026-11-06.

## 2026-11-06: T027 complete

- `Observation`, `Evaluation`, `evaluate` in `src/qjig/logic.py`. Hand-written 16-row AND and OR tables and the 4-row NOT table all match (30 parametrized cases plus a reasons test). Unknown/conflict leaves are returned with predicate id, state and reason; a conclusive operand drops irrelevant unresolved siblings and records the witness; a missing observation is unknown with reason `no_observation`. Limits: leaves are independent here (e.g. A OR NOT A with A unknown stays unknown until T028); precedence choice is recorded as D016.
- Red: ImportError Observation (initial contract). Green: focused 16 passed in 0.03s; tests/test_logic.py 31 passed in 0.03s; full suite 148 passed in 0.19s. 2026-11-06.

## 2026-11-06: T028 complete

- `reachable_outcomes` enumerates every assignment of unresolved ids (unknown, conflict, missing) with known ids fixed and one shared value per id. A OR NOT A with A unknown gives {True} over 2 completions while plain `evaluate` stays unknown; A AND NOT A gives {False}; two free facts give {True,False} over 4; 6 unresolved ids = 64 completions allowed, 7 refused. Limit: it treats unresolved facts as independent free variables (no known logical relationships between distinct predicates).
- Red: ImportError reachable_outcomes (initial contract). Green: focused 1 passed in 0.03s; tests/test_logic.py 33 passed in 0.04s; full suite 150 passed in 0.18s. 2026-11-06.

## 2026-11-06: T029 complete

- `is_material(predicate_id, expression, observations)`: true iff flipping that unresolved predicate changes the result under some completion of the other unresolved ones. Ordinary=false with exception unknown under OR is material; ordinary=true under OR, a known-false AND blocker, a tautology and an already-resolved predicate are not; conflict and missing observations count as unresolved. Limit: shares the independence assumption and 6-unresolved cap of T028.
- Red: ImportError is_material (initial contract). Green: focused 1 passed in 0.03s; tests/test_logic.py 35 passed in 0.04s; full suite 152 passed in 0.19s. 2026-11-06.

## 2026-11-06: T030 complete

- `check_stop(expression, observations, ledger)` in `src/qjig/stopping.py` returns a `StopDecision`. Stop requires one reachable outcome AND no material unresolved obligation: an expression made stable by ordinary=true under OR still cannot stop while a material applicability obligation is open, and can once it is satisfied with evidence. Unstable expressions give `outcome_not_determined`; immaterial obligations do not block; a tautology (A OR NOT A) stops but carries caveat `stable_despite_unresolved_predicates`, as does any stop that leaves unresolved predicates. Limit: which obligations exist and are marked material is decided by the caller; this does not judge completeness of the plan.
- Red: ModuleNotFoundError qjig.stopping (initial contract). Green: focused 1 passed in 0.03s; tests/test_stopping.py 4 passed in 0.04s; full suite 156 passed in 0.20s. 2026-11-06.

## 2026-11-06: T031 complete

- `evaluate_dated_numeric` in `src/qjig/exact.py` (exact Decimal/int comparison; operators eq ne lt lte gt gte). Observation 20 passes the old policy (<=30, effective to 2026-10-31) on 2026-10-15 and fails the new one (<=14, from 2026-11-01) on 2026-11-15, with the applied revision id returned; list order irrelevant; boundaries inclusive. Different field -> unknown, uncovered date -> unknown, unknown-boundary policy -> unknown, two applicable policies -> conflict, other-customer policy ignored, policy recorded after a historical request ignored, a clear policy plus a possibly-applicable one -> unknown (added after I noticed silent resolution). Floats, bools, strings rejected as values. Limit: only simple threshold rules; no unit handling; the field binding is by exact name string and is not itself verified against source text.
- Red: ModuleNotFoundError qjig.exact (initial contract). Green: focused 1 passed in 0.03s; tests/test_exact.py 18 passed in 0.03s; full suite 174 passed in 0.19s. 2026-11-06.

## 2026-11-06: T032 complete

- `next_need(plan, observations, exhausted=)` in `src/qjig/scheduler.py`: considers only unresolved predicates that are material (T029); follows unresolved prerequisites down to the first runnable one (chain c->b->a schedules a, then b, then c even though only c is in the expression); then orders by planner position, then id. Verified deterministic over repeated calls; a dependent listed before its prerequisite still waits; OR already settled or a known AND blocker gives None; exhausted ids are skipped and stop holding back dependents. Limits: the planner-order tie-break leaves the id tie-break unreachable in practice (positions are unique); an exhausted-but-unresolved prerequisite lets the dependent run on unknown input, which later tasks must carry as unknown.
- Red: ModuleNotFoundError qjig.scheduler (initial contract). Green: focused 1 passed in 0.03s; tests/test_scheduler.py 4 passed in 0.03s; full suite 178 passed in 0.20s. 2026-11-06.

## 2026-11-06: T033 complete

- `run_round(state, ctx)` in `src/qjig/acquisition.py` runs next_need -> BM25 -> recover/verify with applicability -> evaluator -> observation, and appends a `TraceRecord` binding request id, predicate, round number, query, hit count, the exact evidence spans (entry, revision, offsets, text hash, text, truncated flag), exclusions and observation. Over two real stored policy revisions the same 20-day fact evaluates FALSE under the 14-day policy in force on 2026-11-15; the old policy is retrieved but recorded as excluded `inapplicable`; the evidence obligation is satisfied; a second call returns None. Truncated/omitted/unusable evidence yields UNKNOWN without evaluating partial evidence. Limits: evaluators are caller-supplied functions (the test's regex extractor is test-local, not a library feature); there is no round cap yet, so repeated calls on a stubbornly unknown predicate would re-run it (T034); one channel per predicate.
- Red: ModuleNotFoundError qjig.acquisition (initial contract). Green: focused 1 passed in 0.05s; tests/test_acquisition.py 2 passed in 0.05s; full suite 180 passed in 0.22s. 2026-11-06.

## 2026-11-06: T034 complete

- `NeedSpec.followup` gives one targeted second attempt (cap `MAX_ROUNDS=2`; `Context.max_rounds` may lower it, values above 2 are rejected). Round 1 'exception' found nothing (UNKNOWN, no_retrieval_hit); round 2 'manager waiver' found the waiver (TRUE). When the followup also fails the third call returns None, the trace has exactly rounds 1 and 2, the predicate stays UNKNOWN, the obligation stays unresolved and `state.refusals` holds one `Refusal(waiver, round_limit)`. With no followup defined, a repeat is refused as `no_targeted_followup`. Limits: the followup query is supplied by the caller (nothing here derives a 'targeted' query); the cap is per predicate, with no request-wide round total or source-change restart yet (T037).
- Red: ImportError Refusal (initial contract). Green: focused 1 passed in 0.05s; tests/test_acquisition.py 5 passed in 0.06s; full suite 183 passed in 0.23s. 2026-11-06.

## 2026-11-06: T035 complete

- `run_until_done` in `src/qjig/acquisition.py`. AND(a,b,c) with a=false: only a is evaluated (verified by call log), stop is True with outcome False, and b and c are recorded as `Skip(kind=witnessed, witnesses=(a,), reason='a=false (a_reason)')` with no observation and no attempts. OR with a=true likewise; when all facts are needed nothing is skipped; predicates outside the expression are `unreferenced`; immaterial predicates with no conclusive witness (e.g. a tautology) are `unwitnessed` and keep their obligations. `ObligationLedger.skip` (obligations.py) records a reason and refuses entity/applicability obligations, which can never be skipped. Limits: skipping waives only predicate-level obligations; touching obligations.py and logic.py (`expression_ids`) went beyond the plan's file list for T035.
- Red: ImportError Skip (initial contract); first green attempt exposed that a skipped predicate's open obligation still blocked the stop, fixed by adding a recorded 'skipped' obligation status. Green: focused 1 passed in 0.05s; tests/test_acquisition.py 8 passed in 0.07s; full suite 187 passed in 0.23s. 2026-11-06.

## 2026-11-06: T036 complete

- Two policy sources both applicable on 2026-11-15 (30 vs 14 days) give observation CONFLICT (`multiple_applicable_policies`) whichever source is ranked higher by BM25 or recorded later (parametrized both ways); both spans are kept in the trace; the obligation is not satisfied and still blocks; stop is False with no outcome; `RunSummary.conflicts` lists the material conflicted predicate. Limits: the conflict here comes from the exact numeric evaluator; semantic-judge conflicts (T044) are not exercised; conflicts are listed, with no rendering or resolution workflow.
- Red: AttributeError RunSummary.conflicts (behavior absent; the existing code already produced CONFLICT via the exact evaluator, but nothing surfaced material conflicts). Green: focused 2 passed in 0.05s; tests/test_acquisition.py 10 passed in 0.07s; full suite 189 passed in 0.22s. 2026-11-06.

## 2026-11-06: T037 complete

- `finalize(state, ctx, summary, mode=, lookup=, rerun=)` in `src/qjig/finalize.py`. Snapshot mode: after the origin moved from a 14-day to a 21-day policy, the run stays bound to the original revision (outcome False), the update is reported as an `OriginUpdate`, and no newer evidence is used. Current-required mode: one restart via `rerun` gives outcome True using only the new revision, and the first run is counted as superseded; a further change after the restart defers with `source_changed_after_restart`; no `rerun` defers with `source_changed_no_restart`; an unreadable origin counts as a change; unchanged origins decide with zero restarts; an already-undecided run stays deferred; unknown mode rejected. Limits: `lookup` and `rerun` are caller-supplied (nothing here reads files or defines how an origin is re-imported); only evidence revisions actually used are checked, not sources that were merely searched; a restart is only counted, not time- or budget-limited.
- Red: ModuleNotFoundError qjig.finalize (initial contract). Green: focused 1 passed in 0.05s; tests/test_finalize.py 3 passed in 0.06s; full suite 192 passed in 0.24s. 2026-11-06.

## 2026-11-06: T038 complete

- Real-subprocess CLI in `src/qjig/cli.py` + `__main__.py`; catalog schema v3 adds per-revision metadata. On a SYNTHETIC fixture (two tiny authored markdown files + a policy JSON in a temp dir, environment with no API keys): import -> ask exits 3, status deferred, within_limit=false, exception=unknown (no_retrieval_hit), providers_called=0; `trace` renders a plain-language account including the plan caveat; importing the waiver source then makes the same ask exit 0 with outcome True. Current-required mode after the origin file is edited exits 3 with source_changed_no_restart; snapshot mode decides and lists the origin update. Bad source id, missing file, boolean budget limit and missing command exit 2 with a message. Limits: the fixture is synthetic mechanics only, not outcome evidence, and should stay on the open-items list as test data; there are no live provider paths (none exist yet); CLI evaluators cover only a numeric threshold and phrase presence; a restart (`rerun`) is not wired into the CLI, so current-required defers rather than re-acquires; file-origin lookup reads local files only
- Red: no CLI existed (python -m qjig: 'No module named qjig.__main__'). Green: focused 1 passed in 0.52s; tests/test_cli.py 3 passed in 1.25s; full suite 196 passed in 1.72s. 2026-11-06.

## 2026-11-06: phases P1-P3 complete (T001-T038)

- 38 of 74 tasks complete. Full qJig suite: 196 passed (`python -m pytest -q`, Python 3.13.9, about 1.7 s). No provider, network or credential is used anywhere in the suite; the CLI test runs real subprocesses with no API keys in the environment.
- Not done / still open: T039-T074 (providers and budgets, browser/two-client use, outcome comparison, clean-install check). `reports/verify_packet.py` asserts all tasks pending and now fails by design (AssertionError at T001); an implementation-aware check has not been written. Nothing has been pushed; local main is ahead of origin.
- Synthetic data in the repo: tiny authored strings inside tests, and the CLI test's temp-dir fixture labeled SYNTHETIC FIXTURE. They prove mechanics only. Removal/replacement with real sources stays on the open-items list.
- Design limits carried forward: plans are authored and completeness is not established; applicability metadata is recorded provenance; topics, role estimates and obligations are in-memory only; CLI evaluators are a numeric threshold and phrase presence; a source-change restart is not wired into the CLI.

## 2026-11-06: T039 complete

- `Journal` and `run_journaled` in `src/qjig/journal.py` (own SQLite file, append-only via triggers, per-request monotonic sequence). The intent is committed before the call: a second connection opened from inside the in-flight call already sees it, and after a simulated process death (BaseException) a fresh open still lists the pending intent with request id, stage, provider, model and input hash. Receipt/failure close an intent; usage with an unknown cost stays None; UPDATE/DELETE blocked; empty fields, bad hash and non-string model rejected before any call (call counter stayed 0). Limits: the 'crash' is simulated in-process, not a killed OS process; provider is the stand-in label only (D018); ordinary exceptions are treated as definite failures here, which T040 refines for uncertain in-flight calls; triggers are a guard, not tamper-proofing.
- Red: ModuleNotFoundError qjig.journal (initial contract). Green: focused 1 passed in 0.03s; tests/test_journal.py 4 passed in 0.04s; full suite 200 passed in 1.18s. 2026-11-06.

## 2026-11-06: T040 complete

- `resume_report`, `Journal.reconcile`, `UncertainOutcome`, `ReconciliationRequired` in `src/qjig/journal.py`. After a simulated crash a repeat of the same call (same request, stage, provider, model, input hash) is refused with the call id and the call counter stays 0 (not even a new intent is written); a different input is allowed; `UncertainOutcome` is journaled as `uncertain` and stays unresolved; after an operator records 'not_executed' (with what was checked) a retry is allowed and journaled; 'executed' also closes it. Reconcile rejects unknown ids, already-closed calls, bad resolutions and blank details. Limits: reconciliation is a recorded human/operator assertion, not verified by code; a retry after 'executed' is allowed as an explicit new paid call (the record shows both); matching is by exact identity, so a changed prompt is treated as a new call.
- Red: ImportError ReconciliationRequired (initial contract). Green: focused 1 passed in 0.04s; tests/test_journal.py 7 passed in 0.05s; full suite 203 passed in 1.19s. 2026-11-06.

## 2026-11-06: T041 complete

- `BudgetLedger` in `src/qjig/budgets.py` derives usage from the journal, so it survives restart. Cap 3: a successful planner call, a failed repair and an uncertain stability probe use all 3; the final check, fallback and escalation are then refused with limit=calls before any intent is written or call made; a second request has its own count. `hold_back_calls` reserves room for later required stages. Tokens: the declared reservation stays committed for failed/uncertain calls and is replaced by actuals when a receipt reports them. Cost: unknown stays unknown (not 0.0), mixed is `partially_unknown`, and known spend at or above the requested cap refuses further calls. No budget, or a zero budget, authorizes nothing. Calls that an operator reconciled as not_executed are not counted. Limits: single writer only (no locking for concurrent writers); the dollar cap applies to known cost only and is not provider-enforced; `run_journaled` gained an optional `intent_payload`.
- Red: ModuleNotFoundError qjig.budgets (initial contract); two of my own test expectations were wrong first (token arithmetic, default call cap) and were corrected in the tests. Green: focused 1 passed in 0.04s; tests/test_budgets.py 4 passed in 0.05s; full suite 207 passed in 1.20s. 2026-11-06.

## 2026-11-06: T042 complete

- `call_typed`, `ProviderRequest`, `RawResponse`, `FieldSpec`, `StandInTransport`, `unresolved_observation` in `src/qjig/providers.py`. Using the labeled STAND-IN transport (D018): HTTP 200 with prose instead of JSON -> failure `malformed_output`, observation UNKNOWN (`provider_malformed_output`), and a journal receipt retains the raw text, its SHA-256, HTTP status, transport label and usage; the call still counts against the budget. Wrong enum value, missing/extra field and non-object JSON -> `schema_violation`; HTTP 500/429 -> `http_error`; a valid response returns the typed value; 7 attempts = 7 counted calls. A timeout becomes `UncertainOutcome` (journaled uncertain); a refused connection is a definite journaled failure; no budget or an empty stand-in never reaches the transport. `run_journaled` receipts accept extra fields. Limits: STAND-IN only, so nothing here shows how a real provider behaves (no real response shapes, rate limits or partial bodies); the schema validator is deliberately small (flat keys, exact type, optional enum).
- Red: ModuleNotFoundError qjig.providers (initial contract). Green: focused 1 passed in 0.04s; tests/test_providers.py 4 passed in 0.05s; full suite 211 passed in 1.23s. 2026-11-06.

## 2026-11-06: T043 complete

- `request_fresh_plan` and `corpus_manifest_sha256` in `src/qjig/planner.py` (`call_typed` now also accepts a validator function). With the labeled STAND-IN transport returning an authored plan: the plan's origin is 'fresh', caveats `completeness_not_established` and `model_generated_untrusted` travel with it, and a `PlanBinding` records request id, order-independent corpus manifest hash, provider, model, prompt hash (equal to the journal intent's input hash), call id and raw-response hash. Changing the corpus or the model changes the prompt hash. Six bad responses (prose, non-object JSON, dangling ref, model-supplied origin, extra code field, seven predicates) give no plan and a named failure (malformed_output, plan_invalid:<code>) while the raw response stays in the journal receipt and the call counts. Limits: STAND-IN only, so no real planner has been exercised; the prompt text is untested against any model; the corpus manifest covers revision ids only, not which spans were visible to the planner.
- Red: ModuleNotFoundError qjig.planner (initial contract). Green: focused 1 passed in 0.04s; tests/test_planner.py 8 passed in 0.06s; full suite 219 passed in 1.21s. 2026-11-06.
