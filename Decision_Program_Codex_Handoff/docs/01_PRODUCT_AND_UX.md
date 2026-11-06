# Product and user experience

The workbench helps a user make and verify decisions from an explicit body of knowledge. Its visible unit is the question and its result. Its reusable unit is a typed operation with an evidence contract. A full program can be saved and reviewed when a family of decisions recurs.

## Decide

1. Enter a question, optionally specify alternatives or decision criteria, and set the scope and as-of date where relevant. Pick a pinned local collection or supply text. Show which source versions are attached. Default to **Fresh decomposition**. Offer **Reviewed program** as a clearly named alternate mode.
2. Start the run. Show progress in terms of work the user can understand, such as finding a governing rule or checking an exception. Preserve the original question. Surface a material ambiguity if an assumption would change the decision.
3. Show the outcome with the decisive findings and short source excerpts. Each citation opens its exact passage or record and identifies the source version. A deferral identifies the specific missing input, conflict, or limitation. A service failure is a separate state from evidence insufficiency. A skipped predicate includes the reason in the expanded trace.
4. Allow replay of the saved run and a fresh rerun with an explicitly changed question, as-of date, source snapshot, or model. Label them separately. An intervention uses a derived snapshot and preserves the original.

The first screen should answer three questions: what was decided, what evidence mattered, and what would still change the outcome. A predicate table can expand to show the planner’s proposed question, evidence requirement, operator, result, and stop reason.

## Programs

Show a program’s original question, applicability, decision predicates, current composition, governing sources, authoring method, version, and review state. A fresh planner produces an ephemeral draft. Saving a draft and reviewing it are separate actions. Reviewed programs can be selected for reuse in supported scopes. Show the reasons a binding was rejected. An explicit review action and successful validation checks are required to promote a revised program. Show what changed between versions and allow rerunning a prior version against the same pinned inputs.

Keep the v1 editor small. View structured records, apply a controlled fact or source edit in an experiment, and promote or retire a validated revision. Complex visual graph editing can be deferred. The decision trace is the main inspection tool.

## Compare

The user can select an evaluation stage, a dataset snapshot, configured arms, and a run budget. Show whether each arm is live, offline, or unavailable before execution. Afterward, display accuracy or adjudication progress, answer coverage, deferrals, source support, cost, and latency. Show paired disagreements and which stage failed. Provide export of raw runs and the score report. Label an unreviewed result as awaiting adjudication. Keep participant-facing review views blind to arm identity until judgments are recorded.

The comparison must show which sources each arm was allowed to access and whether context was supplied or retrieved. Show when a cost or latency measurement is incomplete. Fixture views should visually identify their synthetic data and scripted evaluators. The default comparison presents the standalone smaller path. A fallback-enabled deployment arm has its own row and cost.

## End-to-end demonstration

Use a starter corpus with one explicit exception and a question the planner has not seen. Run the fresh path, show the evidence needed by each decisive predicate, and save the trace. Rerun with the exception confirmed or withdrawn by a controlled source edit and show the expected change. Then remove a different indispensable source and show a justified deferral. In Compare, run or load the actual recorded independent arms with the same question IDs and display how the final verdicts were scored.

## Initial boundaries

Prioritize a local CLI and browser app, text and Markdown import, one bounded corpus, one smaller planner, one local judge, one frontier comparator, and explicit review of reusable programs. Add PDF ingestion, external integrations, model training, and richer program editors only when needed for a measured question or requested by the owner. General-purpose web research is a capability of the separate frontier comparator. The smaller path’s knowledge access stays bounded in the primary experiment.
