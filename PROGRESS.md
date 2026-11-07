# qJig progress

## 2026-11-06: checkpoint, review and proposed build design

The user requested an algorithmic combination of QUIXER and the moved JIG workbench, a checkpoint of QUIXER, a thorough review and granular small-test build steps. This pass creates that repository and review packet; it does not claim a combined runtime.

Completed:

- Verified QUIXER `research-slice` at `1790086a5d3b178957ce80324c0f283dbcf78c97` on GitHub and pushed annotated tag `checkpoint/quixer-before-qjig-2026-11-06`.
- Initialized `/Volumes/WS4TB/qJig` as a new local main-branch repository. The existing moved JIG folder was preserved. QUIXER's exact committed tracked tree is archived under `sources/quixer`.
- Read both goals/plans/current audits and inspected storage, identity, indexing, role ranking, recovery, bounded reasoning, stopping, model adapters, programs and experiment recovery. Found stale JIG instructions and historical test counts.
- Reran QUIXER 263 Python tests, switch 33 tests/typecheck and JIG 250 offline tests. A frozen source copy passed JIG's 250 tests after correcting audit copy/cwd setup errors; preserved logs distinguish those from source defects.
- Reproduced JIG private-KB authored fixture results and ran four explicit compatibility probes without live provider calls.
- Proposed one canonical source/trace contract, bounded deterministic acquisition and exact reasoning, then real providers/shared agents/measurement in later phases.
- Wrote 74 pending runtime tasks with dependencies, target modules, named focused tests, acceptance behavior and red/green/commit actions. No source test result closes these tasks.

Assumptions and choices:

- qJig root is the new app repository; the moved JIG folder is reference material, not the future package root.
- The user's approval to combine the ideas authorizes this review/repository/planning work. The detailed implementation design remains proposed for review before app-code changes.
- Start with a non-sensitive software-project evidence family and a deterministic fixture graph. Keep provider-backed fresh planning, real-agent outcomes and independent judgments distinct.
- Preserve existing Hy4 selection; no new live model expenditure or model promotion during review.
- Credentials/environments/generated data remain local and excluded. No remote was supplied for qJig, so it is a local repository.
- No top-level source license was located; source references are retained locally, and distribution rights remain an explicit publication consideration.

Next: review SYNTHESIS.md, docs/ALGORITHM.md and GOAL.md, then implement T001–T005 one tested behavior per commit. Do not start a wholesale merge or UI-first build.

Repository checkpoint: initial qJig source/provenance commit `da1397b`. Staged path and credential-pattern checks found no credential files, generated data, virtualenvs or private-key/API-key patterns in the 310 checkpoint files. Two inherited whitespace warnings were recorded rather than changing source bytes. This is a narrow pattern check, not a general security audit.

## 2026-11-06: T001 complete

- Added `pyproject.toml` (Python >=3.11, no runtime dependencies, pytest limited to `tests/` with `pythonpath=src`, so nested source suites are not collected), `src/qjig/__init__.py`, `tests/test_bootstrap.py`.
- Red: `test_import_has_no_io` failed with `ModuleNotFoundError: No module named 'qjig'` (allowed initial contract failure).
- Green: focused test 1 passed; `tests/test_bootstrap.py` 1 passed; full `python -m pytest -q` 1 passed.
- Sensitivity check: temporarily appending a file write to `__init__.py` made the test fail; reverted.
- Limits: the test uses a Python audit hook in a subprocess, which sees open/socket/mkdir/remove events during import only. Not verified: a clean `pip install` of the package (not attempted). `verify_packet.py` asserts all tasks pending and will now fail by design; implementation-aware validation is still to be added.

## 2026-11-06: T002 complete

- `Request` (frozen dataclass: request_id, question, role, role_version, scope) with `to_dict`/`from_dict` in `src/qjig/contracts.py`; schema tag `qjig.request.v1`.
- Red: `ModuleNotFoundError: qjig.contracts`. Green: focused 1 passed, `tests/test_contracts.py` 1 passed, full suite 2 passed.
- Behavior: JSON round trip equals the original; role and scope kept byte-exact (no trimming/case folding); wrong or missing schema_version, missing fields and unknown fields raise `ContractError`.
- Limits: only the minimal fields exist; entity keys, as_of, evidence policy, corpus hash and experiment arm from docs/CONTRACTS.md are not yet modeled (later tasks).

## 2026-11-06: T003 complete

- Added `Budget` and optional `Request.budget`; validation runs at construction and in `from_dict`.
- Red: `ImportError: Budget` at collection. Green: `test_reject_invalid_budget` 10 cases passed; `tests/test_contracts.py` 12 passed; full suite 13 passed.
- Rejected: True/False, negatives, floats or strings for counts, NaN/inf/negative cost, non-object budget, unknown/missing budget fields. Accepted: zero limits.
- Limit: this only validates shape. Nothing enforces or spends a budget yet.
