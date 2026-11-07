# qJig

qJig is a local evidence and decision workbench under development for agents. It combines QUIXER's versioned document catalog and role-aware retrieval with JIG's explicit decision questions, bounded reasoning, unknown states and controlled interventions.

**Current status:** the Python/SQLite deterministic core, authored CLI, provider boundaries and a fresh-plan pipeline exist. A local browser foundation supports source import and authored deterministic controls; the full browser journey, shared-client workflow, resource controls and evaluation remain incomplete. Fresh generated plans remain deferred when coverage is unestablished. Passing tests or source-project probes does not establish a quality improvement.

Start with [the synthesis](SYNTHESIS.md), [source audit](SOURCE_AUDIT.md), [algorithm](docs/ALGORITHM.md), and [build queue](TASK_QUEUE.md). The [full implementation plan](docs/plans/2026-11-06-qjig-build.md) gives a focused test and commit procedure for every task. [GOAL.md](GOAL.md) defines completion and [VALIDATION_REPORT.md](VALIDATION_REPORT.md) records what was actually run.

## Source checkpoints

- `sources/quixer/`: exact tracked files from QUIXER `1790086a5d3b178957ce80324c0f283dbcf78c97`, archived from the committed tree. GitHub tag `checkpoint/quixer-before-qjig-2026-11-06` preserves the source commit.
- `Decision_Program_Codex_Handoff/`: the user's moved JIG workbench. Selected code/docs/fixtures are fingerprinted in `plan/jig-source-hashes.json`. Local credentials, datasets, environments and generated records are excluded from Git.
- The separate HITMCockpit adapter is recorded at `08a49cce014453afdb7be5e4a9909c2416454cf9`; it remains in its own local worktree. The first qJig milestones do not require Swift.

The source folders are review inputs, not the location for new qJig implementation. New runtime code belongs in `src/qjig/`; follow the active queue and GOAL.md. The JIG source AGENTS.md describes an older pre-implementation state; consult its actual code and current audit for capabilities. No upstream source file was rewritten to fit this design.

## Verified source commands

From `sources/quixer`: `python -m pytest -q` (requires pytest and optional installed dependencies for their corresponding tests).

From `Decision_Program_Codex_Handoff`: `PYTHONDONTWRITEBYTECODE=1 python scripts/offline_tests.py` (stdlib core; the guard covers network operations inside that test process, not arbitrary children).

From `Decision_Program_Codex_Handoff/Private_KB_Decision_Pilot`: `python pilot.py compare` (authored deterministic fixture; zero live model calls).

These commands run the source applications, not the qJig suite. From the repository root, run `python -m pytest -q` for the offline qJig tests and `python scripts/verify_repo.py` for the current queue audit. The audit checks queue structure, completed dependencies, named test definitions and recorded evidence; it does not prove the recorded results, inspect runtime behavior or certify completion. `reports/verify_packet.py` is the historical pre-implementation review verifier and is not an active runtime gate.

The authored CLI supports `python -m qjig import`, `ask`, and `trace` after installing the package (or with `PYTHONPATH=src` from this checkout). Provider tests are opt-in; do not make live calls until the unfinished input, cost and aggregate budget controls are enforced. The loopback service can be started with `python -m qjig serve --catalog PATH --host 127.0.0.1 --port 8766`. It exposes source import, listing and inspection plus a deterministic question endpoint for explicit authored plans. The browser at `/` uses the same local catalog and authored decision endpoint; its synthetic walkthrough is recorded in `docs/verification/2026-11-07-browser-foundation.md`. The browser also has a fresh-planning form; a trusted backend can be configured as described in [fresh configuration](docs/workflows/fresh-configuration.md), but hosted execution remains blocked. The fresh hosted path, complete browser workflow and clean-install verification remain unfinished.
