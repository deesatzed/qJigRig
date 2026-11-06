# Prospective retrieval comparison

`manifest.json` freezes 16 unlabeled tasks, eight development and eight held out, across three project documents and explicitly synthetic fixtures. The sources share documents across splits and the project has already been explored; the split is not independent by construction. The fixtures include invented conflicting, stale and unsupported agent findings. They are not observations of a live swarm.

The common candidate scope is current sections and agent records; generated-index passages are excluded. All variants use a 2,000-token `cl100k_base` serialized context-packet budget, but switch consumes additional model input and calls, so the complete model budgets are not matched. Exact-ID matches do not establish that a truncated packet contains the answer. The prepared catalog has no role annotations, so this study cannot measure role-score benefit.

With Python dependencies, Node and the switch experiment dependencies installed, run from the repository root:

```sh
PYTHONPATH=src python experiments/retrieval/prepare.py .local/my-study
PYTHONPATH=src python experiments/retrieval/run.py .local/my-study .local/my-fixture-run --mode fixture
PYTHONPATH=src python experiments/retrieval/run.py .local/my-study .local/my-live-run --mode openrouter --env-file /Volumes/WS4TB/QUIX/.env --model-slot 2
```

Each output directory must be new. Runs use a catalog copy and leave the review packet and prepared catalog intact. Fixture mode exercises the wiring with a deterministic fake selector, not a model. Live mode incurs OpenRouter calls; results, receipts and source text remain in the ignored output directory. Missing usage is unknown. The runner checks source revisions, frozen tasks and candidate material before executing.

For relevance evaluation, an independent reviewer should inspect `blind-review-packet.json` and its source candidates without seeing rankings, fill `reviewer`, and set each task's `reviewed`, `labels`, and, when the corpus cannot answer a task, `missing_reason`. A null label means unreviewed; an empty list with a reason means reviewed and unanswerable. Keep the packet with its prepared catalog. Run again into a new output directory with `--reviewed PATH`. The reviewer identity and independence are self-reported, not authenticated; labels must be exhaustive for exact-ID precision and recall to be meaningful. Do not select thresholds using held-out tasks or retrofit role annotations after preparing the packet: a new catalog requires a new packet and review.

The local terminal guide can help a person inspect sources and save a separate draft without editing JSON. From the repository root, for example:

```sh
PYTHONPATH=src python experiments/guided_review.py .local/retrieval-study-isolated-v1/blind-review-packet.json .local/retrieval-study-isolated-v1/review-draft.json --reviewer "Reviewer name"
```

Use `list` or `search WORD` to find candidates, `show N` to read one, `mark N,N` for all relevant source units, or `none REASON` only when the inspected corpus cannot answer the task. `skip` leaves the item unlabeled; `quit` saves only completed items. Repeat the command with the same reviewer and draft path to resume. Each saved task records the session's local date, or the reviewer-supplied `--date YYYY-MM-DD`; this date is not independently verified. The guide never opens a condition key and never supplies labels. Give the completed draft to `run.py --reviewed` with its matching prepared study and a new output directory; a fixture run tests the workflow but is not a model evaluation.

To prepare a **separate** prospective role-scored packet, add `--role-scores --role-call-limit 56 --env-file /Volumes/WS4TB/QUIX/.env --model-slot 2` to the preparation command and choose a new directory. Before creating the packet, this protocol scores every current original section and every current/proposed nonstale agent record for both manifest roles, in sorted order, independent of task labels. It refuses to start model calls if the complete set exceeds the cap. The existing corpus currently has 28 eligible targets, so the two roles require 56 calls; changed corpus size may require revisiting the cap. Model errors are unknown, not negative scores; estimates are provisional, uncalibrated metadata. The preparation records the model names, unknowns and cost only when all call costs are reported. The prior unscored packet and catalog remain unchanged. Compare variants only after obtaining review of the new packet, and separately report the cost of creating the role annotations.

Add `--isolated-sources` when preparing a new study to copy each pinned, hash-checked source into that study's `source-snapshot` directory before indexing. Preparation records each original relative path, copy path and content hash; lifecycle test content is created separately inside the study. Subsequent retrieval checks the copied source revisions. Changing the original workspace does not update the copy, and changing a copy invalidates it. IDs and fingerprints are path-dependent, so a copied study requires its own review packet and must not reuse labels from another catalog.
