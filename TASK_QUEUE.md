# Active usable-app queue (2026-11-08)

The user removed the full model comparison and research evaluation from completion requirements. Follow [plan/app-tasks.json](plan/app-tasks.json) and [the usable-app plan](docs/plans/2026-11-08-usable-app-plan.md). Preserve the research task DAG and its historical records; its pending research entries are not app-completion gates. Do not treat the old gate manifest as acceptance for this new scope.

---

## Historical research queue

# qJig task queue

This queue implements GOAL.md. T001–T048 are complete; T049–T074 remain pending. The machine-readable queue includes repair tasks R01–R09 for findings F01–F09 and additional bounded subtasks; its statuses are authoritative. Historical task identities and evidence remain intact.

Authoritative dependencies: [plan/tasks.json](plan/tasks.json). The [detailed build plan](docs/plans/2026-11-06-qjig-build.md) is historical for completed work; GOAL.md and the repair queue govern the amended sequence.

## Next tasks

R01, R02 and R06 are complete; R08, R07, R03, R04 and R05 remain open before T049–T051. R09 completed the queue audit and initial documentation reconciliation; final reconciliation remains required at T073–T074. T057 must integrate the exact review binding from R01. This ordering repairs decision and transport boundaries, accounting and persistence before retrieval experiments or paid runs. The stand-in transport remains labeled and live calls remain opt-in and budgeted.

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
