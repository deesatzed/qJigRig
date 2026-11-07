# Execution contract

The current deliverable is the operational workbench and evaluation defined in GOAL.md. T001–T048 are complete; follow the amended dependencies in plan/tasks.json. Source workbenches remain read-only review inputs.

For each task in `plan/tasks.json`:

1. Read its dependencies, source method card, target file and named test. Confirm all dependencies are complete.
2. Add the smallest test for its stated observable behavior. Run the exact focused command in the detailed plan and record an intended failure. A missing module is only an initial contract failure; later failures must exercise behavior.
3. Implement that behavior in the named module. No unrelated cleanup or future task APIs. Reuse pure existing helpers only through a documented translation boundary.
4. Run the focused test and the named module's existing tests. At a phase gate run the full new qJig suite; provider calls stay opt-in. Record commands, counts, failures, caveats and any test-only provider use.
5. Commit scoped code/tests/docs. Update task status only with evidence, and record new decisions in DECISIONS.md. A source suite passing never closes a qJig implementation task.

No source dataset, .env, model environment or generated run is a runtime dependency of the new deterministic core. Do not run nested source test discovery as qJig's own suite. Use explicit source-audit commands separately.

Future CLI command after T039: `python -m qjig run --request REQUEST.json --catalog CATALOG --policy POLICY.json`. The catalog-only local service is available as `python -m qjig serve --catalog PATH --host 127.0.0.1 --port 8766`; question and browser workflows remain pending. The future `run` command above is not currently implemented.
