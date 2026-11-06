# qJig handoff — 2026-11-06

## 1. Open items

The user is restarting Codex in `/Volumes/WS4TB/qJig`. They referred to it as the “qRig folder”; the actual repository folder is `qJig`, and the GitHub repository is `qJigRig`.

The current deliverable is a source checkpoint, review, combined design and granular implementation plan. **No new qJig runtime exists. All 74 runtime tasks T001–T074 are pending.** There is no root `pyproject.toml`, `src/qjig` or new qJig test suite yet. The two source apps remain incomplete, though their recorded offline suites pass.

The detailed combined design is proposed for review. The user approved combining the ideas and requested algorithmic steps, small unit tests and a granular build queue; they have not subsequently instructed this session to implement the new runtime. If they say to proceed with the plan in the next session, treat that as authorization to implement the recommended design; do not repeatedly seek approval for routine steps.

No technical blocker prevents T001–T005. Later open work includes semantic plan completeness, trustworthy applicability/evidence support, optional model environment verification, actual role-defined agent use, browser workflow and benefit evaluation. Missing model credentials or local weights must not block the deterministic foundation.

Known baseline caveats:

- Legacy QUIXER and JIG use different hashing/newline/span contracts. Explicit translation is required.
- JIG's source collection builder requires identical scope/effective dates across members. qJig needs independent member validity.
- Hashes and exact quotes do not establish semantic support or source authority. Unknown/conflict and missing exceptions must remain explicit.
- JIG's nested AGENTS.md/TASK_QUEUE.md describe an older pre-implementation state. Do not use them as the current qJig status.
- Two inherited whitespace warnings are preserved in the source checkpoint: JIG docs/03_BENCHMARK_PROTOCOL.md:20 and reference/jigfiles.txt:5026. New review files passed staged whitespace checks.
- The moved `.venv-judge` was not verified after relocation. Do not assume its executable paths still work.

## 2. How to resume

Start the new session with `/Volumes/WS4TB/qJig` as its workspace. This places the new app inside the session's writable root; the previous session needed filesystem escalation because it began in QUIX.

Read this file, then root `AGENTS.md`, `GOAL.md`, `STANDARDS.md`, `IMPLEMENT.md`, `DECISIONS.md`, `PROGRESS.md` and `TASK_QUEUE.md`. Read `SYNTHESIS.md`, `docs/CONTRACTS.md`, `docs/ALGORITHM.md` and the detailed build plan before app-code changes.

```sh
cd /Volumes/WS4TB/qJig
git status --short
git log -4 --oneline
git remote -v
PYTHONDONTWRITEBYTECODE=1 python reports/verify_packet.py
PYTHONDONTWRITEBYTECODE=1 python reports/probe_source_contracts.py
```

At handoff preparation the status was clean, there were no stashes, and both scripts passed. Packet verification reports 17 required documents, 74 pending tasks, an acyclic dependency graph, 149 JIG source hashes and 156 QUIXER source hashes. The probe script reports four reproduced source-contract observations. Python used for the audit was 3.13.9.

`verify_packet.py` is a **review-baseline verifier**: it deliberately asserts that all tasks are pending. Once implementation begins and statuses change, preserve its original baseline evidence and add/update the implementation-aware validation deliberately. Do not treat that baseline assertion as evidence the app is broken, or mark tasks pending merely to make it pass.

Do not run root `pytest` as if it were a qJig runtime suite before T001 establishes discovery boundaries; the repository contains two nested source suites. Their separate commands are documented in README.md. The future `python -m qjig ...` commands in the plan are not implemented.

A suitable next-session instruction is: “Read HANDOFF_LATEST.md and the project controls, then proceed with the recommended plan starting at T001, one focused failing test and one verified behavior per commit.”

## 3. Where things stand

qJig is intended to let agents break a task into specific evidence needs, retrieve the right versioned passages from shared knowledge, evaluate exact or model-dependent claims, and return a traceable answer or explicit deferral. QUIXER contributes document indexing, role metadata, provenance and recovery; JIG contributes explicit subquestions, bounded logic, unknown/conflict states and stopping tests. Whether the combination improves actual agent work remains unproven.

The recommended design is a small new shared core with explicit adapters. A wholesale merge of the two runtimes was rejected because they have different identities, stores, applicability rules and accounting boundaries.

## 4. Verified working

Rechecked during handoff preparation:

- `python reports/verify_packet.py`: passed, source fingerprints and build DAG match.
- `python reports/probe_source_contracts.py`: passed, reproducing different CRLF hashes, rejected mixed-date legacy collection, unresolved material exception and retained conflict.
- GitHub `main` matched local review commit `d471390b413aa106b4e1ffb35795d0f512c062b3` before this handoff commit.
- Root working tree was clean and `git stash list` was empty.

Full source suites were run in the immediately preceding review, not rerun merely to write this document:

- QUIXER: 263 Python tests passed; existing SWIG deprecation warning.
- Switch experiment: 33 tests and TypeScript typecheck passed.
- Moved JIG: 250 offline tests passed; frozen copy also passed 250 after correcting audit copy/cwd setup errors. Prior failed audit-harness logs are retained separately.
- JIG private-KB fixture: 18/18 authored reference decisions across three modes; evidence payload reduction is measured, inference accuracy/cost/latency is not.

Evidence: `VALIDATION_REPORT.md`, `reports/source-test-receipts.json`, source logs, `reports/packet-verification.json` and `reports/compatibility-replay.json`. These are source/review evidence, not completed qJig runtime tasks.

## 5. Unverified or partial

No combined app, fresh qJig planner/judge run, new browser walkthrough, local model installation, actual live swarm use or independent outcome study has been demonstrated. Existing source model smokes and exploratory AI review cannot be pooled into a new qJig result.

Hy4 (`tencent/hy4`) remains the user-selected escalation model. Reflex remains optional and experimental because prior QUIXER decisions changed with option order. No automatic model promotion or calibrated threshold is justified by these observations.

Source licenses/provenance were not fully established for distribution; preserve attribution and review substantial imported code before further publication/reuse. The user explicitly requested and authorized publishing the local source checkpoints and planning packet to qJigRig; that initial push is complete.

## 6. Placeholder, mock, or synthetic data still present

The source suites contain deterministic/fake provider responses. JIG `workbench/fixture.py`, `Private_KB_Decision_Pilot/`, its evaluation/gold.json and `reports/jig-private-fixture.json` contain authored synthetic exercises. QUIXER source experiments include synthetic conflict/stale/unsupported findings. These were retained as approved regression/research inputs, not real-world outcomes.

No new qJig fixture runtime has been implemented. Planned authored graphs are diagnostic controls; fresh model-generated decomposition will be a distinct later path. Keep reference labels and arm mappings outside all indexed/model-visible corpora.

Credentials, virtual environments, generated source-app data and caches remain ignored. A local `.env` exists in the moved JIG folder; the old QUIX configuration is `/Volumes/WS4TB/QUIX/.env`. Their contents were not printed and their current model access was not revalidated. Use configured loaders and presence checks when later authorized live work requires them.

## 7. Recent changes

Repository: `/Volumes/WS4TB/qJig`, branch `main`, origin `https://github.com/deesatzed/qJigRig.git`.

- `da1397b`: checkpointed both source inputs plus provenance so integration can be traced and rolled back.
- `d471390`: committed the audit, recommended shared-core design, contracts, algorithm, risks, verification receipts and 74-task test-first build queue. Both commits were pushed to origin/main.
- This dated handoff and HANDOFF_LATEST.md are the only files added by the handoff operation. The handoff is committed locally according to the handoff workflow; it is not pushed by that operation. Thus local main will be one documentation commit ahead of origin until the next authorized push.

Additional source checkpoints:

- QUIXER commit `1790086a5d3b178957ce80324c0f283dbcf78c97`, archived under `sources/quixer/`, and GitHub tag `checkpoint/quixer-before-qjig-2026-11-06`.
- JIG moved source tree fingerprint and 149 per-file hashes in `plan/source-checkpoints.json` and `plan/jig-source-hashes.json`.
- HITMCockpit integration commit `08a49cce014453afdb7be5e4a9909c2416454cf9` remains in `/Volumes/WS4TB/QUIX/hitm-quix-worktree`; it is not copied into qJig and has no configured remote. qJig's early milestones do not require Swift.

## 8. Next steps

1. Resume from the reviewed/proposed design. If the user directs implementation, begin T001 rather than another broad audit. Done: isolated package, explicit test discovery and import-with-no-IO test pass.
2. T002–T005: request round-trip, malformed-budget rejection, exact byte/text identities and portable source identity. Done: each behavior has a named observed-red then passing focused test, scoped commit and queue receipt.
3. Complete P1 (through T012): canonical spans and legacy translation, immutable revisions, entity/date applicability. Done: tiny counterexamples prove shared contract agreement.
4. P2–P3: indexing/acquisition followed by pure logic/stopping and the deterministic CLI at **T038**. Done: a real subprocess produces a trace and defers for a missing material exception without provider calls. IMPLEMENT.md has a minor later-command reference to T039; the detailed queue correctly places the CLI slice at T038.
5. Only then add P4 provider/journal/budget paths, P5 actual browser/two-client use and P6 isolated benefit comparisons. Every task has files, dependencies, test name and acceptance behavior in the plan.

Use one observable behavior per task: write focused failing test, run and inspect failure, implement minimal behavior, run focused/nearest regressions, commit and record actual evidence. Never close a task because a source project's tests pass. Avoid broad rewrites, unrequested multi-agent delegation, inherited absolute runtime dependencies or live calls in offline tests.

## 9. Key files

- `AGENTS.md`: root working rules and source boundaries.
- `GOAL.md`: intended product and completion gates; overall goal remains incomplete.
- `SYNTHESIS.md` / `SOURCE_AUDIT.md`: approach selection, implemented source mechanisms and gaps.
- `docs/CONTRACTS.md` / `docs/ALGORITHM.md`: canonical records and deterministic acquisition/reasoning procedure.
- `docs/TEST_STRATEGY.md`: mandatory small counterexamples and evidence levels.
- `TASK_QUEUE.md` / `plan/tasks.json`: next tasks and machine-readable dependencies/status.
- `docs/plans/2026-11-06-qjig-build.md`: exact per-task test/implementation/commit steps.
- `VALIDATION_REPORT.md` / `reports/`: actual source/review evidence and limits.
- `DECISIONS.md` / `PROGRESS.md`: rationale, safe assumptions and completed review work.
