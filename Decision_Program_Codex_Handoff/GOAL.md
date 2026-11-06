# GOAL.md · Build the Decision Program Workbench

**Handoff status:** Implementation specification, November 6, 2026. When the project owner assigns this package to Codex for implementation, build, test, and document the completed app through the acceptance criteria below. This document governs the build. The original scaffold in `reference/` records the earlier exploration.

## Objective

Build a local workbench that tests whether a smaller generative model and a local typed decision judge can answer unseen, source-dependent questions at near-frontier accuracy, with verified citations and materially less cost and latency. The smaller path must discover the judgments that determine the answer, obtain the evidence each requires from a bounded knowledge base or supplied context, evaluate them, and combine them into a decision. A frontier model researches and answers the same question independently.

The main hypothesis concerns **fresh decomposition on an unseen question**. A hand-authored program is a diagnostic control. Reuse of whole programs is a secondary experiment for repeated questions. A frontier fallback is a separately reported deployment experiment. The standalone smaller path is the primary result.

## Deliver the app and the experiment

1. **Decide.** Enter a question, specify its scope and as-of date, and select a local source collection or provide bounded context. Run fresh decomposition, inspect the answer and the decisive evidence, see unresolved facts or exceptions, and open the full predicate trace.
2. **Programs.** Inspect the generated predicates, their evidence requirements, and composition. Rerun with an altered fact, missing source, or changed rule. Save reviewed programs for a separate reuse mode and preserve their applicability, provenance, version, and review status.
3. **Compare.** Run reproducible, blinded comparisons among real model arms. Separate shared-evidence, shared-corpus, and practical broad-research comparisons. Display independently scored outcomes, evidence support, deferrals, cost, latency, and where the arms disagree. Export machine-readable runs and a readable report.
4. **Run locally.** Provide documented install, offline fixture, local-model smoke, and live comparison commands. Keep credentials and provider budgets in local configuration. Mark offline, model-backed, and unavailable paths clearly. Record real metrics and modeled estimates separately.

## How to build it

- Read `README.md` and `docs/01_PRODUCT_AND_UX.md` for the user flow. Use `docs/02_ARCHITECTURE_AND_CONTRACTS.md` for interfaces, `docs/03_BENCHMARK_PROTOCOL.md` for the experiment, `docs/04_BUILD_AND_ACCEPTANCE.md` for milestones and acceptance, and `docs/05_JIG_TRANSFER.md` before importing ideas or code from Jig. `examples/decision_run.example.json` illustrates a decision trace.
- Inspect the assigned repository and instructions first. If none is assigned, create a clean local Python project with a local browser UI and CLI. Keep the domain-neutral runtime separate from the starter corpus, model adapters, and benchmark data. Choose the smallest stack that can support the documented flows and pin the dependencies you actually verify.
- Start with reproducible fixture runs and the acceptance probes drawn from Jig. Then connect the smaller planner, local judge, direct small-model baseline, and independent frontier arm. Run the shared-evidence checkpoint before adding retrieval complexity. Report failures and use the diagnostic arms to locate them.
- Use the owner’s Mac setup as the first live local target. The owner has a working MLX/Unsloth invocation of `MaziyarPanahi/Qwen3.5-4B-Jev-Judge` through `FastDecisionModel`, with a 4,096-token configured sequence length and `load_in_4bit=False`. Treat this as the starting adapter contract. Capture and validate the actual environment and output schema. Keep the planner and frontier model configurable and record exact versions in each experiment.
- Use a public, versioned, nonclinical corpus for initial validation. A bounded set of official Python standard-library documentation with version-specific behavior is the default candidate. Select and freeze a narrow slice with independently verifiable questions. Jig’s synthetic data is suitable for regression and smoke tests. Any change to the starter domain should be documented with the reason and independent verification method.
- Continue through all locally executable milestones. Use real services only with configured credentials and an authorized run budget. If a live adapter or review set is unavailable, complete the runnable fixture path, keep the affected acceptance check visibly open, and report the exact command, observed blocker, and input needed to close it. Model-based output and an independently verified research result are separate acceptance claims.

## Definition of done

The app is ready for handoff when an owner can start it locally, complete the three views above, import and pin sources, run and replay a fresh decision with traceable evidence, see a controlled intervention change the appropriate result, and export a comparison. All required automated acceptance checks must pass. Real planner, judge, and frontier smoke runs must be evidenced before claiming live end-to-end verification. A useful comparison report can report a negative or inconclusive result.

The research claim is supported only if a locked evaluation of unseen questions establishes the prespecified accuracy margin versus independent frontier research at acceptable coverage, with a meaningful measured improvement in total cost. Report latency separately and show whether the smaller pipeline adds value over direct small-model RAG. Use the observed results to judge the claim. Record the experiment as exploratory when the sample or independent adjudication is insufficient for confirmation.

At delivery, include verified startup commands, configuration instructions, test results, a sample decision and trace, an exported comparison, and a concise account of unresolved issues. Distinguish local fixture results, live smoke results, pilot outcomes, and confirmatory evidence.
