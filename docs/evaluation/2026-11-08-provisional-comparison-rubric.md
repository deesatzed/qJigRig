# Provisional qJig comparison rubric

**Status: draft, not frozen and not yet executable.** This policy is proposed before any paid pilot or holdout results. It makes the tradeoffs in the completion contract explicit; it is not evidence of model quality, an independently adjudicated reference, or authorization to run providers. The current decision validator accepts a single proportion, but the existing review and scoring code does not yet produce the paired metric below. Do not feed this policy an asserted number and call the evaluation complete.

## Unit and denominator

For each holdout case and repeat, compare the combined arm separately with each of `direct_full_evidence` and `direct_retrieval`. Each comparison has one pair per assigned case/repeat, including failed and deferred runs. Keep both baseline comparisons and both repeats visible; do not pool them to disguise a failure against either baseline. The present draft has five holdout cases and two repeats: ten assigned pairs per baseline, subject to recomputation if the design is corrected before freeze.

Reference outcomes and evidence requirements are authored assertions with `authored_unvalidated` provenance. Do not expose reference labels, case identities or arm mappings to the answer-producing models. A separately budgeted review may see only the information appropriate to its recorded role; its opinion is `ai_reviewed_unvalidated`. Source authenticity, completeness and independent truth remain unestablished.

## Per-assignment outcome categories

Evaluate the request-level outcome, not a fresh run's conditional graph answer. Retain the raw result, cited evidence, reference and review records so each classification can be reconstructed.

- **Supported match:** a definite yes/no/conflict answer agrees with the attributed reference, the decisive evidence is present and applicable, and a separate attributed semantic review supports the answer and its evidence. Exact quotation presence alone does not establish support. For an expected unknown, an explicit unknown or deferral can be reference-aligned only when the authored case record identifies the missing or conflicting basis and the outcome-review procedure supports that characterization; a failed search alone is not such evidence.
- **Reference-misaligned:** a definite answer contradicts the attributed reference, a request defers where the attributed reference supports a definite answer, or a definite answer is given where the attributed reference calls for unknown/conflict. These are reference-relative classifications, not proof that the reference is correct. Report deferrals separately and call them `reference_indicated_unjustified`, not objectively unjustified.
- **Failed:** malformed response, provider error, timeout, invalid citation, or exhausted required work that prevents an evaluable request-level answer. Preserve the specific reason. An uncertain physical call also prevents spending reconciliation.
- **Unknown assessment:** missing assignment or required receipt, unavailable or uncertain semantic/outcome review, conflicting review evidence, or a reference that does not establish the necessary applicability or expected outcome. Never upgrade a conditional graph answer, model opinion or retrieval miss to a final answer.

A matching conditional fresh graph and its review are reported separately as diagnostic results. The current semantic reviewer assesses conditional graph support, not whether request-level deferral is appropriate; a separately specified and budgeted outcome-review mechanism is needed before a fresh deferral can be classified as supported or reference-misaligned under this rubric. No existing review is silently repurposed.

## Paired metric and decisions

For this exploratory decision only, order evaluable categories as supported match (2), reference-misaligned (1), and failed (0). For each complete pair award the candidate 1 if its category is higher than the baseline's, 0.5 if equal, and 0 if lower. `outcome_support` is the sum of candidate points divided by **all assigned pairs** for that baseline. An unknown assessment or missing pair makes the metric null; it is not omitted from the denominator and does not count as a tie or a zero. This ordering is a predeclared product tradeoff, not a statistical effect size or accuracy estimate.

For each baseline comparison, apply the following exhaustive, disjoint intervals on [0, 1]:

| Paired outcome support | Comparison result |
|---|---|
| Less than 0.40 | remove |
| At least 0.40 and less than 0.60 | revise |
| At least 0.60 | retain |

Combine the two comparisons conservatively: retain only when both say retain; remove only when both say remove; otherwise revise. If either metric is null, any assigned pilot/holdout work or required resource record is missing, any physical call is unreconciled, or the frozen design, isolation and receipt checks fail, report **inconclusive/incomplete** instead of selecting a category. A budget-exhausted partial campaign is incomplete, not a completed inconclusive comparison. These intervals are pragmatic decision boundaries for a small exploratory dataset, not statistically calibrated claims; with ten pairs each 0.5-point change changes the metric by 0.05.

## Required companion reporting

For each arm and comparison, show all case/repeat classifications and separate counts for supported matches, reference-indicated deferrals, failures, unknown assessments and missing assignments. Report evidence applicability/coverage, unsupported or invalid citations, conditional graph results, intervention pairs, repeat-level variation, elapsed time, call count, input/output tokens, known cost and unknown cost. Distinguish comparison-arm differences in source access, context, followups, extra model stages and total work. The existing $1/request and $25/goal ceilings are guardrails, not evidence of efficiency. Report resource use and differences; do not introduce a retrospective efficiency threshold.

## Before freeze

1. Validate the complete case/source/reference manifest, protected-label isolation, intervention links and actual assignment denominator. Correct the draft if necessary before any pilot or holdout results.
2. Specify and implement an outcome-review stage that can assess request-level deferral separately from conditional-graph support, with a role-appropriate privacy boundary, exact model/prompt/input and source bindings, same-goal budget allocation, unavailable/uncertain outcomes and replay. Resolve how it can assess the authored reference assertion without exposing labels to the evaluated model. Its output remains unvalidated.
3. Implement the paired calculation and two-baseline combination from anchored, verified records, with tests for failures, unknowns, missing pairs, repeat mismatches, contradictory review, thresholds and resource/receipt incompleteness. Integrate it with the existing criteria validator instead of accepting an unsupported asserted proportion.
4. Pin the complete design, rubric version, criteria, review model/configuration, source and reference hashes, quota and assigned work before pilot/holdout. Recheck full affordability and all billing/account restrictions. Until then, this document is a working proposal and the existing corpus retains its draft status.
