# Local fresh-planning configuration

The local service accepts `--fresh-config PATH` on `qjig serve`. The file is a trusted local JSON object, not browser input. It selects the OpenRouter stage settings, a private state directory and the path to the existing credential file. Do not put credentials in the JSON. The normal server starts without this option; fresh requests then report that the backend is not configured.

**Hosted requests remain disabled.** A configured request currently returns a preflight-unavailable response without contacting the provider. Configuration values, including model metadata, token bounds and prices, are assertions and do not establish safe costs or provider availability. In particular, a new state directory does not account for previous goal spending. Do not treat configuration as authorization to bypass the hosted gate.

The exact schema is illustrated by `config_for` in `tests/test_fresh_config.py`. Its model metadata and prices are synthetic test values, not current provider information. The `qjig.fresh-config.v1` object requires:

- `state_dir` and `env_path`: local paths to private state and the existing credential file, respectively. Run archives may contain source text and raw model responses.
- `total` and `per_request`: objects with `max_calls`, `max_tokens`, and `max_cost_usd`, within the ceilings in `GOAL.md`.
- `allocations`: separate budgets for `smoke`, `pilot`, `holdout`, and `acceptance`; their sums must fit the total. `partition` selects one of these.
- `planner`, `judge`, and `reviewer`: objects containing `provider`, `model`, `input_tokens`, `output_tokens`, and `max_price`. The `model` object is a provider-model metadata snapshot; its values do not prove current pricing or token bounds. The selected planner and judge identities are constrained by `GOAL.md`.

The persistent goal ledger and run archives would be created inside `state_dir` when the hosted gate is eventually resolved; the current refusal occurs before opening the ledger or making a model call. Further work must reconcile prior spending and establish complete provider input, pricing and BYOK bounds, as well as experiment reservations, before that gate can be opened.
