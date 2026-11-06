# Source review: 2026-11-06

Review scope: goals/audits, data contracts, ingestion/indexing/retrieval, state composition/stopping, provider boundaries, program lifecycle, experiment journals and targeted tests. Both full offline suites were rerun. Existing GUI and local-judge claims were read from their evidence documents; neither a new browser walkthrough nor local inference nor paid calls was performed. This is a targeted architecture/completeness audit, not an exhaustive security audit or proof of semantic correctness.

## QUIXER

Checkpoint: `1790086a5d3b178957ce80324c0f283dbcf78c97`, `research-slice`, pushed; annotated remote checkpoint tag recorded in README. Code references below use the archived `sources/quixer/` tree.

| Surface | Implemented evidence | Incomplete or limiting behavior | qJig action |
|---|---|---|---|
| Catalog | [store.py](sources/quixer/src/quix_knowledge/store.py), schema version 7, foreign keys, records/evidence/index/role tables | Single logical writer, no general swarm transaction service | Preserve identities; add immutable blob manifest and writer service |
| Text ingestion | [ingest.py](sources/quixer/src/quix_knowledge/ingest.py:25), heading anchors and generated fallback | IDs include resolved path; universal-newline text hash; semantic section quality unverified | New portable identity and explicit hash/span translation |
| Indexing | [indexing.py](sources/quixer/src/quix_knowledge/indexing.py:99), extractive paragraph proposals with offsets, topic receipts | Provisional labels; long spans/titles heuristics; no evidence of superior learned topics | Adapt derived-index model; benchmark granular retrieval |
| Retrieval | [retrieve.py](sources/quixer/src/quix_knowledge/retrieve.py:20), lexical/BM25/topic/role variants | Whole catalog scan; bounded shortlist can omit decisive exception regardless of soft boost; scores uncalibrated | Separate evidence obligations from ordering hints |
| Source recovery | [evidence_recovery.py](sources/quixer/src/quix_knowledge/evidence_recovery.py:28), source/span checks, exclusions and alternatives | Point-in-time; PDF text not re-extracted; links do not prove claims | Bind immutable run evidence and keep assurance states |
| Agent endpoint | [hitm.py](sources/quixer/src/quix_knowledge/hitm.py:59), role-ranked recovery packet, read-only CLI | Research catalog snapshot cap 100; no live swarm service; Swift adapter separate | New role-defined client protocol in Python first |
| Provider gating | [decisions.py](sources/quixer/src/quix_knowledge/decisions.py:11), unknown/fallback and metadata; research cascade | Reflex order instability; two latest Hy4 invalid responses; empirical thresholds absent | Optional gates; include repair/fallback costs and measured failure states |
| Evaluation | [latest pilot](sources/quixer/reports/2026-11-06-recovery-pilot.json), six tasks, 22/24 proposals | Prior corpus exposure; AI labels unvalidated; one review unknown; mostly partial/inadequate outputs | New isolated comparisons and reference separation |

Full current QUIXER suite: 263 passed on Python 3.13.9, existing SWIG warning. Switch: 33 passed, typecheck passed. These establish the tested source mechanisms, not agent benefit. No new Swift run was made in this review; previous boundary verification is preserved in source PROGRESS.md.

## JIG workbench

The moved package is not a Git repository of its own; the local root qJig now preserves its selected source baseline with per-file hashes. `AGENTS.md` and `TASK_QUEUE.md` are stale relative to actual implementation. `RESULTS.md` and `ACCEPTANCE_AUDIT.md` are more candid descriptions, but also describe earlier test counts; this review observed 250 tests.

| Surface | Implemented evidence | Incomplete or limiting behavior | qJig action |
|---|---|---|---|
| Snapshots | [core.py](Decision_Program_Codex_Handoff/workbench/core.py:30), atomic append-only JSON publishing and source hashes | Run/storage/model/UI concerns concentrated in core; hashes are not authentication | Retain immutability, separate domain from IO |
| Collections | [collections.py](Decision_Program_Codex_Handoff/workbench/collections.py:17), source members and citation mapping | Requires all sources to share exact scope and effective dates; joins text | Per-member validity and independent spans |
| Plan validation | [core.py](Decision_Program_Codex_Handoff/workbench/core.py:254), six predicates and bounded AST | Valid syntax cannot establish complete decision conditions or opposed claims | Record plan status/obligations; semantic review remains explicit |
| Logic/stopping | [core.py](Decision_Program_Codex_Handoff/workbench/core.py:275), completion enumeration and predicate relevance | At most six refs; proof applies only to generated expression | Reimplement as pure bounded functions with invariant tests |
| Local judge | [local_judge.py](Decision_Program_Codex_Handoff/workbench/local_judge.py:29), false support -> unknown; paired support -> conflict | Threshold exploratory; positive/negative claims can be semantically wrong; full context not local quote | Strict typed adapter; exact operators for exact facts |
| Retrieval | [retrieval.py](Decision_Program_Codex_Handoff/workbench/retrieval.py), scoped spans and source bindings | Lexical heuristics tied partly to Python docs; no general topic/role catalog | Use QUIXER methods behind canonical evidence requests |
| Program lifecycle | [programs.py](Decision_Program_Codex_Handoff/workbench/programs.py:46), exact request/snapshot binding | Reuse intentionally narrow; self-reported review not independent assurance | Keep lifecycle, do not generalize from matching title |
| Run recovery | [datasets.py](Decision_Program_Codex_Handoff/workbench/datasets.py:147), locks, call intents, receipts, runtime pins | Protection is specific to dataset pipeline, not a general multi-agent service | Request-wide ledger and single writer |
| Evidence assurance | [ACCEPTANCE_AUDIT.md](Decision_Program_Codex_Handoff/ACCEPTANCE_AUDIT.md), candid A7 failure | Forged instruction and wrong-relationship semantics unresolved; heuristic guard narrow | Adversarial regressions; do not assert support from exact quote |
| Browser/service | [HTTP handler](Decision_Program_Codex_Handoff/workbench/__main__.py:109), source/program/run views and in-process background jobs | Core run routes are synchronous; daemon jobs are process-local and are not a general swarm service | Thin API/UI over new trace; durable request state below workers |
| Private-KB pilot | [README](Decision_Program_Codex_Handoff/Private_KB_Decision_Pilot/README.md), 18 cases, keyed records and dates | Authored scheduler, zero live calls, no measured inference cost/latency | Use fixture controls, not fresh-planner result |

Full moved-folder suite: 250 passed. Frozen-copy suite: 250 passed after correcting this audit's copy filter to include `.rst` fixtures and running from its root. The first two frozen-copy failures were review-harness setup errors, not demonstrated application defects; raw logs are preserved. Optional model dependencies and moved `.venv-judge` were not verified; moved virtualenvs can contain old absolute interpreter paths.

## Compatibility probes actually run

See [results](reports/compatibility-probes.json).

- Identical CRLF source bytes give different legacy hashes: QUIXER normalizes universal newlines; JIG's raw snapshot preserves them. Do not equate these identities.
- JIG rejects a collection containing old and new policy versions with different effective intervals. Historical decision corpora need per-member applicability.
- With `ordinary OR exception`, ordinary=false and missing exception yields unresolved; the exception is material. Preserve that behavior.
- Positive and negative support both present yield conflict. Preserve conflict explicitly through the catalog and planner trace.

## Prioritized findings

1. P0 integration: ambiguous source hash/span contracts could attach the wrong text to an apparently valid citation. Resolve before adapting either runtime.
2. P0 reasoning: no matching passage, no source, inapplicable rule and proven negative are distinct. Exceptions need an explicit coverage obligation.
3. P0 trace: incomplete generated plans can yield a stable but wrong answer. Stability is conditional on graph completeness; never promote it to semantic proof.
4. P0 measurement: source test counts, fixture size savings and model outputs are different evidence. Compare direct RAG, decomposition and their combination under pinned inputs and full accounting.
5. P1 dates: mixed rule versions, entity-specific overrides and observation dates need independent fields and tests.
6. P1 roles: usefulness is an uncalibrated prior; evidence mandatory to a task cannot be filtered away by another agent's preference.
7. P1 operations: nested provider budgets, retries and request journals need one owner; uncertain calls must not be replayed blindly.
8. P1 scope: neither codebase implements a proven live agent swarm or validated semantic verifier. Build a small actual client flow and measure it.
9. P2 scale: catalog scans, 100-candidate snapshots, full-source local judge contexts and worker cold starts need separate profiling after correctness.
10. P2 documentation: stale nested instructions and historical results require dated evidence and a source manifest.
