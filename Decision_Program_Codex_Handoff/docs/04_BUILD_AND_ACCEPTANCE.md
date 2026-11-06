# Build plan, acceptance, and release

## Stage 0 · Establish the workspace

Inspect the assigned repo, existing code, local instructions, Python environments, and available credentials. Inventory Jig only as far as useful for testing. Record the chosen project layout, dependency constraints, operating system, and model configuration. Use a clean project when no implementation repo is supplied. Pin dependencies after verifying installs. Do not require the Mac inference dependencies in the core app environment if an isolated worker is simpler.

Select one initial authoritative source collection and its source verification method. For the default Python documentation option, pick one small standard-library area and dated or versioned documentation snapshots. Record the official locations and verify what can be independently demonstrated with the correct interpreter version. Keep source records separate from question labels. Design the fixtures and held-out evaluation independently of the prompts.

## Stage 1 · Deterministic vertical slice

1. Implement the request, plan, evidence, result, and trace schemas. Add a local source registry, snapshot creation, and exact-span citation validation.
2. Implement the evaluator interface, three-valued composition, candidate relevance and stop conditions, explicit failure states, and run recording. Use a scripted fixture plan and evaluator to test mechanics.
3. Expose the runtime through a CLI. Demonstrate one resolved decision, one decisive intervention, and one justified deferral. Save their traces. Show the same run can be inspected from its pinned record.
4. Add the missing-entity, temporal, and override regressions from Jig. Confirm a fixture run performs zero network model calls and is visibly identified as a fixture.

## Stage 2 · Real models and shared evidence

1. Connect a smaller planner and direct-answer comparator, and wire the live frontier adapter. Require explicit configuration for each. Record versions, token limits, provider costs where observable, and call budgets.
2. Adapt the owner’s local typed judge and verify an actual model call on the intended Mac environment. Probe support, unsupported evidence, negation, and an input near the configured limit. Confirm output mapping, trace metadata, and error handling. Compare against the offline control on the same fixture predicates.
3. Run the shared-evidence comparison on a small independently scored set. Verify that the smaller planner creates its own predicates and that neither path sees the other’s answer. Run the curated-plan and curated-evidence diagnostics on failures.
4. If the pipeline fails here, preserve the results, improve the implicated component on development data, and retest on a fresh slice. A confirmed quality failure should change where development effort goes. Keep the runnable app and negative evidence deliverable.

## Stage 3 · Bounded knowledge and practical comparison

1. Implement snapshot-backed bounded retrieval with entity, scope, and date filtering. Start with exact lookup and lexical search. Add other retrieval methods only when error analysis supports them.
2. Implement the one targeted extra retrieval round and the evidence interventions. Measure the extra searches and calls. Compare with the same runtime configured without the extra search.
3. Run the shared-corpus arms, then the practical comparison when a broad frontier research route and an authorized budget are available. Record actual inputs and costs. Freeze arm configuration, budgets, corpus, and scorer for each report.
4. Run the exploratory pilot if an independently adjudicated set is available. Record open requirements for a confirmatory non-inferiority study. Carry forward the held-out boundary after changing prompts or runtime behavior.

## Stage 4 · Product workflow and delivery

1. Finish the Decide, Programs, and Compare views using the same service as the CLI. Implement program review and version history for the secondary reuse path. Add result, trace, and score export. Verify that saved runs can be reopened after restart.
2. Test install and startup from a clean checkout. Run focused automation for CLI, runtime, storage, and UI smoke flows. Demonstrate the same changed-fact and missing-source examples in the UI.
3. Provide setup, model configuration and budget guidance, a walkthrough, benchmark exports, and a concise results and limitations report. Verify the commands from the actual packaged checkout.

## Required acceptance checks

| ID | Check | Expected result |
|---|---|---|
| A1 | Offline install and demo | A clean supported environment launches the CLI and browser app, completes the synthetic demo, and labels its outputs as fixtures. |
| A2 | Real adapter smoke | Observed planner, Mac-local judge, and frontier calls generate valid records with backend identity, elapsed time, and usage status. Run modes are labeled. An unavailable backend yields an explicit failure with context. |
| A3 | Fresh framing and plan validation | An unseen question yields a fresh plan. Invalid operators, references, cycles, unhandled material conditions, or out-of-scope bindings are rejected or produce a meaningful deferral. |
| A4 | Missing entity versus inapplicable | Removing a material entity that a predicate needs cannot silently pass the check. An established inapplicability follows the explicit composition rule. |
| A5 | Temporal correctness | A query uses the program logic and evidence compatible with its as-of date. A missing pinned version fails explicitly. A future-dated observation cannot establish an earlier state when the task disallows it. |
| A6 | Conditional stopping | Early stop omits work only after showing the remaining predicates cannot change the result under the verified expression. A relevant exception survives a failed ordinary condition until the exception is settled. |
| A7 | Evidence integrity | A fabricated span, mismatched source version, wrong entity, unsupported negative from a partial search, or retrieved instruction that attempts to override the plan cannot create a supported conclusion. |
| A8 | Intervention and replay | A decisive change flips the expected decision, removal of indispensable evidence yields an appropriate gap, and a verified irrelevant change preserves the decision. Original runs and snapshots remain inspectable. |
| A9 | Fair comparison | The scorer uses independent labels, the provider arms see no gold labels or one another’s responses, and the fresh arm receives no saved program or frontier fallback. Replay of the same exports reproduces the score report. |
| A10 | Measurement | A run with retries, failure, or escalation retains costs and timings in its assigned arm. Simulations, unobserved usage, and measured charges are separate states. |
| A11 | Complete app flow | The user can run a question, inspect evidence, view and review a program revision, rerun an intervention, and export an arm comparison through the documented interfaces. |

Record commands and checks in the delivered README. Provide distinct commands or entry points for install, app startup, deterministic demo, automated tests, local judge smoke, stage-specific live comparison, scoring from saved runs, and export. Exact commands belong in the final implementation README after verification. Use fixtures or fake adapters for deterministic tests and separately identify networked smoke checks.

## Handoff evidence

Deliver source and pinned dependency configuration, a runnable app and CLI, example configuration with empty credential fields, the source manifest, fixture demo records, representative comparison exports, automated test output, and a short results report. State which checks ran, the environment, and the result. If local hardware, frontier access, spend limits, or independently adjudicated data prevent a run, identify the specific check still open and the command or input that would close it. Keep app completion, model smoke verification, pilot findings, and confirmatory non-inferiority distinct.
