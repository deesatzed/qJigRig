# Implementation plan entry point

The 74-task [detailed plan](docs/plans/2026-11-06-qjig-build.md) expands each behavior into five red/green/commit actions. [TASK_QUEUE.md](TASK_QUEUE.md) shows phase gates and the next five tasks; [plan/tasks.json](plan/tasks.json) records exact dependencies and status.

Read the [synthesis](SYNTHESIS.md) and [algorithm](docs/ALGORITHM.md) first. The recommended architecture is a new canonical core with adapters; merging both existing runtimes directly was rejected because their source identities, date rules, state ownership and model budgets differ.

All runtime tasks are pending. The review checkpoint itself preserves source inputs and actual source-test evidence. The first implementation milestone is the deterministic vertical slice at T038, followed by real provider paths at P4 and shared agent/browser use at P5. The final comparison must test whether the combination adds value over each component and a competent direct model.
