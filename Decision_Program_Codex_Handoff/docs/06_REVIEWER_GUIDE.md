# Reviewer guide for exploratory comparisons

This guide explains the current workbench fields. It is not a validated review protocol, proof of reviewer independence, or a secure blinding system. Agree on a case-specific reference and adjudication procedure before a study, keep reference answers out of model inputs, and record disagreements separately. The [benchmark protocol](03_BENCHMARK_PROTOCOL.md) sets the intended study design.

## Before reviewing

Use an independently prepared reference appropriate to the question, scope, as-of date and study stage. Check the source's origin and version, and whether it is a derived intervention. Recorded origins and dates are claims, not proof of authority or availability. In a practical broad-research comparison, the frontier may use sources outside the bounded collection; assess those sources under the study's rules rather than assuming the local collection is complete.

Open the comparison's `/review` link. The page hides explicit arm names, but answer style, evidence structure and local files can reveal identity. Do not inspect the main app, run files, logs or exports that expose arms before completing review. For a confirmatory study, use a separately designed blinding and adjudication process; this interface alone is insufficient.

For current comparisons, the review interface withholds items until a case assessment is saved. Assess case answerability first, then evaluate each item against the same reference. Older comparisons can show items without that assessment. The application records the reviewer name and rationale; it does not verify identity, independence, source authority or reference accuracy.

## Case answerability

- **Answerable:** the reference can settle the question under the declared task rules. Cite the decisive reference and explain why it resolves the case.
- **Unanswerable:** the reference establishes that the case cannot be settled under those rules, such as a genuinely missing material fact or unresolved conflict. Identify the missing fact or conflict and supporting reference.
- **Uncertain:** you cannot determine answerability. Explain the uncertainty; do not infer missing facts from a failed search.

References are required for answerable and unanswerable assessments. Source metadata and exact text checks do not establish the reference's truth or applicability.

## Each review item

Judge **decision correctness** and **evidence support** separately:

- **Correct:** a decided answer materially agrees with the reference, or a deferral is justified for an unanswerable case. Explain the decisive comparison.
- **Incorrect:** the answer materially conflicts with the reference, a decidable case was deferred, or an unanswerable case received a definitive answer. Describe the error or missing condition.
- **Unresolved:** correctness cannot be settled from the available reference or output. Explain what is missing. A technical failure remains a failure in the scorer regardless of a review label.
- **Supported:** the recorded evidence adequately supports the material answer and applies to the relevant entity, scope and time. A matching quotation alone is insufficient. For web citations, inspect the source independently.
- **Unsupported:** the evidence is missing, irrelevant, contradictory, incomplete for a material claim, or attributed to the wrong source. A correct answer can still be unsupported.
- **Unclear:** the evidence or its applicability cannot be determined. A full-source context is not automatically a localized supporting citation; assess it under the agreed study rubric.

The structural citation indicator checks recorded bindings, not semantic support. A detected structural failure cannot be saved as supported. For a deferral, evidence support may be unclear; the scorer uses answerability and decision correctness to assess whether the deferral was justified.

## Save and hand off

Enter your name and a concrete rationale for each assessment. Verify the selections before saving: review records are immutable, and the interface does not provide an edit or reversal. Do not submit a replacement under a different name to conceal a mistake; record and resolve it under the study's agreed procedure before interpreting results. An administrator should preserve the original record and establish a documented correction path rather than silently editing local files.

For CLI review, `python3 -m workbench blind COMPARISON_ID` prints the review payload. `assess-case` records the case assessment, and `adjudicate` records each review item; run each command with `--help` for required fields. The payload may contain source text and review metadata, so share it only with authorized reviewers. Model responses and source material may be sensitive.

The exploratory scorer treats technical failures as incorrect, deferrals on answerable cases and decisions on unanswerable cases as incorrect, and uncertain assessments as unresolved. Decided answers marked correct require supported evidence to count as correct; unclear support remains unresolved and unsupported evidence is incorrect. An unassessed legacy deferral cannot count as justified. This describes current scoring behavior, not independent validation of the judgments.
