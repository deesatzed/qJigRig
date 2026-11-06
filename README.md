# qJig

qJig is a proposed shared evidence and decision workbench for agents. It combines QUIXER's versioned document catalog and role-aware retrieval with JIG's explicit decision questions, bounded reasoning, unknown states and controlled interventions.

**Current status:** source checkpoint, code review, compatibility probes and granular build plan. A combined qJig runtime has not been implemented. Passing either source project's tests does not prove a combined application or a quality improvement.

Start with [the synthesis](SYNTHESIS.md), [source audit](SOURCE_AUDIT.md), [algorithm](docs/ALGORITHM.md), and [build queue](TASK_QUEUE.md). The [full implementation plan](docs/plans/2026-11-06-qjig-build.md) gives a focused test and commit procedure for every task. [GOAL.md](GOAL.md) defines completion and [VALIDATION_REPORT.md](VALIDATION_REPORT.md) records what was actually run.

## Source checkpoints

- `sources/quixer/`: exact tracked files from QUIXER `1790086a5d3b178957ce80324c0f283dbcf78c97`, archived from the committed tree. GitHub tag `checkpoint/quixer-before-qjig-2026-11-06` preserves the source commit.
- `Decision_Program_Codex_Handoff/`: the user's moved JIG workbench. Selected code/docs/fixtures are fingerprinted in `plan/jig-source-hashes.json`. Local credentials, datasets, environments and generated records are excluded from Git.
- The separate HITMCockpit adapter is recorded at `08a49cce014453afdb7be5e4a9909c2416454cf9`; it remains in its own local worktree. The first qJig milestones do not require Swift.

The source folders are review inputs, not the location for new qJig implementation. New code belongs in `src/qjig/` after the design is reviewed. The JIG source AGENTS.md describes an older pre-implementation state; consult its actual code and current audit for capabilities. No upstream source file was rewritten to fit this design.

## Verified source commands

From `sources/quixer`: `python -m pytest -q` (requires pytest and optional installed dependencies for their corresponding tests).

From `Decision_Program_Codex_Handoff`: `PYTHONDONTWRITEBYTECODE=1 python scripts/offline_tests.py` (stdlib core; the guard covers network operations inside that test process, not arbitrary children).

From `Decision_Program_Codex_Handoff/Private_KB_Decision_Pilot`: `python pilot.py compare` (authored deterministic fixture; zero live model calls).

These commands run the source applications. The future qJig test/start commands are specified in the plan and become verified only after those tasks exist. No new hosted calls, local model loading, live swarm dispatch or deployment occurred in this review. The new repository is local; it has no GitHub remote configured.
