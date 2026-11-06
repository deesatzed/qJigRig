# QUIX Knowledge — experimental prototype

An early local SQLite catalog for exploring evidence-linked retrieval by software agents. This is a research prototype, not a validated swarm knowledge service.

## Try it

From this checkout, set `PYTHONPATH=src`, then run:

```sh
python -m quix_knowledge --db /tmp/quix-example.db ingest docs/plans/2026-10-29-shared-knowledge-design.md
python -m quix_knowledge --db /tmp/quix-example.db search 'role retrieval'
python -m pytest tests/ -q
```

Markdown headings become line-anchored sections; unheaded text receives a generated fallback section. PDF ingestion requires the optional `pdf` dependency (`pip install -e '.[pdf]'`). Embedded PDF bookmarks define page-granularity sections; without bookmarks, each page becomes a generated fallback section. Pages with no extractable text are reported, and OCR is not performed. Source revisions are retained. Python APIs can add findings, evidence links, topic assignments and role annotations. Search includes current sections and proposed/current agent records, labels unsupported claims, and can apply topic and role adjustments. Decision providers can be passed to the Python search API; returned judgments are recorded and bounded adjustments are experimental. Missing or invalid judgments do not remove results.

This checkout has a local, ignored pilot catalog at `.local/pilot-catalog.db` if it has been created on this machine; it is not part of the repository. For example, from the worktree run `PYTHONPATH=src python -m quix_knowledge --db .local/pilot-catalog.db search 'retrieval role relevance' --variant topic --include-proposed`. Its proposed topics and passages are unreviewed. Run `PYTHONPATH=src python -m quix_knowledge --db .local/pilot-catalog.db refresh` after source files change; refresh invalidates affected annotations and does not automatically reindex them.

The `index` command creates provisional topic links from existing headings. For unheaded fallback sections and sections containing multiple paragraphs or long passages, it also proposes paragraph-level entries with extractive titles, exact offsets into the source section and an explicit provisional status. An explicit `unsuitable` structure judgment also triggers finer proposals; the original section remains available. These are candidate navigation aids, not verified semantic headings. Optionally it assesses structure and a bounded number of topic candidates with a decision model; source text remains searchable when a model is uncertain or unavailable. Model-assessed links remain proposals. The result's `decision_calls` reports actual attempted calls. For example:

```sh
python -m quix_knowledge --db /tmp/quix-example.db index docs/plans/2026-10-29-shared-knowledge-design.md --env-file /Volumes/WS4TB/QUIX/.env --model-slot 2 --max-decisions 2
```

Inspect generated candidates with `list-index` and record an explicit named review with `review-index ENTRY_ID accepted --reviewer NAME` (or `rejected`). Provisional entries can be included experimentally in topic, decision or role searches with `--include-proposed`; accepted entries are available to those variants by default. Source changes mark dependent entries stale.

Heading and agent-record topic links can be inspected with `list-topics` and reviewed with `review-topic LINK_ID accepted --reviewer NAME`. `assess-record-topic RECORD_ID TOPIC` accepts the same explicit OpenRouter or JevEdge0 provider settings as `assess-role`; it proposes a topic for the record, without endorsing the record's claim. Stale evidence prevents that assessment. Review names are recorded as supplied; the catalog does not establish reviewer identity or independence.

`map-topics TOPICS.json --max-decisions N` assesses a caller-supplied JSON array of topic names across current sections and agent records, plus generated spans when `--include-proposed` is supplied. Explicit OpenRouter or JevEdge0 provider settings are required. The cap bounds attempted model calls; the output reports remaining pairs, existing links, stale records, receipts, timing and reported usage. A topic assigned to a generated span remains scoped to that span rather than being attributed to its whole parent. Model outputs create proposed or rejected links; named review is needed to accept proposals. Topic annotations retain their status in search results and context packets. The mapping loop does not automatically retry existing unknown proposals.

Agents can submit local proposals with `add-record ID finding --body-file FILE --producer NAME`, optionally supplying `--evidence SECTION_ID` and `--supersedes OLD_ID`. `review-record ID accepted --reviewer NAME` makes a proposal current; rejecting a replacement leaves the old record current. A replacement retires the old record only when accepted, and stale supporting evidence prevents acceptance. `list-records` shows reviews. An accepted record with no evidence remains marked unsupported; a test-result output reference remains unverified until an external process checks it. Review names are self-reported.

Run `python -m quix_knowledge --db /tmp/quix-example.db refresh` to check known source files, re-ingest changed files, and invalidate missing or unreadable sources. The JSON report identifies sources that need reindexing; refresh does not make model calls or regenerate topic proposals. This is an explicit point-in-time check, not a file watcher or a guarantee that a file cannot change immediately afterward. Without it, `current` means current in the catalog, not verified against the filesystem.

The optional search `--context-chars` bounds returned body text by characters. Alternatively, install the `tokens` extra and use `--context-tokens N --tokenizer cl100k_base` to bound each returned body's token count with the named `tiktoken` encoding. The sum is for body text only: titles, metadata, message framing and model-input tokens are excluded, and a named encoding may not match the agent's actual tokenizer. Agent findings report `evidence_status` as current, stale or unsupported; linked evidence does not prove the finding is true.

For a stricter agent handoff, `context 'review retry behavior' --role reviewer --role-version 1 --budget 400 --tokenizer cl100k_base` emits a canonical JSON packet. Its token budget covers the task, role, catalog fingerprint, titles, anchors, metadata and included body text. The packet records truncated bodies and the count of selected results omitted to fit; the search result limit may have excluded further candidates before packet assembly. The consumer must reserve additional space for its chat or tool-message wrapper and use an encoding appropriate to its actual model. The `experiment` command can compare variants using this packet budget via `--packet-tokens N --tokenizer NAME`.

To request a role-usefulness estimate for a section ID, generated-index ID or agent-record ID returned by search, use `assess-role ID --role reviewer --role-version 1 --role-purpose 'Review implementation evidence' --env-file /Volumes/WS4TB/QUIX/.env --model-slot 2`. It records the source revision or record, role definition and model receipt; the score is a proposed estimate, not calibrated utility. A generated topic's score takes precedence over its parent section's score, and the returned `role_score_scope` identifies which was used. An error records an unknown result and does not invent a score. Increment the role version when its purpose changes.

## Current limitations

OpenRouter can be used explicitly for a decision search, using a configured model slot and `.env` file. This sends candidate text to OpenRouter and incurs API charges:

```sh
python -m quix_knowledge --db /tmp/quix-example.db search 'role retrieval' --variant decision --env-file /Volumes/WS4TB/QUIX/.env --model-slot 2
```

Returned model probabilities are recorded but remain provisional: the adapter does not apply unvalidated thresholds. Model failures result in unknown judgments and preserve the original candidates.

An independently running JevEdge0 workbench can be selected with `--jev-url http://127.0.0.1:8090 --stability-trials 2` instead of the OpenRouter settings. The adapter accepts only loopback HTTP and preserves conditional option scores and permutation-stability information; those scores are not calibrated accuracy. The workbench and model weights are separate prerequisites, and have not been tested live in this checkout.

There is no OCR, production orchestration integration, persistent vector index, complete request token budget, independently labeled benchmark, model calibration, concurrency control or production readiness claim. PDF bookmarks can be incomplete and same-page entries are combined; page anchors do not identify exact passage boundaries. The current evaluator is not the planned complete run-manifest framework. When a decision is uncertain or fails, retrieval falls back to the ungated baseline and identifies the fallback. Structure judgments are recorded rather than used to delete source content, and topic links remain proposed pending acceptance. Do not interpret synthetic tests as a quality evaluation. See [progress](PROGRESS.md), [evaluation](docs/evaluation.md), and the [plan](docs/plans/2026-10-29-shared-knowledge-implementation.md).

When exact lexical search yields no results, the retriever also tries a conservative singular/plural normalization and labels that fallback. This is not semantic search and may still miss relevant evidence.

The default ranker is word overlap. `--ranking bm25` selects a local BM25 lexical ranker for `search`, `context` and all four `experiment` variants. Its corpus statistics use original sections and agent records rather than counting generated paragraph views as separate source documents. Its usefulness relative to the default remains unvalidated.

`--ranking hybrid --jevedge-root PATH --embedding-model-path PATH` explicitly loads JevEdge0's local MLX `BertEmbedder` from a trusted source checkout and an existing local checkpoint. It combines BM25 and cosine rankings with reciprocal rank fusion; no weights are downloaded. It hashes the encoder code, weights, tokenizer and configuration for provenance. Inputs are bounded by characters and may be truncated again by the encoder's tokenizer; the result includes truncation metadata. An embedding failure falls back to BM25 and is labeled, or reports an error if no lexical result exists. Model loading, repeated embeddings and GPU costs have not been optimized. This requires the JevEdge0 runtime dependencies and an accessible Metal device.

The isolated [model-cascade research experiment](experiments/cascade/README.md) tests Reflex decisions, optional Cohere reranking, Hy4 escalation, Clairic extraction and Cohere embeddings. Model roles and evidence limits are documented in [research model selection](docs/model-cascade-selection.md); the cascade is not a live swarm connection.
