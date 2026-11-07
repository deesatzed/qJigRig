# qJig task queue

This queue implements GOAL.md. T001-T038 (phases P1-P3, the offline deterministic slice) are complete with receipts in plan/tasks.json and PROGRESS.md; T039-T074 are pending. Source-project tests do not close these tasks.

Authoritative machine-readable dependencies: [plan/tasks.json](plan/tasks.json). Exact per-task red/green/commit steps: [detailed build plan](docs/plans/2026-11-06-qjig-build.md).

## Next five small tasks

1. T039: record call intent in a journal before any provider side effect.
2. T040: refuse a blind retry of an uncertain paid call.
3. T041: enforce request-wide physical call reservations.
4. T042: validate typed responses and keep invalid HTTP-success output.
5. T043: bind a fresh bounded planner response to request, corpus and model.

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
