# Retrieval Experiment Repair Implementation Plan

> Use the executing-plans and test-driven-development workflows in the existing isolated research worktree.

**Goal:** Repair the decision-provider, switch-navigation and evaluation-design failures exposed by the 16-task exploratory comparison, then verify a bounded new experiment without reclassifying old results.

**Architecture:** Keep the source-checked catalog and read-only agent boundary. New runs explicitly record whether the retrieval decision provider is active, use a bounded, deterministically ordered switch candidate shortlist with an explicit broaden path, and retain the legacy navigation contract for replay. A separate AI-review protocol distinguishes essential source evidence, supporting evidence and material to inspect, and judges proposal quality as a plan. Reviewed artifacts remain explicitly model-generated and uncalibrated.

**Tech stack:** Python, SQLite, pytest, TypeScript, switch, OpenRouter Decisions and a separate OpenRouter text reviewer.

## Evidence and scope

The saved 16-task agent experiment used `provider=None` for ordinary decision retrieval. Switch asked up to 52 options at once and fell back on all 16 tasks, 13 after unstable choices. The earlier AI reviewer labeled up to 20 sources as relevant despite a three-result cap, and assessed a proposal-only planner as if it had implemented code. The earlier results and prompts are historical and must not be rewritten. AI review is the user's chosen alternative to manual review; it is not independently verified ground truth. The existing user authorization covers bounded non-sensitive model calls and pushing QUIXER; it does not authorize live swarm or MindStore integration.

## Tasks

1. **Provider wiring and verification:** Modify `experiments/agent_tasks/run_live.py` to configure `OpenRouterDecision` for newly generated retrieval comparisons, record model/provider policy, reject replay falsely represented as model-enabled, and preserve unknown/fallback outcomes. Write focused tests of the provider wiring and recorded calls before implementation. No uncalibrated operational threshold.
2. **Bound switch choices:** In `src/quix_knowledge/switch_snapshot.py` and `experiments/switch-navigation/src/{quix-snapshot,domain}.ts`, introduce an opt-in versioned shortlist for new experiments. Rank initial passages deterministically using the baseline candidate pool, limit visible passage and matching-topic choices, differentiate same-title choices with source IDs and snippets, and preserve an explicit bounded path to the remainder. Keep old snapshots/traces replayable. Test option bounds, ranking, broaden coverage, duplicate titles, missing evidence, and fallback.
3. **Redesign automated evaluation:** Add a separately versioned AI-review protocol under `experiments/` and tests. Freeze prompts, model, source hashes and task identities before calls. Retrieval labels distinguish essential, supporting and inspect-only material and do not treat empty/unknown as unanswerable. Outcome review assesses plan quality and source support, not whether a proposal executed code. Validate IDs, rubric, model, failures, costs and blind condition mapping; never relabel AI review as human review. Keep full outputs local and produce a sanitized summary.
4. **Fresh bounded evaluation:** Prepare separate, previously unused source-grounded tasks and holdout groups before model calls; clearly identify any source overlap and avoid claiming independent validation. Compare common candidates, result limits and packet budgets; record full prompt/token differences. Run fixture tests and a capped live pilot with the authorized `.env`. Record actual calls, failures, fallbacks, costs and separate planner/decision/reviewer accounting. Include an actual no-context, baseline, role and switch planner comparison when the model and executable are available.
5. **Verification and documentation:** Run focused and full Python tests, switch tests and typecheck, and relevant Swift checks if its code changes; recheck sources and `git diff --check`. Record commands, evidence, open limitations and local artifact paths in `PROGRESS.md`. Commit only scoped work and push the authorized QUIXER branch; preserve unrelated files and the separate HITMCockpit worktree.

## Success criteria

A new decision-enabled run proves actual decision calls or reports an exact external failure; switch choices are bounded without losing the ability to reach remaining candidates; evidence and proposal rubrics match the intended use; fixture and live results are explicitly separated and reproducible. An AI review is exploratory and cannot establish independent human agreement, calibrated accuracy, statistical power or live swarm benefit.
