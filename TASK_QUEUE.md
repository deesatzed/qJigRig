# qJig task queue

This queue implements GOAL.md. Current review/checkpoint work is complete; all runtime tasks below are pending design review and implementation. Source-project tests do not close these tasks.

Authoritative machine-readable dependencies: [plan/tasks.json](plan/tasks.json). Exact per-task red/green/commit steps: [detailed build plan](docs/plans/2026-11-06-qjig-build.md).

## Next five small tasks

1. T001: isolate the package; prove importing it does no IO.
2. T002: round-trip the request contract, including role/version and scope.
3. T003: reject malformed budgets before work.
4. T004: preserve bytes and explicit decoded-text identity.
5. T005: make pinned source identity independent of a workstation path.

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
