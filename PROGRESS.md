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

## 2026-11-06: T004 complete

- `decode_source(raw, *, encoding)` in `src/qjig/sources.py` returns a frozen `DecodedSource`: original bytes, `raw_sha256` (of the bytes), named `encoding`, `normalizer="identity"`, decoded `text` (CRLF kept) and `text_sha256` (of the UTF-8 encoding of the text).
- Red: `ModuleNotFoundError: qjig.sources`. Green: focused test passed; `tests/test_sources.py` 3 passed; full suite 16 passed.
- Test uses latin-1 `café` + CRLF so the two hashes differ; strict decoding raises `ContractError` rather than substituting characters; the encoding argument is required.
- Limits: in-memory only. No blob storage, no revision record, no BOM handling policy (a UTF-8 BOM would stay as U+FEFF in text under `utf-8`), no PDF extractor.

## 2026-11-06: T005 complete

- Added `SourceRevision.create(source_id, origin, decoded)` and `require_pin(...)` in `src/qjig/sources.py`.
- Red: `ImportError: SourceRevision`. Green: focused test passed; `tests/test_sources.py` 11 passed; full suite 24 passed.
- Shown: the same content read from two different absolute origins gives the same `revision_id`; changed bytes, a different encoding choice or a different `source_id` give a different one; `require_pin` fails on changed content but not on a move; path-like source ids are rejected.
- Limits: the id attests content identity only, not authority or semantics. There is no store, no entity/scope/date fields and no check that an origin really holds these bytes (later P1 tasks). Hash scheme is a new qJig contract and is not yet reconciled with QUIXER/JIG hashes (T007+).

## Phase note (T001-T005)

Full qJig suite after T005: 24 passed (`python -m pytest -q`, Python 3.13.9). T006-T012 remain in P1. `reports/verify_packet.py` still asserts all tasks pending, so it fails by design now; an implementation-aware check has not been written.

## 2026-11-06: T006 complete

- `Span`, `make_span`, `verify_span` in `src/qjig/spans.py`: offsets are code-point, end-exclusive; an astral emoji counts as one position; altered quote, shifted offsets, other revision, wrong text hash and bad offsets (bool, negative, empty, out of range) all raise `ContractError`. Limit: line/page anchors and extraction assurance fields from CONTRACTS.md are not modeled yet.
- Red: ModuleNotFoundError qjig.spans (initial contract). Green: focused 1 passed in 0.08s; tests/test_spans.py 7 passed in 0.04s; full suite 31 passed in 0.10s. 2026-11-06.
