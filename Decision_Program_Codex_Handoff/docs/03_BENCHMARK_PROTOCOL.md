# Benchmark protocol

## Claim and study design

Primary question: can the standalone smaller pipeline, using fresh decomposition and a bounded knowledge base, make materially correct, source-supported decisions on unseen questions close to the quality of independent frontier research, at meaningfully lower total cost? Test the standalone path directly. Report program reuse and fallback separately. Use paired cases so each system sees the same question, scope, as-of date, and decision criteria.

| Stage | Source conditions | Purpose |
|---|---|---|
| **1 · Shared evidence** | Both paths receive the same independently assembled source excerpts, including relevant exceptions and ambiguity. Provide the question and scope but withhold the answer, reviewed plan, and reference reasoning. | Test whether the smaller planner can discover enough of the right structure when evidence acquisition is controlled. |
| **2 · Shared corpus** | Freeze one corpus and source-access rules. Give each arm the same opportunity to search within the corpus. Match smaller-arm budgets where possible and report each actual budget and any differences. | Test decomposition and the judge against direct smaller-model RAG, and measure how much quality drops when systems must locate the evidence. |
| **3 · Practical comparison** | The frontier model researches broadly using its actual configured tools. The smaller path uses the intended bounded corpus and evidence budget. | Test the original end-to-end proposition. Track which losses stem from decisive evidence outside the corpus. |

## Arms and comparisons

| Arm | Definition |
|---|---|
| **F · Frontier** | Real frontier model. Independent research and citations under the stage rules. |
| **D · Direct small model** | Same smaller generative model as the planner, with evidence access, a competent direct prompt, allowance for an additional bounded search under the matching policy, and a deferral option. |
| **P · Fresh predicates** | The same small model frames a fresh decision, scoped evidence goes to the local judge or exact operators, and the result is composed. One targeted extra retrieval round is permitted in retrieval stages. No reviewed program, frontier answer, or fallback enters the primary P run. |
| **C · Curated diagnostic** | On an approved analysis subset, inject a human-reviewed decomposition, a verified evidence packet, and then both. Keep the other components fixed where possible. | 
| **R · Program reuse** | Bind to an eligible pre-reviewed program using the same evidence, judge, and composition runtime as P. Freeze the program library before the reuse holdout. |
| **H · Hybrid fallback** | Optional deployment comparison. The smaller path can escalate to a frontier model under a prespecified rule. Record when it happened and count all calls and outcomes. |

Primary practical contrast is **P versus F**. Main controlled contrast is **P versus D**. Measure the contribution of the judge by running the same predicates, packets, and combining logic with the smaller generative model as evaluator on an approved subset. Measure the contribution of the second search with targeted retrieval on versus off. Optionally run bounded exhaustive retrieval and an evidence-withheld arm with the same predicates to isolate the value of selective acquisition and attached knowledge. Report separate arm IDs. Jig’s scripted run is a fixture control.

## Dataset and adjudication

- Begin with one bounded, versioned, nonclinical source collection. Select a narrow set of public authoritative documents, record their revisions and provenance, and pin the corpus manifest before holdout access. Choose questions whose answers and exceptions can be independently verified. Use executable checks only when they actually demonstrate the relevant behavior. Include enough questions that require interpretation, multiple sources, or exceptions to exercise the architecture.
- Separate development, pilot, and confirmatory sets. Group paired perturbations, source families, near duplicates, and shared rule variants. Split them together. Test unseen instances within scope, a distinct unfamiliar family or scope challenge, historical rule changes, conflicting or missing evidence, and deliberately irrelevant wording. Keep any explanatory source excerpts and all reference answers out of the evaluation prompts unless the stage specifically supplies original evidence.
- Record adjudicated labels, decisive predicates or facts, allowable equivalent answers, exact references, materiality, and expected deferral conditions. Keep the scoring material separate from the app’s live index and model inputs. Use reviewer adjudication blinded to arm identity for confirmatory work. Resolve disagreements under a fixed rubric and log changes before unblinding. The frontier model is a comparator. A case counts as jointly answerable if the reference can decide it under the declared task rules. In stage 3, missing knowledge in the smaller corpus can explain a loss and is not an automatic scoring exemption.
- Target roughly 60–100 independently adjudicated pilot questions as a planning range. A smaller smoke set establishes connectivity and mechanics. Use the pilot to estimate discordance, failure rates, latency, and adjudication burden. Freeze a fresh confirmatory holdout after choosing budgets, scope, and statistics. If independent review or sample size falls short, label the findings exploratory.

## Scorecard

| Metric | Definition |
|---|---|
| **Primary decision accuracy** | Fraction of all assigned cases with a materially correct, adequately supported decision, or a justified deferral on a genuinely unresolved case. Count unjustified deferrals, wrong decisions, technical failures, and invalid output as misses. Record their categories separately. |
| **Coverage and material errors** | Share of adjudicated answerable cases receiving a definitive decision. Separately report unsupported definitive answers on unresolved cases, material errors among issued decisions, and missed decisive conditions. |
| **Evidence quality** | Whether cited spans exist, support the decisive findings, and apply to the relevant entity, scope, and time. Report correct final answers with unsupported reasoning. |
| **Robustness** | Paired sensitivity to changes in decisive facts and rules, invariance to irrelevant changes, and correct deferral after removing indispensable evidence. Report paired cases by cluster. |
| **Latency** | End-to-end wall clock per assigned question, with median and p95, separated for cold and warm runs. Include acquisition, all model calls, retries, timeouts, and any fallback in its arm. Record stage timings for diagnosis. |
| **Cost** | Actual metered provider and tool costs or usage with pinned unit prices. Report unobservable costs explicitly. Include every assigned question, including failures, deferrals, retries, and fallback. Account for corpus preparation and maintenance at stated query volumes. Record local resource use and human review hours separately unless they have a documented valuation. |
| **Work performed** | Actual judge and planner calls, source calls, tokens, retrieved spans, evaluated and skipped predicates, and end-to-end status. Separate exact operations and simulated calls. |

Before unblinding, lock a practically meaningful margin and cost target. Earlier working targets were a **3 percentage point accuracy non-inferiority margin** and **50% lower total cost** at a stated recurring volume. Treat those as proposals and document the final rationale based on the question family. A claim of non-inferiority requires a prespecified paired interval for `accuracy(P) − accuracy(F)` whose lower bound exceeds the negative margin. Specify a one-sided confidence level, a method appropriate to paired outcomes and clustered variants, handling of missing results, and a coverage guard before collecting confirmatory results. Use the observed discordance and clustering from the pilot to size the final study. Report the paired estimate and uncertainty even if the result is inconclusive. Report actual latency separately, with the chosen practical target if one is set.

## Failure decisions

- If P trails F on shared evidence, use curated-plan and curated-evidence diagnostics to identify framing, judgment, or composition failures before investing in search.
- If P performs on shared evidence and drops on shared corpus, inspect decisive-span retrieval, rule applicability, and the effect of the targeted second search.
- If P and D perform similarly, retain components only when their evidence support, robustness, cost, latency, or diagnostic value justify the complexity.
- If H succeeds while P falls short, report the hybrid separately with escalation cost and standalone quality. If R succeeds while P falls short, report the supported question families and limits on program discovery.
- If P meets the practical target, report the scope and evidence conditions where it held. Keep all negative and inconclusive comparisons in the results record.
