# qJig working rules

Read GOAL.md, STANDARDS.md, IMPLEMENT.md, DECISIONS.md, PROGRESS.md and TASK_QUEUE.md before coding. Use `plan/tasks.json` for task dependencies and `docs/plans/2026-11-06-qjig-build.md` for exact test steps. Do not implement beyond the next unblocked task without recording why.

Work in `src/qjig`, `tests`, `docs` and the root control files. Treat `sources/quixer` and `Decision_Program_Codex_Handoff` as checkpointed review inputs; changes there require an explicit migration task. Do not silently follow their stale scope statements as descriptions of qJig.

For each behavioral task: write the smallest meaningful failing test, observe the intended failure, implement only that behavior, run the focused test and nearest regressions, then commit scoped files. Record evidence and remaining limits. A fixture proves mechanics; a model smoke proves a provider path; neither is independent outcome evidence.

Preserve source evidence, agent interpretations and reviewer judgments as distinct linked records. Unknown, contradiction, conflict, retrieval failure and provider failure are separate. Missing search hits cannot establish that an exception does not exist. Role scores affect acquisition order and never erase material obligations.

Make safe assumptions and record them rather than blocking routine progress. Stop for a material scope change, missing credentials, destructive action, deployment or repeated failure after distinct mitigations. Existing user authorization persists. No background agents or broad rewrites are required; use bounded delegation only if separately requested.

Keep .env, environments, local datasets and generated data out of commits. Do not run live model evaluations as part of the offline suite. Live evaluations require an explicit configured call/token/spend budget; report missing costs as unknown. Hy4 remains the selected escalation model; selection is not evidence of superiority. Do not introduce unrelated sensitive-content features.
