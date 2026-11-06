# Autonomous Swarm Retrieval Implementation Plan

> **For Codex:** Use the available `executing-plans` skill and the project's `AGENTS.md`; execute and verify tasks in order. This document is a plan, not a claim that its proposed components exist.

**Goal:** Build and evaluate a read-only HITMCockpit-to-QUIX retrieval path, a switch-guided document-navigation prototype, and matched retrieval and agent-task comparisons.

**Architecture:** QUIX remains the owner of its source catalog, indexes, role scores and evidence links. A versioned, bounded local request exposes a read-only context packet to an isolated HITMCockpit caller; switch consumes a bounded QUIX candidate snapshot and controls evidence-gathering steps, with no direct catalog mutation. A separate experiment runner compares the variants and actual agent outputs against fixed task sets and budgets.

**Tech stack:** Python 3.11+, SQLite, pytest, optional tiktoken and PyMuPDF; Swift 6 / HITMCore; Node.js 22.18+, TypeScript, pnpm, switch; OpenRouter Decisions using the existing `.env`.

---

## Starting point and authority

- Work in `/Volumes/WS4TB/QUIX/quix-knowledge-worktree` on `research-slice`; HITMCockpit is `/Volumes/WS4TB/QUIX/HITMCockpit/HITMCockpit`; switch is `/Volumes/WS4TB/QUIX/switch`. Inspect each repo's `AGENTS.md`, control files, Git status, branch and HEAD before editing it. Preserve existing changes and untracked files, including `.DS_Store`; do not reset or clean worktrees.
- The user approved the five proposed tasks and candidate headings and the read-only first slice in `docs/hitm-read-adapter-proposal.md`. Those candidate headings were originally implementation-suggested, have not been shown exhaustive, and are **not independently authored labels**. The fifth task's suggested provider-evaluation document is outside the original two-document corpus. Keep the existing blind packet intact; work on copies. Do not call any labels independent without the actual reviewer and procedure to support that claim.
- `src/quix_knowledge/hitm.py` provides an in-process version-1 Python contract, checks current source revisions before and after retrieval and produces a JSON-character-budgeted packet. It is not a transport or an HITMCockpit caller. Source checks are point-in-time; the consumer must revalidate before using returned evidence.
- Existing five-task all-section experiment: offline role ranking matched the baseline ordering; live role and decision variants fell back after unclear model judgments. See `PROGRESS.md` and `.local/approved-complete-roles-{offline,live}.json`. Treat this as a small exploratory result, not a quality or cost claim.
- Approved first slice does **not** authorize a live swarm connection, MindStore export, automatic promotion, write-back or agent dispatch. It does authorize implementing and exercising an isolated, read-only adapter and controlled non-sensitive experiments. Preserve HITMCockpit's existing policy, destination and gate checks. A change to the live swarm or MindStore requires a separate user decision, after the proposed change is concrete and reviewable.
- Use `/Volumes/WS4TB/QUIX/.env` through existing loaders for OpenRouter. Never print, commit or pass keys in process arguments. Use explicit model IDs, bounded calls and actual usage receipts; default to the existing model slot 2 when available. No threshold becomes operational until the relevant model/question/role has independently reviewed development evidence and separate held-out evaluation.
- Do not use scores as truth, suppress evidence because a role score is low, or turn source records into agent findings. Unknown, unstable, malformed and unavailable results remain explicit. Preserve original sections even when indexes are absent or proposals are unreviewed.
- Treat shell/network access and writable roots as enforced by the environment. If an authorized action actually requires an unavailable permission, follow the sandbox escalation mechanism; do not work around it. No production deployment is part of this plan.

## Working rules

1. Follow `@test-driven-development` for behavioral changes: add a meaningful test, observe its expected failure, implement, and rerun the focused test. Preserve test artifacts and failure evidence where relevant. Run only additional tests justified by the changed surface.
2. Record decisions, assumptions, revisions, bounded costs, test commands and open gaps in `PROGRESS.md`; update `DECISIONS.md` only if it exists or a durable decision warrants creating it. Do not overwrite `.local/blind-review-packet.json` or its catalog.
3. Keep user-approved candidate labels distinct from newly acquired independent labels, fixture labels, model judgments and agent outputs. Do not ask a model to supply labels and then call them independent.
4. Complete each phase's independent work even if a later evidence gate is unmet. Report a gate as open with the exact missing artifact; do not fabricate the artifact, equate a timeout with failure, or block the whole plan when useful work remains.
5. Commit only the files belonging to a finished, verified slice. The earlier user instruction authorized commit and push to the existing QUIXER remote; confirm the actual branch and remote before pushing. HITMCockpit and switch are separate repositories: do not push or merge their changes merely because QUIXER was authorized.

## Phase 0 — Reconcile live state

### Task 0.1: Inventory and pin inputs

**Inspect:** `PROGRESS.md`, `docs/evaluation.md`, `docs/hitm-read-adapter-proposal.md`, `docs/switch-assessment.md`, `src/quix_knowledge/{hitm,context,experiment,retrieve}.py`, `tests/test_hitm_contract.py`, HITMCockpit's `Sources/HITMCore/{PlannerAgent,MindStore,MindTypes}.swift`, switch's `src/core/{loop,pick,replay}.ts` and `src/models/pi-ai.ts`.

1. Read all present project control files and each repository's applicable instructions. Capture `git status --short --branch`, `git rev-parse HEAD` and `git remote -v` for each repository without modifying them.
2. Verify the approved local review packet, pilot catalog, source revisions, existing Python environment, `swift --version`, `node --version`, `pnpm --version` and switch dependency availability. Report missing tools as missing; never download a model or install packages implicitly when this violates local constraints.
3. Run `python -m pytest tests/ -q` and `git diff --check` in the QUIX worktree. Record actual outcomes and the baseline. If the HITMCockpit baseline is needed, run `swift test` in its package directory and distinguish pre-existing failures from changes.
4. Write an execution receipt in `PROGRESS.md` with exact pinned heads, selected corpus, model slot, and assumptions. Do not record secret values.

**Acceptance:** Baseline and provenance are recorded; source paths and authorization boundaries match current reality.

## Phase 1 — Read-only HITMCockpit adapter

### Task 1.1: Harden and expose the QUIX request boundary

**Modify:** `src/quix_knowledge/hitm.py`, `src/quix_knowledge/__main__.py`, `tests/test_hitm_contract.py`; add `tests/test_hitm_cli.py` if needed. **Update:** `docs/hitm-read-adapter-proposal.md`.

1. Define a versioned request with `version`, `task`, `role`, `role_version`, nonnegative `limit`, and `budget_characters`; accept no model-supplied code, paths or shell arguments. Use an explicit, locally configured catalog path. Keep the existing `retrieve_context` API and specify structured, machine-readable error outcomes for malformed requests, unavailable catalog, changed/unreadable source and budget too small.
2. Add a one-shot CLI command, for example `hitm-context`, reading a JSON request from stdin and emitting exactly one JSON response. Run it as a child process with an argument vector; no shell. This is a local transport for a controlled caller, not a network service. Bound input and output, execution time and process environment. Do not modify the catalog while answering: check whether current `open_catalog` performs migration or `search` commits, and implement a genuinely read-only opening path or an isolated immutable snapshot without bypassing schema validation.
3. Return the packet's catalog fingerprint, exact source path/revision/anchors, role/version, lifecycle and evidence status, fallback and truncation fields. Use the existing canonical serialization to enforce a **packet character budget**, and separately document response-envelope and eventual full-prompt budgeting. Do not describe character counts as model tokens.
4. Revalidate text using the exact universal-newline UTF-8 hashing convention and PDFs using raw-byte hashes. Verify again after retrieval. The caller must revalidate the referenced source revisions immediately before use; report any missing/unreadable/changed source, including changes after the first check. A source check cannot guarantee a later filesystem read will stay unchanged.
5. Tests: malformed/version/type/budget inputs; valid role/version; exact source and span/page anchors; truncation and empty/budget-too-small cases; text CRLF and PDF revisions; source removed or changed before/during retrieval; catalog changes; unsupported/stale record labeling; no database writes; subprocess timeout/unavailable/malformed output. Test uncertain model behavior separately if a provider is wired; never claim it is covered by provider-free tests.
6. Run `python -m pytest tests/test_hitm_contract.py tests/test_hitm_cli.py -q` (adjust names to the implemented tests), then the full Python suite and `git diff --check`.

**Acceptance:** A one-shot, source-checked context request works without writing the catalog and reports failures explicitly; no listener or HITMCockpit state changes exist.

### Task 1.2: Isolated HITMCockpit caller

**Create:** `HITMCockpit/Sources/HITMCore/QuixContextAdapter.swift` and `HITMCockpit/Tests/HITMCoreTests/QuixContextAdapterTests.swift` in the HITMCockpit repository; change `Package.swift` only if actually required.

1. Define an injectable async transport and typed Codable request/response. Provide an isolated local process transport with fixed executable and arguments, bounded output, timeout/cancellation and structured errors. Keep a fake transport for deterministic tests. Do not read `.hitm` directly or alter `MindStore`, destinations, gates or `AgentAdapter.propose` semantics.
2. Verify protocol version, required fields, source status and source revision before use. Reject unsupported/stale evidence or expose its explicit status according to the existing consumer policy; never relabel it as verified. Preserve the catalog fingerprint, truncation and fallback fields.
3. Add tests for happy path, malformed JSON, nonzero exit, timeout/cancellation, unknown version, stale/deleted source, role/version mismatch, oversized output and missing evidence. Assert no calls write to MindStore, and run the existing MindStore/Planner policy tests.
4. Run `swift test` from `/Volumes/WS4TB/QUIX/HITMCockpit/HITMCockpit`; additionally run the narrow test filter during iteration. Record any platform/toolchain limits and the exact repo commit independently of QUIX.
5. Exercise the real one-shot Python/Swift boundary locally with a temporary non-sensitive catalog and no live swarm. Save a compact receipt containing input schema/version, catalog fingerprint, path/revision checks, pass/fail and elapsed time, but no key or unnecessary document body.

**Acceptance:** An isolated HITMCockpit component can request and validate read-only QUIX context, fails closed on bad input or unavailable sources, and existing HITMCockpit policy tests pass. This does not claim a live swarm integration.

## Phase 2 — Switch-guided navigation

### Task 2.1: Minimal domain and deterministic replay

**Create in QUIX worktree:** `experiments/switch-navigation/package.json`, `tsconfig.json`, `src/domain.ts`, `src/quix-snapshot.ts`, `tests/domain.test.ts` and a short `README.md`. Prefer the local pinned switch checkout as a development reference; use a declared dependency and lockfile only if the local environment can resolve it. Do not edit switch's repo to implement this domain.

1. Specify a versioned case with task, role/version, catalog fingerprint, source-revision-bound candidates and a step/character budget. Use fixed actions: `inspect_topic`, `inspect_span`, `broaden`, and `stop`. Choices are generated from actual QUIX IDs; the model never supplies executable code or arbitrary paths. State distinguishes source text, agent-produced findings, evidence status and unverified metadata.
2. Use switch's state-machine, bounded `picking` and trace/replay interfaces. Bound candidate count, model calls, steps and total view size. Check source revisions before inspection, and record chosen IDs, spans, costs, failures, stop reason, model/definition versions, and truncation. `unknown`, malformed output, timeout, invalid choice or exhausted budget yields explicit fallback to baseline or a labeled insufficient-evidence result.
3. Write tests using switch's fake decider: legal and illegal choices, duplicate/loop prevention, stop, budget exhaustion, changed source, missing candidate, explicit fallback, and deterministic replay without another model call. Verify that no topic/role proposal becomes accepted and no source or catalog is modified.
4. Run the package's focused test command and typecheck. Record switch's pinned commit and dependency versions; check its MIT license before copying code.

**Acceptance:** A local deterministic run can navigate a fixed QUIX snapshot and replay the trace, with bounded operations and no model or external service.

### Task 2.2: Provider bridge and live smoke

**Create/modify:** `experiments/switch-navigation/src/openrouter-decider.ts`, tests alongside the domain, `README.md` and `PROGRESS.md`.

1. Inspect `switch/src/models/pi-ai.ts` and the installed registry; do not assume OpenRouter's `/decisions` is supported. If directly supported, prove the exact configured model and request/response through a smoke call. Otherwise implement a custom switch `Decider` bridge to the existing QUIX OpenRouter behavior or a minimal System One client, with explicit request shape, model resolution, error and usage mapping. No credentials in traces.
2. Contract-test the bridge against captured synthetic fixtures for typed choices, invalid/missing options, errors, timeout, usage absent and option-order instability. Treat unsupported outputs as unknown; do not equate a model probability with calibrated correctness. Ensure a fallback does not silently exceed the action or token budget.
3. Use `.env` and one non-sensitive task for a capped live run, recording actual calls, usage, latency and status. Failure or missing dependency is a reported blocker for the live adapter, not proof that switch works or fails as a framework.

**Acceptance:** Either a real model-backed navigation trace with source-bound evidence and actual usage, or a precise reproducible provider/dependency blocker; fixture tests alone are labeled as such.

## Phase 3 — Matched retrieval comparison

### Task 3.1: Prepare evidence and preregister comparison

**Modify/create:** `docs/evaluation.md`, `experiments/retrieval/manifest.json`, `experiments/retrieval/README.md`, `tests/test_run_experiment.py`; keep raw reviews and reports under `.local/` unless explicitly suitable for publication.

1. Freeze a non-sensitive corpus revision, role definitions, source granularity, query IDs, index/provider versions, model prompts, context serialization, budget, result limits, and cost-accounting plan. Include the original two design documents and explicitly include the provider-evaluation document if it is needed for the fifth task; regenerate IDs in a new catalog. Do not reuse path-dependent IDs across catalogs.
2. Keep the five approved headings as `user_approved_candidate` provenance. Construct a broader balanced implementation/review task set covering no headings, broad topics, changed/stale sources, contradictory/unsupported agent findings and role distinctions. Fix development and held-out assignment before threshold selection; group related tasks/sources to reduce leakage. Record that a split alone does not establish independence.
3. Generate a blind reviewer packet with exact source revisions and no rankings. An independent reviewer must inspect the corpus, identify all relevant anchors and missing evidence, and record reviewer/date/provenance. If no independent reviewer is available, run only the explicitly labeled exploratory study, leave independent-quality claims and calibration open, and proceed to infrastructure and synthetic checks.
4. Preregister a common task set, matched candidate scope and packet budget, success/failure definitions, primary metric (e.g. per-task recall at a fixed budget), secondary precision/stale/unsupported rates, and how missing labels and truncated evidence are handled. Separate task relevance from role boost; record provider failures, observed latency, reported usage/cost and indexing cost separately. Do not invent production thresholds or claim statistical power from five tasks.

### Task 3.2: Execute and analyze

**Modify/create:** `src/quix_knowledge/experiment.py`, switch experiment runner, `tests/test_run_experiment.py`, `reports/` sanitized manifest and summary only when safe.

1. Run baseline, topic, role and decision variants with `--matched-candidates`; run switch on the same pinned candidate set, query, role and serialized-packet budget. If switch uses a different candidate set or budget, label that comparison unmatched and do not attribute the difference to the model alone. Preserve same query IDs and corpus fingerprint; match full available prompt budgets as far as model tokenizers allow and record differences.
2. Include every scheduled task and report missing labels, unanswerable cases, unknown calls, dropped/truncated evidence and provider failures. Keep independent held-out results separate from tuning. Report role rankings with and without role scores and decision gating with and without model calls; explicitly report if fallback makes variants identical.
3. Execute existing fixtures and the user-approved five-task exploratory comparison even without new independent labels; never substitute its metrics for the independent study. Compute summaries only over the same eligible tasks, list task IDs and per-split counts, and separately report operational and indexing costs. Preserve provider-reported missing costs as unknown.
4. Save exact commands, revisions, model/role versions, label provenance, receipts, case-level results and sanitized comparison. Do not infer that exact-ID matches prove a truncated passage contains evidence. Repeat only when needed to resolve a failure or stated uncertainty.

**Acceptance:** A reproducible matched experiment and clearly labeled results exist. A comparative-quality claim requires independently reviewed sufficient labels and a defensible held-out analysis; otherwise the report states the limitation and gives the next reproducible action.

## Phase 4 — Agent-task comparison

### Task 4.1: Controlled isolated agent runner

**Create:** `experiments/agent_tasks/README.md`, `manifest.json`, `run.py`, and `tests/test_agent_task_runner.py`; reuse the real HITMCockpit caller only after Phase 1 passes. A fixture agent may test orchestration but must never be reported as real agent performance.

1. Define paired conditions on identical tasks: no QUIX context, baseline QUIX, role-aware QUIX, and switch-guided QUIX when available. Use isolated non-sensitive project copies and the same agent model, task text, tool permissions, output requirements and full request budget. Randomize or counterbalance order, record seeds and runs, and prevent one condition from seeing the other's output or labels.
2. Capture actual agent outputs, citations, source revisions, model/provider/version, prompt/context budgets, fallback reasons, tool errors, wall-clock times, provider-reported costs and local-compute unknowns. Keep agent outputs separate from source material and catalog records. Do not write to HITMCockpit MindStore, change live agent dispatch, or promote findings automatically.
3. Add tests for paired-task consistency, isolation, missing results, timeouts, replayable manifests, ordering, cost unknowns and preserving failure cases. Run fixture-based tests and label them synthetic.
4. Conduct a bounded live run only using authorized non-sensitive data and existing configured credentials. If an actual agent runtime is unavailable, report that exact blocker and retain the runnable harness and fixture results; do not call simulated answers real.

### Task 4.2: Outcome review and final gate

**Create:** `experiments/agent_tasks/review-packet.md`, a machine-readable review schema, and a sanitized summary under `reports/`; update `PROGRESS.md`.

1. Prepare anonymized, shuffled agent outputs and fixed rubrics for correctness, source support, missing evidence and task completion; record actual independent reviewer identity and procedure. Keep agent conditions hidden until review is complete. Do not convert a model's self-review into an independent outcome.
2. Report per-task paired outcomes, missing runs, confidence limitations, source verification, latency/cost and all failures. A five-task exploratory pilot is not sufficient to establish improvement. Do not claim a live swarm benefit from an isolated runner.
3. Run final applicable Python, TypeScript and Swift tests, source-revision checks and `git diff --check` in each changed repo. Record exact commands, exits, commits and remaining gaps. Push only authorized QUIXER commits; leave separate-repo commits and push decisions explicit.
4. If the user later wants a live swarm connection, first present the exact transport, destination/policy behavior, tests, deployment scope and resulting changes for separate approval under the approved proposal. Do not start it as a side effect of this plan.

**Acceptance:** An isolated real-agent comparison and independent outcome review support only the claims their evidence warrants; otherwise the remaining missing evidence is explicitly identified and the goal stays incomplete.

## Definition of done

- The isolated read-only adapter works end to end and source freshness, failure behavior, budgeting and HITMCockpit policy boundaries have been tested.
- The switch domain runs with a fake and a real configured provider, records/replays decisions, and either works against the same frozen QUIX candidates or records a specific external blocker.
- A reproducible matched retrieval comparison and a controlled actual-agent comparison exist; independent review, held-out evidence and real results are required for any claim of benefit.
- Results, source links, corpus/model versions, costs and limitations are durable; no sensitive content or keys are committed, and no live swarm or MindStore write has been silently enabled.
