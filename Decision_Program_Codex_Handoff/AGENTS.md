# Repository Guidelines

## Project Structure & Source of Truth

This repository is an implementation handoff for the Decision Program Workbench; it does not yet contain an application or test suite. Start with `GOAL.md` and `README.md`. The numbered files in `docs/` specify the product, architecture, benchmark, acceptance criteria, and Jig transfer. `examples/decision_run.example.json` is an illustrative synthetic trace; `reference/` holds historical material and a Jig source export.

Before coding, read `GOAL.md`, `STANDARDS.md`, `IMPLEMENT.md`, `DECISIONS.md`, `PROGRESS.md`, and `TASK_QUEUE.md` when present. Treat them as project source of truth. Keep the domain-neutral runtime separate from the starter corpus, model adapters, and benchmark data.

## Build, Test & Development

No build, installation, or test commands are established yet. Implement a local Python project with a browser UI and CLI, then document and verify actual commands in `README.md`. Provide distinct entry points for installation, app startup, offline fixtures, automated tests, local judge smoke, live comparisons, scoring, and export. Pin dependencies after verifying installation.

## Coding & Testing Guidelines

Follow the contracts in `docs/02_ARCHITECTURE_AND_CONTRACTS.md` and acceptance checks in `docs/04_BUILD_AND_ACCEPTANCE.md`. Choose and document Python formatting, naming, and test conventions as the implementation takes shape; avoid inventing existing tooling. Start with deterministic, offline fixture tests, including missing-entity, temporal, and override regressions. Test source citations, interventions, replay, and explicit failure states. Keep live model smoke tests separate and record their environment and results.

## Evidence & Configuration

Keep credentials and provider budgets in local configuration; never commit secrets. Clearly label fixtures, live model results, simulations, measured costs, and independently adjudicated research outcomes. Freeze benchmark inputs and preserve the held-out boundary described in `docs/03_BENCHMARK_PROTOCOL.md`.

## Contributions & Agent Workflow

No Git history or established commit convention is available in this handoff. Use concise, imperative commit subjects and describe behavior, verification, and remaining limitations in pull requests; include screenshots for UI changes. Document safe assumptions in `PROGRESS.md`. Stop for missing credentials, destructive actions, production deployment, sensitive-data or legal uncertainty, repeated failures, or material scope decisions. Claude Code may provide a bounded second opinion; Codex reviews its recommendations and remains responsible for decisions and verification.
