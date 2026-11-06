# Standards

- Python 3.11+ for the first new runtime, standard library for deterministic logic/storage; pytest for small new tests. This review used Python 3.13.9. Pin actual runtime/dependencies in T001 rather than inventing a verified clean install.
- Frozen dataclasses and enums for external contracts. Pure functions for validation, applicability, state combination, relevance and stopping. No network, filesystem or config reads at import time.
- Separate modules for contracts, source storage, indexing, retrieval, logic, acquisition, providers, journals, agents, UI and evaluation. One source authority; derived indexes are rebuildable.
- Preserve raw file bytes; store decoded text and an explicit normalization map separately. Source identity cannot depend only on a workstation absolute path. Offsets are Python Unicode code-point indices into a named text hash, end-exclusive. Byte, normalized-text and extracted-text hashes have distinct field names.
- Dates and entity/authority identifiers are recorded provenance, not authenticated truth. Missing applicability data produces a reasoned unknown. Do not infer rule completeness from a valid generated graph.
- Run `python -m pytest tests/path.py::test_name -q` after each behavior. Use parametrized truth tables only for distinct logical cases, not redundant implementation mirrors. Use small graph enumeration to check invariants. Keep provider tests opt-in.
- Begin each change with its dependency IDs and failing behavioral test; commit only after focused regressions pass. Stop adding features when verification is red. Use one writer initially; measure concurrency before promising concurrent multiwriter operation.
- No network retry without a journaled policy and remaining budget. An uncertain in-flight paid call needs reconciliation; elapsed time is not evidence it did not execute. All planner/judge/rerank/embedding/repair/fallback usage belongs to the request ledger.
- Scores are uncalibrated estimates unless independently calibrated. Hashes verify identity/integrity, not authority, semantics, reviewer independence or adversarial robustness.
