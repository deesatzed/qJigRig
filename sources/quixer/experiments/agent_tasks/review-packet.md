# Independent agent-output review

Generate `outcome-review.json` and its separate `outcome-key.json` using `prepare_review.py`. Give the reviewer only the review packet and the pinned source corpus; withhold the key, retrieval reports and prior outputs. The packet shuffles completed responses and does not deliberately disclose the retrieval condition, although a response or its citations may reveal clues. Failed or missing runs are counted in the separate key and must remain in the final analysis.

For each output, inspect the task, response and supplied source candidates. Fill the `review` object using `review-schema.json`. Assess correctness, support for cited claims, missing material evidence, and whether the requested task was completed. Use `unknown` when evidence is insufficient and add a brief explanation with relevant source IDs. Record your identity and review date in the packet. The recorded identity is self-reported; this software does not establish independence. Do not interpret an agent's own claims or a model-authored review as independent verification.

For a guided local review, from the repository root run:

```sh
PYTHONPATH=src python experiments/guided_review.py .local/agent-isolated-16-v2/outcome-review.json .local/agent-isolated-16-v2/review-draft.json --reviewer "Reviewer name"
```

Use `list`, `search WORD` and `show N` to inspect sources; `review` opens the rubric. Enter supporting source numbers when prompted, or leave them blank. If an answer cites an unknown source ID, describe it in the explanation and judge its support; the supporting-source field accepts only IDs in the packet. `skip` leaves an output unreviewed and `quit` preserves completed reviews. Repeat the same command to resume. The tool does not read the condition key or generate answers, and the original packet remains unchanged. The current packet contains 57 completed outputs; seven missing runs are recorded in the separate key.

The source list includes explicitly synthetic records. A source-linked agent finding is still a claim, not proof that its text is correct; check the cited source. Exact section IDs can identify a document, but truncated context may omit the evidence the agent needed. Compare conditions only after the review is complete and the key is released, including missing runs and small-sample limitations.

After review, run `PYTHONPATH=src python experiments/agent_tasks/compile_review.py PACKET.json KEY.json OUTPUT.json`. The compiler checks the original blinded tasks, source candidates and output text against the local key, validates each review and source ID, and retains failed or absent runs. It does not authenticate the reviewer or prove independence, the truth of a review, the correctness of the key, or the scientific adequacy of the task set.

To produce a per-task paired report after the reviewer has finished the isolated 16-task packet, run:

```sh
PYTHONPATH=src python experiments/agent_tasks/analyze_review.py \
  .local/agent-isolated-16-v2/review-draft.json \
  .local/agent-isolated-16-v2/outcome-key.json \
  .local/agent-isolated-16-v2 .local/retrieval-study-isolated-v1 \
  .local/agent-isolated-16-v2/paired-analysis.json
```

This verifies the task manifest, review contract, catalog and copied source revisions, retrieval evidence, and recorded input packets before unblinding. The output retains each condition's review, failure, latency and reported cost; unknown costs remain unknown. It separates planner, switch and role-indexing accounting, and does not declare a winner or calculate a confidence interval. The report contains local source paths and reviewer explanations, so it stays local unless deliberately sanitized. Verification is point-in-time; it does not independently re-extract PDF text, authenticate the reviewer, or verify agent-authored claims. If a source or recorded packet has changed, analysis stops rather than silently rebinding the review.
