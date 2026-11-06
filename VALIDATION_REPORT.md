# Validation report: 2026-11-06 review checkpoint

No qJig runtime has been implemented or claimed. These checks assess source baselines, compatibility and the planning packet.

| Check | Actual command / context | Result / limits |
|---|---|---|
| QUIXER remote checkpoint | `git ls-remote origin refs/heads/research-slice`; annotated tag push | Remote branch points at `1790086`; checkpoint tag pushed successfully |
| QUIXER Python | `python -m pytest -q`, original worktree | 263 passed on Python 3.13.9; existing SWIG deprecation warning |
| Switch source suite | `pnpm test` and `pnpm typecheck`, original switch experiment folder | 33 passed, TypeScript check passed; no paid calls |
| JIG moved source | `PYTHONDONTWRITEBYTECODE=1 WORKBENCH_DATA=TEMP python scripts/offline_tests.py`, moved project root | 250 passed; offline socket guard inside process; local HTTP tests exercised |
| JIG frozen copy | same command, frozen audit root | 250 passed. First copy omitted `.rst` fixtures; second invocation used the wrong cwd for CLI subprocesses. Both setup failures were corrected without source edits; prior logs retained |
| Private-KB pilot | `python pilot.py compare`, frozen pilot folder | 18/18 reference decisions in three authored modes; measured evidence bytes 187565 -> 38059, not inference cost or accuracy evidence |
| Compatibility | exact audit probe preserved in `reports/probe_source_contracts.py` | CRLF hashes differ, heterogeneous dates rejected, missing exception remains material, conflicting support retained |
| Source manifest | SHA-256 of selected source files; QUIXER archive from commit | JIG has a filesystem fingerprint, not upstream Git identity; see source manifests |
| Planning packet | `python reports/verify_packet.py` | Checks task IDs/dependencies/DAG, required controls and legacy hashes; final result saved in reports/packet-verification.json |
| Git diff | `git diff --cached --check` before commits | Preserved JIG baseline reports trailing whitespace in docs/03_BENCHMARK_PROTOCOL.md:20 and an extra blank line in reference/jigfiles.txt:5026. Kept source bytes unchanged; new packet is checked separately |

Raw source test logs and compatibility output are in `reports/`. They are not qJig runtime tests. No new GUI walkthrough, local judge installation, fresh provider/model run, independently adjudicated evaluation, scaling test or actual swarm dispatch occurred. The frozen copy is not a clean dependency installation. Independent live performance remains an open goal.

## Evidence needed during implementation

- First new unit test red/green receipts at T001–T012.
- Actual deterministic CLI trace at T038.
- Opt-in real provider receipts and complete accounting at P4.
- Browser/two-client workflow at P5.
- Outcome assessment under isolated arms and fresh cases at P6.
