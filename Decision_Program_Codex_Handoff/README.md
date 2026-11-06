# Decision Program Workbench

This local workbench imports and pins text, runs fresh OpenRouter decomposition and direct/frontier supplied-evidence answers, validates literal source quotes, and saves runs for inspection. It supports shared-evidence, experimental shared-corpus and opt-in practical web comparisons, human review and export. The local typed judge is an optional evaluator for fresh and reviewed predicates and final-answer support. It is **not a validated comparison system**: the practical web route has not been exercised end to end, and independent evaluation and confirmatory benchmarking remain open. A supplied-evidence frontier run does not perform broad research.

See [RESULTS.md](RESULTS.md) for the concise evidence and remaining acceptance work.

## Run

Requires Python 3.10 or later; no third-party core dependencies. Copy `.env.example` to `.env` if needed, and configure `OPENROUTER_API_KEY`, `OPENROUTER_PLANNER_MODEL` (a chat-capable model), and `OPENROUTER_TOP_MODEL`. The existing `.env` remains local. The supplied `OPENROUTER_DEC_MODEL_1` is a typed extraction model and cannot generate a plan via chat completions; set `OPENROUTER_PLANNER_MODEL` explicitly. A separate typed Decisions API probe is available; it is not the pipeline judge. Provider-backed runs send the question and supplied source or retrieved excerpts to OpenRouter only after explicit source-sharing consent. Avoid sending sensitive or restricted data unless authorized. The configured endpoint is restricted to OpenRouter HTTPS.

The current offline suite has been run on Python 3.10.18 and 3.15.2 on macOS arm64; a prior suite was also run on Python 3.12.16. A separate Python 3.10 virtual environment ran the fixture demo and archive score replay. The optional local judge was verified separately on Python 3.12.

```sh
python3 -m venv .venv
.venv/bin/python scripts/offline_tests.py
.venv/bin/python -m workbench serve --port 8765
```

Open http://127.0.0.1:8765. Paste a source, save its immutable snapshot, enter a question, select an arm, authorize sharing, and run. Saved records appear below and survive restart. Snapshots and runs live in ignored `data/`; `WORKBENCH_DATA` can select another directory.

The offline test entry point blocks non-loopback DNS resolution, TCP connections and datagrams in the test process while allowing the local HTTP tests. It is a test guard, not an operating-system sandbox: child processes and other network APIs are not contained. Running `python -m unittest` directly does not install this guard. Live model smoke commands are separate.

The same service is available through the CLI:

```sh
python3 -m workbench import path/to/source.txt --title 'Source title'
python3 -m workbench list snapshots
python3 -m workbench run --snapshot SNAPSHOT_ID --question 'Your question?' --mode fresh --share-sources
python3 -m workbench list runs
python3 -m workbench show runs RUN_ID
```

Optionally add `--origin 'Source location or description'` to record provenance, or enter it in the browser's source form. The value is user-supplied metadata: the app does not fetch or verify it. CLI imports default to the local path; browser entries default to “user supplied.” Origins are included in source records and exports, so avoid putting credentials in them.

Modes include `fresh`, `direct`, `frontier`, `reviewed`, and `intervention`. The direct and frontier arms make independent calls using the selected evidence. JSON records include model identity, prompt hash, elapsed time, and provider usage if returned. Missing cost is marked unobserved. A failure is retained as a failed record, not silently substituted with fixture output. Reopening a record is replay; running it again invokes the model anew.

The predicate and answer evaluator selection applies to fresh, reviewed and intervention runs. Direct and frontier runs do not use that separate evaluator and record it as not applicable. Their lexical retrieval mode can be used without the local judge; lexical program runs require it.

Reviewed-program and intervention runs using the local judge can run without OpenRouter consent because those paths make no provider calls. Fresh planning, direct and frontier answers, and remote-evaluator runs still require consent; the provider invocation itself also enforces it. The local worker uses cached model weights, but this is not a general network-isolation guarantee.

For a stronger offline check of a saved run, choose **Verify saved evidence and composition** in its browser entry or run `python3 -m workbench verify-run RUN_ID`. This checks the saved source text and recorded metadata fingerprints, checks source-bound citation text and offsets where available, and recomputes the expression from recorded predicate outcomes. When only context passages are bound, the citation status says they are context and not localized support. The CLI exits nonzero when it detects an issue; a zero exit does not mean every check was available. Missing references, decisive predicate evidence and missing candidates are reported separately. It does not execute or validate model responses, establish that an excerpt supports an answer, verify web citations, authenticate records, or prove correctness. It cannot reconstruct an unrecorded result.

Recorded citation titles and observation dates are compared with the pinned source when present; missing attribution metadata is reported as partial. These fields remain user-supplied provenance, not independently verified authority.

When a saved result includes both a single-citation alias and a citation list, verification rejects conflicting text or references. It does not authenticate the record or establish semantic support.

The Decide view labels the title attached to an excerpt as recorded metadata. Opening the source checks any recorded title and observation date against the pinned source as well as checking text and offsets; a mismatch is shown as an error.

The Decide page initially loads source metadata and saved-run summaries. Opening a run fetches its full record on demand; the server still reads the local JSON records to build its lists, so this is not a database or a guarantee of performance on large stores.

Date and scope filters use the source metadata supplied at import, not an independently verified source authority. Exact quote validation establishes that a span exists, not that it supports the model's conclusion. Model-generated plans may miss conditions; all results require review. Shared-evidence mode sends the full source text and does not enforce provider token budgeting. The planner allows one bounded repair call. Large inputs may fail at the provider. The browser binds to loopback; it is intended for a trusted local machine, not deployment.

CLI file imports and derived snapshots decode UTF-8 without converting line endings, and the snapshot hash covers that text encoded as UTF-8. Browser file loading rejects invalid UTF-8 instead of replacing invalid bytes; browser text editing and paste may normalize line endings. Snapshots created before these changes are not rewritten.

Use **Check setup** in the browser or `python3 -m workbench preflight` to inspect local configuration without contacting a provider or revealing the key. The check reports whether configuration values are present, the judge Python is executable, and required judge package metadata is installed. It does not validate the key, package imports, hardware, model access, or spending limits. A practical web run additionally requires the web tool budget to be configured and separately authorized.

Before planner calls, local-judge runs and comparisons check the configured Python executable and the installed metadata for Unsloth, MLX, Transformers and Hugging Face Hub; dataset preparation performs the same checks. These checks do not prove that packages import successfully, hardware works or model weights are available. If source search finds no evidence and defers before model work, no worker check is required.

New source and question-set dates are stored as calendar dates in `YYYY-MM-DD` form. Effectivity checks also parse legacy source dates before comparing them, rather than ordering their original strings. Existing saved records are not rewritten; a reviewed program bound to a legacy noncanonical question date may need to be drafted and reviewed again. Runtime fingerprint changes prevent resuming older unfinished experiments under changed date behavior.

See [PROGRESS.md](PROGRESS.md) for verification and outstanding acceptance requirements, and [GOAL.md](GOAL.md) for the full intended scope.

For an explicitly recorded intervention, use the browser's **Derive an intervention** form. Select an individual source and choose **Load original text for editing**, then modify it and save a derived snapshot. Alternatively, create a new file containing the modified text and run:

```sh
python3 -m workbench derive --parent SNAPSHOT_ID --file changed.txt --title 'Intervention' --reason 'Describe the controlled change'
```

This creates a new snapshot with a parent link. Run the original and intervention separately; the reviewed-program intervention report described below compares their recorded results and traces.

The typed model settings in the supplied `.env` are distinct from the generative planner. A limited experimental support probe is available:

```sh
python3 -m workbench decision-probe --snapshot SNAPSHOT_ID --question 'A proposition to check' --share-sources
```

It defaults to `OPENROUTER_DEC_MODEL_3` and calls OpenRouter's Decisions API. The returned score is not a verified fact; absence of support is not proof of contradiction. It is a diagnostic probe, not yet the fresh pipeline's local judge. The supplied `OPENROUTER_DEC_MODEL_1` (Clairic) is an extraction model and requires a different endpoint.

## Shared-evidence comparison and review

Enter a question and pinned source in the app, check source-sharing consent, and select **Run comparison**. This makes live calls for all three arms. Save the resulting comparison ID and give it to an independent reviewer, who can open `/review` to see anonymized answers and evidence. Once every item in the associated dataset has a recorded judgment, **Open report after review** reveals the arm IDs, judgments, timing, and any complete provider-reported costs. The review interface hides explicit identities but is not access control; output style or evidence structure may reveal an arm, and local files and the main app expose run details. It is therefore not sufficient for a confirmatory blinded study. The report covers one case and does not establish accuracy or non-inferiority.

The review page shows each item's recorded citation check as structural information only. It does not decide whether a passage supports an answer; the reviewer must assess that separately. The type of evidence or check result may reveal an arm. External web citations are not independently verified.

Give reviewers the [exploratory reviewer guide](docs/06_REVIEWER_GUIDE.md), which explains the case and item fields, the current scorer, immutable records and the limits of blinding.

Review also displays recorded source origins and, for derived snapshots, their parent IDs and intervention reasons. Collection members identify whether their metadata is pinned to the comparison; older unpinned member metadata is labeled accordingly. These are recorded claims, not independently verified provenance.

For a source-bound answer citation, predicate quotation or retrieved span, **Show citation in source** highlights the recorded text within its pinned source after checking the reference and attribution. Predicate quotations and retrieved context remain separately labeled. The surrounding source can help assess context, but neither the highlight nor surrounding text establishes support automatically. Web citations and unbound quotes do not get this control.

Predicate evidence also shows the associated question and usable outcome. When a guard changed a model proposal, the original reported outcome is shown separately; the original proposal is not the runtime's accepted outcome. These details can reveal an arm and do not make the review securely blinded.

A citation with a detected structural failure cannot be saved or reported as `supported`; a reviewer can mark it `unsupported` or `unclear`. Unavailable or partial checks, including external web citations, are not automatically treated as failures and still require reviewer judgment. A structurally verified citation is not automatically supported.

CLI equivalents:

```sh
python3 -m workbench compare --snapshot SNAPSHOT_ID --question 'Your question?' --share-sources
python3 -m workbench blind COMPARISON_ID  # inspect the case and source
python3 -m workbench assess-case COMPARISON_ID --reviewer 'Independent reviewer' --answerability answerable --rationale 'Why the case is answerable' --references 'Specific source references'
python3 -m workbench blind COMPARISON_ID  # view review items after assessment
python3 -m workbench adjudicate COMPARISON_ID REVIEW_ID --reviewer 'Independent reviewer' --verdict correct --support supported --notes 'Evidence and reason for this judgment'
python3 -m workbench report COMPARISON_ID > report.json
```

Repeat adjudication for each review ID. `unresolved` and `unclear` are available when review cannot settle correctness or support. Reviews are immutable and report generation is blocked until all items have a judgment. Cost is labeled incomplete when a failed run or missing provider usage prevents a complete total. The report can be exported as JSON. Dataset scoring is exploratory; confirmatory statistics remain unimplemented.

## Offline fixture and reviewed programs

`python3 -m workbench fixture-demo` runs a clearly labeled synthetic exception, changed exception, and missing-fact example with no network calls. It is a scripted mechanics demonstration, not a model quality test.

Open `/programs` to save a draft from a fresh run and explicitly review a revision. A reviewed revision is eligible only for the exact original question, scope, as-of date, and pinned snapshot. Review is a recorded human action, not a validated admission process or evidence of independent review. Reviewed execution uses the selected predicate evaluator. Equivalent CLI commands:

```sh
python3 -m workbench program-draft FRESH_RUN_ID
python3 -m workbench program-revise DRAFT_ID --plan-file edited-plan.json --author 'Reviewer' --rationale 'Reason for edit'
python3 -m workbench program-review DRAFT_ID --reviewer 'Reviewer' --rationale 'Review rationale'
python3 -m workbench run --mode reviewed --program REVIEWED_ID --snapshot SNAPSHOT_ID --question 'Original question' --share-sources
```

Include the same `--scope` and `--as-of` as the original request when those were set. Inspect with `python3 -m workbench list programs` or `python3 -m workbench show programs PROGRAM_ID`.

An edit creates a new draft revision and preserves its parent, original model run, author, and edit rationale; it does not automatically approve the plan. Review the new draft ID separately. The Programs page can load and edit draft plan JSON. Plan syntax validation does not establish semantic correctness.

## Frozen question sets

Import your source first. On `/datasets`, select a saved source or collection and add questions individually; the advanced JSON editor remains available for bulk entry. For CLI use, create a UTF-8 JSON file containing an array of objects like:

```json
[{"case_id":"case-1","question":"Your question?","snapshot_id":"SNAPSHOT_ID","scope":"","as_of":""}]
```

Do not include reference answers in this file. Freeze and run it using `/datasets` in the browser, or:

```sh
python3 -m workbench dataset-freeze cases.json --title 'Evaluation inputs'
python3 -m workbench dataset-run DATASET_ID --share-sources --max-calls 15
python3 -m workbench dataset-status DATASET_RUN_ID
python3 -m workbench dataset-score DATASET_RUN_ID > score.json
```

The minimum call cap is fifteen times the number of cases (1–100 cases); it bounds the current worst-case number of calls, not monetary spend or total tokens. Review every comparison via `/review` or the CLI before scoring. The score explicitly counts failures and unresolved judgments. It is exploratory, and the blinding limitations above apply. Dataset runs created with the recovery journal can resume cases that have not started or reconnect a fully saved comparison. If an intent exists without a completed comparison, the app stops and marks the case uncertain rather than silently repeating possibly billed calls.

If all three arms fail for a case and more cases remain, the dataset stops after saving that case's receipt. Inspect the saved results and charges before explicitly resuming; resume skips the completed failed case and continues with the next one. The stop identifies a broad failure pattern, not its cause or all possible provider failures. Practical-web continuation has additional restrictions described below.

Synchronous `dataset-run` prints its saved run ID to standard error before starting comparisons, while its final result remains JSON on standard output. An ordinary later error also includes the run ID. If abrupt termination prevents the announcement, use `list dataset_runs` and inspect the journal before resuming.

Recovery also checks that the saved total and per-case reservation cover the current worst-case call budget before starting work. Runs with missing or insufficient reservations cannot resume under the current runtime; their saved records remain available for inspection.

A frozen public source example is included at `starter_corpus/python-3.12.10-keyword.rst`; its version, official upstream URL and SHA-256 are in `starter_corpus/manifest.json`. It is a small connectivity example, not an independently adjudicated evaluation set.

Recent development tests found that a syntactically valid generated expression can still produce the wrong answer. In one synthetic exception case, the evaluator handled the individual facts but the generated composition mapped them to the wrong outcome. Treat every output as unverified and inspect its plan and evidence; this app is for experimentation, not autonomous decisions. A false branch for a question that does not begin with a recognized yes/no auxiliary is conservatively deferred; this syntax check does not validate semantic correctness.

A [synthetic direct-answer probe](examples/direct_instruction_live_probe.json) returned a wrong, decided answer after following an embedded grading instruction, even while quoting the rule and measurement that contradicted that answer. This is a single developer-authored test, not an estimate of attack success. Direct and frontier baselines do not receive the fresh arm's separate answer check; an exact citation is not evidence that the answer follows.

The planner's instruction to treat source text as untrusted is not a reliable security boundary. In a [synthetic forged-authority probe](examples/instruction_injection_variant_live_probe.json), it incorporated an assistant-directed notice into the decision and the judge accepted that predicate. The run deferred for a separate unresolved fact; a different result on that fact would have led the generated plan toward the wrong answer. Inspect plans and source text, especially when evaluating untrusted documents.

Fresh, reviewed-program and intervention runs defer before predicate evaluation when a narrow textual pattern connects an apparent instruction to ignore a rule, policy, question or instructions with a predicate about overriding or ignoring a directive. A matching draft cannot be promoted without revision. This heuristic can miss reworded attacks and can also defer legitimate material or prevent its promotion. It is not applied to direct answers and does not establish instruction resistance. The plan remains available for inspection.

A separate narrow predicate-citation guard downgrades to unknown a remote judge's true or false proposal when its cited passage matches a pattern such as ‘the assistant must respond’. It retains the original proposal and quotation. This may defer legitimate questions about instructions, misses paraphrases and other attack placements, and does not apply to local-judge evidence, answer checks, or direct/frontier baselines. In a [different synthetic probe](examples/quote_guard_live_probe.json), the answer check itself followed a forged note and rejected a correct candidate; the citation guard did not fire. Neither result establishes general instruction resistance.

The result view's **Inspect generated plan** disclosure shows the saved predicates and branches, including when a fresh run defers before predicate evaluation. This is model output and requires review.

Fresh and reviewed decisions include a separate configured-model check of the proposed answer against the source. A contradictory, uncertain, malformed, or unquoted check defers the candidate. Agreement is still unverified model output, not independent adjudication, and can be wrong. This additional call is included in the dataset call cap and recorded in the run.

## Optional local MLX judge

On Apple Silicon, an isolated Python 3.12 environment was verified with Unsloth 2026.11.2. To recreate it, run `python3.12 -m venv .venv-judge` and `.venv-judge/bin/pip install -r requirements-judge.txt`. Download and smoke-test the pinned public model once with:

```sh
.venv-judge/bin/python scripts/local_judge_smoke.py --output data/local_judge_smoke.json
python3 -m workbench local-judge-probe --snapshot SNAPSHOT_ID --claim 'A claim to check against the source'
```

The worker uses cached weights only during normal use and rejects a fully serialized input above 4,096 tokens rather than silently truncating it. If using another environment, set `LOCAL_JUDGE_PYTHON` to its Python executable. The first model smoke may download several gigabytes. Resource usage and local cost are not measured.

New local judge responses record the worker's Python and selected package versions. New local-judge dataset runs also save these version strings at preparation, check them before resume and each case, and compare saved inference metadata before accepting a completed case. A decided local fresh arm must have both recorded predicate inference and a final local check. A mismatch or missing inference record after the fresh arm saves its arm receipt and stops before the remaining arms; inspect the incomplete journal rather than retrying blindly. This does not detect changed code with the same version or authenticate the environment; standalone comparisons do not freeze the environment. Older records lack these fields and older unfinished local datasets cannot resume under the changed runtime.

To use the local judge for **predicate and final-answer support checks** for a fresh or reviewed run, select it in the browser and supply an explicit exploratory threshold, or add `--judge-backend local --local-threshold 0.9` to `run`, `compare`, or `dataset-run`. The example threshold is not calibrated. A low score or false choice means unknown, not contradiction; it causes deferral. Fresh planning uses OpenRouter and requires source-sharing consent; reviewed and intervention runs using the local judge do not invoke that planner. Each predicate is represented by model-generated positive and negative claims, scored separately; only positive support above the threshold establishes either side, neither side gives unknown, and both give conflict. Their logical opposition is not mechanically guaranteed. The local judge does not supply exact spans; the trace identifies the entire pinned source as evidence context, not a localized supporting citation. New shared-evidence records bind that full context to source offsets, but verifying those offsets does not establish support. It is started once for the predicate batch and once for any final check, so wall time includes model startup; no resident cross-run service is implemented.

The observed synthetic support, unsupported and negation probes are in `examples/local_judge_smoke.json`. A near-limit input of 3,670 serialized tokens ran and a 5,170-token input was rejected. These checks establish an adapter path, not model calibration, decision quality, or general safety.

In a further [synthetic paired-entity probe](examples/local_judge_paired_entity_smoke.json), the local judge and an illustrative 0.8 threshold classified an explicitly contradicted entity as false and an unmentioned entity as unknown. This one example does not establish general protection against wrong-entity conclusions or calibrate the threshold.

The [synthetic irrelevant-change probe](examples/irrelevant_intervention_live_smoke.json) records a reviewed-program baseline and an intervention that adds a venue color outside the stated permit rule. Both real-model runs returned the same decision. This is a developer-reviewed development example, not independent or general invariance evidence.

On macOS arm64 with Python 3.12.16, the pinned judge requirements were also installed into a separate temporary environment and the worker completed a public-documentation probe using the already-cached model with offline mode enabled. This verifies one clean dependency environment on this machine, not a fresh model download, another platform, or model accuracy.

## Experimental lexical retrieval

For a fresh or reviewed local-judge run, choose **Experimental lexical retrieval** in Decide or add `--evidence-mode lexical --judge-backend local --local-threshold 0.8` to `run`. The threshold is an illustrative setting, not calibrated. The planner receives up to five matching passages; each local predicate receives up to three passages, with one extra search for unresolved predicates. The final local check receives up to five passages. Exact source offsets and retrieval queries are retained in the trace; selected passages are evidence context, not verified support. A missing hit defers and is never treated as proof of absence.

Lexical retrieval can miss synonyms, exceptions, entities, scope, and time applicability; it searches a pinned source or collection and does not independently resolve source authority or historical applicability. The sample query has not been independently adjudicated. Compare and dataset runners default to shared evidence; explicitly select shared corpus to run bounded retrieval for all arms.

## Multi-source collections

Import each text or Markdown document as a separate snapshot, using the same scope and effective dates for all members. On the Decide page, select the source snapshots, adjust their displayed order, and save the collection. Advanced ID entry remains available. Alternatively use:

```sh
python3 -m workbench collection --title 'My collection' SOURCE_ID_1 SOURCE_ID_2
```

The collection ID can be selected like a source snapshot. Member IDs, content hashes, and character offsets are retained; missing or changed members fail explicitly. Citation mapping rejects spans that cross source boundaries, and lexical evidence includes the member source ID and offsets. Sources with differing scopes or date ranges must be kept in separate collections; automatic source-authority and historical version resolution remain unimplemented. To intervene, derive a member and build a new collection rather than editing an existing collection.

Direct and frontier supplied-evidence answers can record up to six separate source quotations. Each must map uniquely to one pinned source, and in lexical mode each must also have been supplied to that arm. A legacy single quote remains supported. The decision and blinded review views expose the separate citations; exact matching alone does not establish that they support the answer.

## Shared-corpus comparisons

Select **Shared corpus** and the local evaluator in the browser, or add `--stage shared-corpus --judge-backend local --local-threshold 0.8` to `compare` or `dataset-run`. The threshold is illustrative and uncalibrated. Each arm starts with up to five independently retrieved lexical passages from the same pinned source or collection. The direct and frontier arms may each request one extra bounded search; fresh performs its own per-predicate retrieval and at most one follow-up per unresolved predicate. Actual retrieval budgets differ and the report records search counts; the frontier arm is still bounded to this corpus, not broad research. Each direct/frontier citation must match a passage supplied to that arm and map to an original source. A matching quote alone does not prove the answer is correct.

Lexical retrieval retains a preceding reStructuredText function, method, class, data or attribute directive with its indented description and immediately following version-added, version-changed or deprecated annotations when the combined passage fits the size limit and stays within one source member. This helps preserve identifiers and version context in the included Python documentation; other document structures can still lose necessary context.

Dotted numbers such as `3.9` and common attached prerelease forms such as `3.9.0rc1` are retained as lexical tokens. This is not a complete version grammar: other suffix formats can still be split. Tokens are not interpreted as semantic versions or numeric comparisons, and a match alone does not establish temporal applicability.

For direct/frontier lexical answers, an exact source citation may span separately supplied passages only when every non-whitespace character in the citation was exposed at that exact source position. Gaps containing hidden text are rejected, as are citations crossing source boundaries. Whitespace-only normalization remains separately recorded when used.

The shared-corpus path has only development smoke evidence and does not yet establish comparable retrieval quality, full budget parity, or a confirmatory benchmark. Inspect failures and adjudicate results independently.

Dataset scoring includes decision rate over all assigned cases, adjudication categories, paired outcome counts, and median/p95 end-to-end latency. Decision rate is not answerable-case coverage; cold/warm state and local resource cost remain unobserved.

The Markdown work summary totals recorded local inference counts per arm only when every assigned case has a valid count; otherwise it shows unknown. A failed local run or missing batch count is not treated as zero. Local inference counts are not a measurement of energy use or monetary cost.

To export a human-readable report after all reviews:

```sh
python3 -m workbench dataset-score DATASET_RUN_ID --format markdown > report.md
```

The individual report gate also waits for all cases in a dataset before unblinding. This is a workflow guard, not secure access control: local files remain accessible and answer style can reveal an arm. The sample [comparison export](examples/comparison_smoke.json) contains synthetic data and developer judgments, not independent adjudication or research evidence.

After the review gate, the individual comparison report includes each arm's answer, reason and available source references or web citations. It also indicates whether decided answer strings differ exactly; different wording does not establish a semantic disagreement or correctness. Dataset score rows remain unchanged so historical score archives can still be replayed.

Before each comparison arm starts, the workbench saves a comparison intent and an arm intent; after an arm returns, it saves a receipt linking the arm to its run. If execution is interrupted, inspect them with `python3 -m workbench list comparison_intents`, `python3 -m workbench list comparison_arm_intents`, and `python3 -m workbench list comparison_arm_receipts`. These local records reveal arm identities and should not be shown to a blinded reviewer. An arm intent without a receipt has an uncertain outcome: the process may have stopped before, during, or after a provider call, so it must not be assumed free or automatically retried. A crash between saving a run and its receipt may leave an unlinked run. This journal helps inspection; it does not automatically resume a single comparison or guarantee recovery of in-flight charges.

On the Decide page, **Find saved comparisons** lists journaled comparisons and links completed ones to blinded review. An incomplete entry is labeled “in progress or interrupted” because the journal alone cannot tell whether its worker is still active. The button does not resume or retry anything. Comparisons made before journaling was added do not appear in this list.

For bounded and experimental web model calls, the workbench also saves a run intent and a call intent before each provider request, followed by a receipt when the call returns or reports a provider error. **Find uncertain calls** lists runs without a final record and final runs whose call intents and receipts do not match. Inspect their call records with `python3 -m workbench list run_call_intents` and `python3 -m workbench list run_call_receipts` before retrying: an intent without a receipt may have incurred an unknown charge, and may still be active. If receipt writing fails after a response, the app attempts to retain observed cost and response in a failed run record; this depends on that final record being writable. The journal does not resume work automatically, does not cover a process failure before intent creation, and cannot reconstruct costs the provider did not report. Receipts can contain model responses and should be handled with the same care as run records.

## Experimental practical web comparison

Practical comparisons are experimental and require explicit acceptance that the requested spending and search limits may be exceeded. A live OpenRouter server-tool smoke requested one search but the provider reported two; therefore the requested setting cannot be relied on as a hard spend limit. The original record was created before this check existed and is superseded by [the budget audit](examples/web_search_budget_audit.json). The route uses OpenRouter's [web-search server tool](https://openrouter.ai/docs/guides/features/server-tools/web-search); provider citations and returned snippets are not independently verified.

The current adapter was also exercised offline using the saved answer, annotations, and usage from that historical overrun; the [replay summary](examples/web_overrun_current_replay.json) shows that it now fails the arm while retaining the reported cost. The original full HTTP response was not retained, and this reconstruction does not test current provider behavior.

Usage checks recognize both `server_tool_use` and `server_tool_use_details` response fields. If both report counts, the larger count is used; a bounded arm rejects reported server-tool use. Provider reports may still be incomplete, and observing a count after a call does not enforce a spending limit in advance.

For practical web requests, a reported web-search count over one or a reported total of more than one executed server-tool call fails the web arm, even if the other count says one. Missing or unreported tool usage is not proof that the requested limit was enforced.

The web arm also requires the provider to report a normal `stop` finish before marking a cited response decided. A truncated, filtered, or missing finish reason defers while retaining the partial provider response, citations and usage for inspection; a normal finish does not establish correctness.

Bounded OpenRouter calls similarly reject incomplete or unconfirmed finish reasons, even if the returned text parses as JSON. Their failed-call records retain the reported usage and partial response; this is recorded as a technical failure, not a supported decision.

Comparison reports distinguish a complete provider-reported web-search count from an incomplete count. When a call omits search usage, `web_search_requests` is null and `observed_web_search_requests` retains any reported subtotal; no provider calls is recorded separately. A missing usage field is not evidence of zero searches. Because the report schema changed, verification of older exported reports may show a mismatch with the current scorer.

Practical JSON and Markdown scores also show the requested per-request web tool-loop budget and aggregated reported web searches and total server-tool executions by arm. The budget is not a guaranteed total spending cap. An incomplete count remains unknown, with only the observable subtotal shown; a missing subtotal is not shown as zero. Practical archives exported before execution counts were added may no longer reproduce their exact score with the current scorer.

For troubleshooting only, `python3 -m workbench web-research --question 'A public question' --allow-web --accept-unenforced-budget` makes an explicit diagnostic request. The provider can exceed the requested one-search limit and incur additional cost. An observed overrun is recorded as a failed run; missing tool usage or citations yields a deferral. The request sends the question and scope to the model and its search provider, but does not send the local source collection. Do not use sensitive questions unless that sharing is authorized. The practical route has not yet been exercised end to end with the current controls.

The diagnostic now requests `parallel_tool_calls: false` and explicitly disables the separate web plugin while using the server tool. These are requested mitigations, not a proven hard limit; the acknowledgment is still required. OpenRouter documents [parallel function calling](https://openrouter.ai/docs/api/api-reference/chat/send-chat-completion-request) and notes that a [web plugin can coexist with the server tool](https://openrouter.ai/docs/guides/features/server-tools/web-search).

Optionally set `OPENROUTER_WEB_TOOL_BUDGET_USD` to a positive finite dollar amount in `.env` for a diagnostic or practical comparison. The request then asks OpenRouter to stop the server-tool loop at that spend threshold and after one step. The stop conditions replace `max_tool_calls`, per [OpenRouter's server-tool documentation](https://openrouter.ai/docs/guides/features/server-tools); the separate search `max_uses` request remains. This is a requested tool-loop stop, not a verified cap on total model and search charges: enforcement, possible overshoot, and billing coverage have not been established. Practical comparisons require this setting plus explicit web and unenforced-budget acknowledgments; the diagnostic also requires acknowledgment.

To try a practical comparison only after accepting that the requested limit may be exceeded, set a positive `OPENROUTER_WEB_TOOL_BUDGET_USD` in `.env`, select **Practical web research**, select the local judge and threshold, and check both web authorization and the spending acknowledgment. Or use `compare --stage practical --allow-web --accept-unenforced-budget --judge-backend local --local-threshold 0.8` with the usual question, snapshot, and source-sharing options. For a frozen set, use the same flags with `dataset-run --max-calls 15` per case. This call ceiling is not a dollar cap. The frontier receives the question, scope and date and uses web research independently; it does not receive the local corpus. Future-source exclusion for historical-as-known questions cannot be verified, so that combination is rejected. Provider URLs and excerpts need independent review. A reported search overrun fails the frontier arm, and a multi-case run stops before the next case if web use failed or was not reported as exactly one search. A missing report is not proof of no charge. No current live end-to-end practical comparison has been run; use only an authorized budget and non-sensitive questions.

Bounded comparisons and dataset runs freeze the configured small/frontier model IDs and prompt hashes before calls, and retain the provider-reported routed model, provider, generation ID, and usage when returned. Changing `.env` does not change the requested model IDs partway through a dataset run. The web plugin is explicitly disabled in bounded requests; any reported web/server-tool use or URL citation causes the response to be rejected. Provider enforcement and unreported tool activity cannot be independently verified from this check. Model aliases and upstream provider versions can still change, so frozen IDs are not a guarantee of identical model weights.

## Recovering a dataset run

Use `python3 -m workbench list dataset_runs` to find saved IDs, then `python3 -m workbench dataset-status DATASET_RUN_ID` to inspect receipts, active state, and pending cases. Use `python3 -m workbench dataset-resume DATASET_RUN_ID --share-sources` to resume. The dataset page also lists runs and offers safe resume. The app uses an exclusive local lock, pinned model and prompt settings, and immutable case intents. A completed comparison can be reattached without additional model calls. An intent without a completed comparison is **uncertain**: one or more model calls may have occurred, so it will not be retried automatically. Inspect saved run records and provider usage before choosing further action. Legacy runs created before journaling cannot be resumed automatically. Local process and filesystem failures can still leave orphaned model calls.

## Reviewed-program interventions

A reviewed revision can be evaluated experimentally against one directly derived source snapshot, or a new collection with exactly one original member replaced by a directly derived member or removed. Question, scope, date, and source order must remain the same. This is a diagnostic use of the original plan, not approval of a revised plan. Removing a source always defers a would-be decision because its materiality has not been independently established.

For a recognized yes/no question, a composed answer containing `if`, `unless`, or `provided that` is conservatively deferred even if the model support check accepts it. The proposed answer remains in the run record for review. This word-based guard can defer an answer that is actually complete, and it does not detect every non-answer or validate the plan.

In Decide, select a reviewed program and choose **Use program and original request** to fill its original question, scope, date, and source. For an intervention, then select **Reviewed program intervention**, enter a reason, and select the derived snapshot. The runtime checks the saved binding. If the plan was edited, first run the reviewed program on its original source and use that run as the baseline; an unchanged plan can also use its originating fresh run. Compare using `/programs` or:

```sh
python3 -m workbench run --mode intervention --program REVIEWED_ID --snapshot DERIVED_SNAPSHOT_ID --question 'Original question' --intervention-reason 'Describe the one source change' --share-sources
python3 -m workbench intervention-report ORIGINAL_RUN_ID INTERVENTION_RUN_ID > intervention.json
```

The report compares status and answer text, and preserves both traces; it does not determine semantic equivalence or causal correctness. When both runs use the local judge, it also compares recorded worker version metadata, marking missing or internally inconsistent metadata unknown. Matching versions do not prove identical binaries or behavior. The [synthetic intervention example](examples/intervention_smoke.json) was reviewed by the developer, not an independent adjudicator.

Reports require the saved intervention plan and source hash to match the reviewed program and selected snapshot; recorded source metadata is checked when present. Older records missing the plan or source hash can still be inspected but cannot produce this report. These checks do not authenticate records or establish that a plan is correct.

## Historical as-known runs

At source import, an optional observation date records when the supplied content was available. It is a user-supplied provenance assertion, not independently verified. Effective dates and observation dates are separate. For a historical-as-known question, set an as-of date and choose **Historical as known** in the browser, or use:

```sh
python3 -m workbench import source.txt --title 'Source' --observed-at 2023-01-01
python3 -m workbench run --snapshot SNAPSHOT_ID --question 'Your question?' --as-of 2024-01-01 --historical-as-known --share-sources
```

The runtime checks every collection member: a missing observation date or one later than the as-of date causes a deferral before any model call. The same option is supported by `compare` and by a `historical_as_known: true` field in dataset case JSON. A derived intervention receives its creation date as its observation date. Existing snapshots without an observation date remain unknown; create a new snapshot with a supported date rather than altering the old one. This check does not establish source authority, policy-version applicability, or the truth of the supplied observation date.

The source form also accepts a local text, Markdown, or reStructuredText file. Selecting a file fills the text editor; it is saved only when **Save source snapshot** is selected.

### Case answerability

New comparisons require a separate case assessment before review items are displayed or adjudicated. A reviewer records whether the case is answerable, unanswerable, or uncertain under the task rules, with a rationale and reference evidence. This record is separate from each arm's output and is never sent to models. The app cannot verify reviewer independence or reference validity; source and answer style may also reveal an arm.

On `/review`, complete **Case answerability** as well as the individual arm judgments. The CLI equivalent is:

```sh
python3 -m workbench assess-case COMPARISON_ID --reviewer 'Reviewer' --answerability answerable --rationale 'Why the case is answerable' --references 'Specific source references'
```

Choose `unanswerable` or `uncertain` when appropriate. Dataset scores report coverage on assessed answerable cases and separately count uncertain or legacy cases. A deferral on an assessed answerable case and a definitive answer on an assessed unanswerable case count as misses. This is a human assessment workflow, not an independently validated benchmark. Older comparisons remain readable without a case assessment and are labeled as legacy/unassessed in dataset summaries.

A legacy deferral marked correct without a case answerability assessment is scored unresolved rather than counted as justified. Historical archives containing such cases can therefore produce a score mismatch when replayed with the current scorer.

The browser service binds to `127.0.0.1` and accepts only loopback Host headers for its selected port. POST requests require JSON and reject a mismatched browser Origin. Provider-sharing and web authorizations require an explicit JSON boolean `true`; strings and numbers are not accepted as consent. These checks reduce exposure to cross-origin requests and accidental authorization; they do not authenticate other processes or users on the same machine and do not constitute a security audit. Run it only on a trusted local machine.

### Clean-environment check

On macOS arm64 with Python 3.12.16, an isolated copy excluding `.env`, `data/`, and both existing virtual environments passed 68 offline tests and the fixture demo using a new standard-library-only virtual environment. A synthetic browser import and live direct OpenRouter call then completed using credentials passed through the process environment, and its saved run reopened after the server stopped. The redacted synthetic record is [clean_copy_smoke.json](examples/clean_copy_smoke.json). This did not verify the local-judge install in a second clean environment, independent adjudication, or every browser workflow.

The Decide view displays the result, recorded gaps, and expandable predicate/evidence context. For citations with source offsets, **Open exact passage in source** reopens the pinned snapshot and highlights the recorded span after checking its source hash and exact text. Older runs without source offsets remain inspectable but cannot open an exact passage. The saved-run list can reopen a run without making another model call; raw JSON remains available under the full-record disclosure.

## Predicate stopping control

Remote-predicate runs default to targeted stopping. The runtime enumerates the Boolean completions of unresolved predicates in the validated expression, and skips remaining predicates only if every completion gives the same expression value. The trace records skipped predicates and the run records the possible-outcome proof. This proves only a property of the generated expression; it does not establish that the expression includes every material exception or represents the question correctly.

Add `--exhaustive` to `run`, `compare`, or `dataset-run`, or select the exhaustive control in the browser, to evaluate every remote predicate. In local lexical retrieval, the initial predicates are evaluated in a batch; by default a second search is made only for an unknown predicate that can change the expression under some assignment of the other unknowns. `--exhaustive` instead searches again for every unknown predicate. Selection uses the initial batch, so searches selected together may become unnecessary after later results. Local shared-evidence evaluation remains an exhaustive batch. Dataset runs freeze the policy; older unfinished local shared-corpus runs cannot resume without the new policy version. These controls establish expression-level behavior, not planner correctness or retrieval recall. For a no-extra-search control, add `--no-extra-search` to `run`, `compare`, or `dataset-run`, or select the browser checkbox. In lexical mode this disables the fresh arm’s second predicate searches and the direct/frontier arms’ additional query and retrieval; initial and final evidence searches still occur. Compare otherwise identical frozen question sets with and without the flag. Dataset records freeze the setting, and legacy unfinished shared-corpus runs lacking it cannot resume safely.

New frozen question sets pin a fingerprint of each source's text hash and recorded applicability/provenance metadata, including scope, dates and collection membership. Launch and recovery reject a mismatch before proceeding, and comparison arms retain the fingerprint. A newly generated program carries its originating run's fingerprint into review and reuse. Older datasets without this fingerprint remain inspectable and scoreable but must be frozen again before launch or resume; older programs remain usable with their original text-only binding, so their metadata history is unverified. These hashes detect changes relative to a retained record; they are not signatures and do not establish that metadata is true or resist an actor who can rewrite all local records.

New collections also record each member's origin and metadata fingerprint; loading them rejects a conflicting member record. Older collections lacking those fields remain readable, but their member origins and other previously unpinned metadata are unverified. Recreate such a collection before starting a new comparison, freezing a question set, or resuming a dataset that uses it. Existing saved results remain inspectable.

For a saved run using an older collection, `verify-run` reports unpinned member metadata separately even when the collection text and its own metadata fingerprint match. Exact citation checks remain separate from that provenance status.

Dataset recovery and scoring also reject recorded fresh-arm evaluator, threshold, or execution-policy values that conflict with the frozen configuration, and conflicting recorded direct/frontier execution policies. Missing fields in older or early-failed records remain unverified. Historic direct/frontier evaluator labels are not checked because those arms do not use the separate evaluator.

A one-case live shared-corpus integration smoke is available in [JSON](examples/shared_corpus_live_smoke.json) and [Markdown](examples/shared_corpus_live_smoke.md). Its reviewer was the developer, not independent, and the sample supports no benchmark claim.

A second run of that same development case enabled extra searches: [JSON](examples/shared_corpus_extra_search_smoke.json), [Markdown](examples/shared_corpus_extra_search_smoke.md). The direct arm failed citation validation after two calls; the fresh and frontier arms decided. These are single, non-independent development observations, not a controlled estimate of retrieval benefit. Failed arms retain any provider-reported charges separately as observed partial cost; their complete total remains unknown.

New run records retain raw provider response text under `model_responses`, labeled by stage. These responses are untrusted, may repeat sensitive source material, and are stored locally with the run; older records do not have them. For direct and frontier answers only, a nonliteral citation can be repaired when its only differences are whitespace and it uniquely matches an original source passage that was actually supplied to the model. The result stores the exact source text and records the original quote and adjustment; ambiguous, absent, or unexposed passages still fail validation. This verifies the span, not whether it supports the answer.

New comparison configurations also freeze hashes of the runtime files used for execution. Resume rejects changed or missing runtime fingerprints instead of mixing behavior across cases. Previously completed reports remain readable; unfinished runs created before runtime fingerprinting cannot safely resume and need a new dataset run. These file hashes do not freeze external model provider behavior, installed dependencies, or hardware.

The browser dataset runner saves a run, starts work in the background, and promptly returns its ID, then polls case progress. Browser resume also starts a tracked background worker and polls progress; the server rejects a second tracked worker for the same run, and the dataset's filesystem lock still applies across processes. The worker lives in the local server process, not a durable job service: after server shutdown or a lost connection, use **List saved runs** and inspect status before resuming. An in-flight case without a saved comparison remains uncertain and will not be retried automatically. CLI `dataset-run` and `dataset-resume` remain synchronous.

Scoring is unavailable while a dataset run is active or incomplete. Before scoring a journaled run, the app checks the saved case receipts, comparison configuration, and arm bindings against the frozen dataset; reviews and case assessments are still required before unblinding.

After adjudication, the review page can download a comparison bundle. The CLI equivalent is `python3 -m workbench export-comparison COMPARISON_ID > comparison.json`. The bundle contains the pinned source and collection members, raw saved arm runs, adjudication records, and the report. Dataset-wide review gates apply before export. Bundles can contain local source text, model responses, reviewer names, and notes; inspect and protect them before sharing. This is a single-comparison export, not an export of an entire dataset or a secure blinding boundary.

After all dataset cases are reviewed, download a dataset archive from the question-sets page, or run:

```sh
python3 -m workbench dataset-export DATASET_RUN_ID > dataset-archive.json
python3 -m workbench dataset-verify dataset-archive.json > verification.json
```

Verification reconstructs the saved records in a temporary directory and recalculates the score with the current local code, without making model calls. It returns a nonzero exit status if the recalculated score differs or recorded journal relationships are inconsistent. A matching score does not establish independent review, correctness, or authenticity; the archive is not signed. Archives include source text, model output and review details and should be protected accordingly. Old runtime versions may score differently, which will be reported as a mismatch rather than silently accepted.

New dataset archives use format v2 and include available comparison and per-call journal records for their saved cases. Older v1 archives remain readable. Verification reports journal relationships separately as consistent, incomplete, inconsistent, or not recorded, checking available receipt links, call metadata, and returned response text against the saved runs. It cannot prove authenticity or that every provider call was recorded. These records may contain model responses, and older experiments can legitimately have no journal records.

To try offline verification without making model calls, run `python3 -m workbench dataset-verify examples/shared_corpus_reviewed_archive.json`. This archive contains a one-case live shared-corpus development smoke using public Python documentation and developer judgments, not independent evaluation. The provider did not report web-search counts for its calls; the current report marks those counts incomplete.

On the question-sets page, enter a saved dataset run ID and choose **Show review links** to open each completed case directly in the blinded review page. A saved judgment is marked on return; arm identities remain hidden until the report gates pass.

Remote answer checks can cite several separate exact source passages. Each passage must map uniquely to one pinned source; a joined or fabricated span is rejected. Multiple matching citations are still a model assessment, not proof that the answer follows. Intervention reports show recorded execution-setting differences and missing metadata so that a change in evaluator or retrieval mode is visible; matching recorded settings alone do not establish causal comparability.

If the first answer-check response is invalid, its single repair attempt receives exact predicate quotations already mapped to the source as candidate passages. These are untrusted hints, not proof of support; the repair can still defer, and every returned quotation must pass the same source validation. This may influence the repair model's assessment.

When a remote predicate response fails parsing, citation validation, or the provider call, the run remains a technical failure and its trace now identifies the predicate and error. Raw model output, when received, is retained separately; it is not treated as evidence.

A current clean-copy Python 3.12.16 check passed 103 offline tests and the fixture demo. In that isolated copy, Safari saved a synthetic source, ran a fresh OpenRouter decision, opened an exact source passage, and reopened the saved run. The synthetic record is [clean_copy_fresh_live.json](examples/clean_copy_fresh_live.json); it is integration evidence, not an independent correctness assessment.

The question-sets page can initialize a five-question **development** set from the hash-pinned Python 3.12.10 keyword and token documentation, without making model calls. CLI: `python3 -m workbench starter-development`. The output gives the frozen dataset ID and a minimum 75-call budget for a full three-arm run; this is a call ceiling, not a dollar cap. The developer-authored references are in [development_references.json](starter_corpus/development_references.json) and are not included in frozen model inputs. These cases and sources are development material, not an independently adjudicated pilot or holdout. A single fresh OpenRouter development run on the soft-keyword list question failed citation validation; see PROGRESS.md before drawing conclusions.

A remote predicate response that fails JSON or citation validation may receive one bounded repair attempt per run. The original and repair outputs and both call records are retained. A repaired response cannot establish a false predicate: it must return a valid positive, unknown, or conflict, and any quoted passage is still checked. A further invalid response remains a technical failure. This is a model-assisted formatting and reevaluation step, not a proof of relevance or protection against all unsupported conclusions. Dataset budgets reserve up to 15 provider calls per case; this is not a dollar cap.

Direct and frontier supplied-evidence answers also receive at most one model-assisted repair when their answer or citations fail validation. The repair can revise the answer or defer; it is checked against the same source and, for lexical runs, the same exposed passages. Both responses and calls are recorded. A second invalid response remains a failure. Each comparison arm has its own repair allowance, included in the 15-call per-case reserve; a repaired quote still requires human assessment for relevance and support.

The remote final answer check may likewise make one repair call if its JSON, verdict, or supporting quotations are invalid. A valid uncertain or contradicted verdict is not retried. If the repaired check is still invalid, the decision defers. The [live replay diagnostic](examples/live_answer_check_repair_replay.json) shows a case where the model repeated an inexact quotation and the result remained deferred; the initial responses were replayed and only the repair was a new live call.

The [live repair diagnostic](examples/live_direct_repair_replay.json) replays a previously recorded failed response and makes one new OpenRouter repair call. It is a development integration check, not an independent evaluation or a fully live two-call run.

For remote negative predicate results, the runtime applies a conservative lexical prerequisite: the cited passage must contain every non-generic term extracted from the predicate question. For certain recognized numerical thresholds, it does not require the threshold to be repeated in the quote, but does require another numeric occurrence and the remaining question terms. A missing prerequisite downgrades the usable outcome to unknown while retaining the model's proposal. Paraphrases, inflections and other valid comparisons may still defer. The numerical check does not perform arithmetic or verify that a number is the relevant measurement, and term overlap does not prove that a passage applies to the correct entity. Model outputs still require review.

The remote predicate guard also downgrades true or false proposals citing certain explicit descriptions of missing information, such as “records do not state,” to unknown. This is a limited phrase check: it can miss paraphrases and can defer valid questions about what a record does or does not say, or quotes containing other decisive evidence. It is not semantic verification.
