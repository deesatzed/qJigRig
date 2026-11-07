# qJig task queue

This queue implements GOAL.md. T001-T045 and T047 (P1-P3 plus the offline, stand-in-tested parts of P4) are complete with receipts in plan/tasks.json and PROGRESS.md; T046 and T048-T074 are pending. T046 is blocked on the owner's model choice, budget and key arrangement. Source-project tests do not close these tasks.

Authoritative machine-readable dependencies: [plan/tasks.json](plan/tasks.json). Exact per-task red/green/commit steps: [detailed build plan](docs/plans/2026-11-06-qjig-build.md).

## Next tasks

1. T046 (BLOCKED, needs the owner): opt-in real planner/judge smoke with receipts. Needs a model ID chosen from a current lookup, a call/token/spend budget, and how the key is supplied.
2. T048-T052 depend on T046 in plan/tasks.json (fresh pipeline, Hy4 escalation, assurance cases, replay, cost aggregation).
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
