# Local fresh-planning configuration

The local service accepts `--fresh-config PATH` on `qjig serve`. The file is a trusted local JSON object, not browser input. It selects the OpenRouter stage settings, a private state directory and the path to the existing credential file. Do not put credentials in the JSON. The normal server starts without this option; fresh requests then report that the backend is not configured.

**Hosted requests remain disabled.** A configured request currently returns a preflight-unavailable response without contacting the provider. Configuration values, including model metadata, token bounds and prices, are assertions and do not establish safe costs or provider availability. In particular, a new state directory does not account for previous goal spending. Do not treat configuration as authorization to bypass the hosted gate.

The exact schema is illustrated by `config_for` in `tests/test_fresh_config.py`. Its model metadata and prices are synthetic test values, not current provider information. The `qjig.fresh-config.v1` object requires:

- `state_dir` and `env_path`: local paths to private state and the existing credential file, respectively. Run archives may contain source text and raw model responses.
- `total` and `per_request`: objects with `max_calls`, `max_tokens`, and `max_cost_usd`, within the ceilings in `GOAL.md`.
- `allocations`: separate budgets for `smoke`, `pilot`, `holdout`, and `acceptance`; their sums must fit the total. `partition` selects one of these.
- `planner`, `judge`, and `reviewer`: objects containing `provider`, `model`, `input_tokens`, `output_tokens`, and `max_price`. The `model` object is a provider-model metadata snapshot; its values do not prove current pricing or token bounds. The selected planner and judge identities are constrained by `GOAL.md`.

The persistent goal ledger and run archives would be created inside `state_dir` when the hosted gate is eventually resolved; the current refusal occurs before opening the ledger or making a model call. Further work must reconcile prior spending and establish complete provider input, pricing and BYOK bounds, as well as experiment reservations, before that gate can be opened.

A retained fresh run can be opened and downloaded from **Saved fresh runs**. The SQLite download includes source text, prompts and model responses. To replay it without inference, run `python -m qjig verify-fresh --file PATH`. The output includes a structural status, digest and `semantic_assurance`. With no separately retained digest the result is `unanchored`; to compare with a previously retained digest, add `--expected-digest DIGEST`. A matching digest checks consistency with that supplied anchor, not its authenticity, the correctness of the decision, or whether sources remain current. Incomplete or invalid checks return a nonzero exit code.

The local saved-run view also checks the local call journal for unresolved attempts. An unresolved attempt means the provider outcome is unknown and requires reconciliation before retry. If the journal is unavailable or cannot be matched to the archive, that status is unknown. The downloaded archive does not contain the separate journal and cannot establish its reconciliation state on its own.

Role-defined Python clients can use `RoleClient.ask_fresh(request_id, question, scope, as_of=..., entities=[...])` and inspect retained archives with `list_fresh_runs()` and `get_fresh_run(run_id)`. The request records the client's role and version; these are context, not authorization or evidence of expertise. The same configured-backend and hosted-call gates apply.
