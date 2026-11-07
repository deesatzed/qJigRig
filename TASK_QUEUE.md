# qJig task queue

This queue implements GOAL.md. T001-T047 (P1-P3 plus P4 through the first live smoke) are complete with receipts in plan/tasks.json and PROGRESS.md; T048-T074 are pending. Source-project tests do not close these tasks.

Authoritative machine-readable dependencies: [plan/tasks.json](plan/tasks.json). Exact per-task red/green/commit steps: [detailed build plan](docs/plans/2026-11-06-qjig-build.md).

## Next tasks

1. T046 done (live smoke, see PROGRESS.md). Hy4 needs a larger token allowance than the planner/judge defaults (it spends the cap on hidden reasoning); decide before T048.
2. T048-T052 are now unblocked (T046 done) in plan/tasks.json (fresh pipeline, Hy4 escalation, assurance cases, replay, cost aggregation).
3. Independent of T046 in substance but ordered after it in the plan: P5 (T053-T062) and P6 (T063-T074). Starting them early would need a recorded plan change.

P4 onward touches providers: it needs a labeled stand-in transport (approval) for offline tests and a configured budget before any live call.

## Phase gates

| Phase | Tasks | Demonstration required before advancing |
|---|---|---|
| P1: shared contracts | T001–T012 | hashes/spans/versions/entity/date behavior agree |
| P2: knowledge acquisition | T013–T024 | headings/fallback/topic/role retrieval and evidence recovery preserve obligations |
| P3: deterministic decision spine | T025–T038 | authored graph + exact evidence + unknown exception + real CLI trace |
| P4: real model boundaries | T039–T052 | journaled fresh plan/judge, full budget, optional local path and Hy4 escalation |
| P5: usable shared workbench | T053–T062 | browser workflow and two role clients using shared evidence |
| P6: benefit assessment | T063–T074 | isolated arms, frozen cases, reviewed outcomes and clean install |

Each task has five execution actions: write one behavioral test; observe intended failure; implement the smallest change; rerun focused and nearest regressions; commit and record evidence. The detailed plan expands these for every task. Do not batch several untested features into one step.
