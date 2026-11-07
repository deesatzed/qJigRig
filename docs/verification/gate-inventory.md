# Completion-gate inventory

`plan/gates.json` is an initial machine-readable inventory, not the completion report or proof of a passing gate. `qjig.gates.build_gate_inventory` maps F01–F09, all `R` repair task IDs, and original T049–T074 task IDs. Every gate is `unverified`, with an empty verified-evidence list. Task status, command and evidence text are copied as **queue assertions** only; they are not checked execution receipts, exit codes, counts, independent labels or verified outcomes.

The inventory records SHA-256 hashes of the exact current `GOAL.md` and `plan/tasks.json` bytes. `inspect_gate_inventory` returns `current_unverified` only when the whole document matches a fresh inventory from those exact inputs; changes, omitted gates or a manually promoted status return `stale_or_invalid`. A current inventory does not establish completion. The current GOAL file is an existing uncommitted user change, so a checkout without those exact bytes will correctly report this snapshot as stale.

To regenerate after an authorized change to the goal or task queue:

```sh
PYTHONPATH=src python -c 'import json; from pathlib import Path; from qjig.gates import build_gate_inventory; q=Path("plan/tasks.json").read_bytes(); g=Path("GOAL.md").read_bytes(); Path("plan/gates.json").write_text(json.dumps(build_gate_inventory(q,g),indent=2,ensure_ascii=False)+"\n")'
```

Remaining work includes evidence records with actual commands, exit codes, counts, artifact locations and hashes, trustworthy validation of those records and explicit incomplete/unknown gates, live receipt and workflow verification entrypoints, and the final requirement-by-requirement completion audit. Do not interpret the structural inventory as independent model quality, provider execution, accessibility, security or release evidence.
