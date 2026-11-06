# Switch navigation prototype

This isolated experiment uses the published MIT-licensed `@osolmaz/switch` 0.1.1 package and its fake decider, with dependency integrity pinned in `pnpm-lock.yaml`. It was developed against the sibling switch checkout at `7c5b6b9bae55e9e7cda3efe310f585187eb7c717`; the registry artifact has not been independently proven byte-for-byte equivalent to that checkout. No switch checkout files are modified.

From this directory, with Node 22.18+ and pnpm:

```sh
pnpm install --frozen-lockfile --ignore-scripts
pnpm test
pnpm typecheck
pnpm smoke
pnpm live-smoke
```

`smoke` creates a temporary in-memory catalog from the two project design/plan documents and uses a deterministic fake decider. `live-smoke` uses OpenRouter settings from `/Volumes/WS4TB/QUIX/.env`, slot 2 by default. Set `QUIX_OPENROUTER_ENV` or `QUIX_MODEL_SLOT` to select an existing settings file or slot. Live calls cost money; the smoke caps the run at four logical decision calls and eight physical requests, with a 15-second timeout per request. Its output names a raw report in the ignored project `.local` directory. That report contains source content, local paths and model views; do not commit it. Exit 0 means the script completed, not that it found usable evidence: inspect `status`, `reason` and `decision_detail`.

`quix_knowledge.switch_snapshot.build_snapshot` exports a bounded, point-in-time catalog snapshot without writing the database. It checks source revisions before and after export, includes current source sections, accepted or explicitly proposed generated passages, and current/proposed agent records, with evidence links and proposal statuses. It fails rather than silently cutting a catalog over 100 candidates. Snapshot text and metadata are bounded; source body truncation is explicit. A caller must open the catalog read-only when read-only access is required and verify the current fingerprint before using a previously saved snapshot. A snapshot's fingerprint is not a signature or proof of origin; only use snapshots from a trusted exporter.

The domain offers topic, passage, broaden and stop choices. It does not let a model choose a command or arbitrary path. Topic results carry accepted/proposed/unverified status; role estimates are labeled uncalibrated and do not by themselves filter candidates. The project smoke uses the three highest lexical-overlap initial candidates and leaves all others available by broadening; this experimental selection was introduced after observing order instability and is not a preregistered quality comparison. Inspected source evidence is rechecked before use and before returning a result. UTF-8 text sections and generated spans are checked against the cited source text and revision. For PDF, only file revision is checked; extracted PDF text is not independently rederived by this prototype. An agent finding's referenced files are checked, but its claim remains `agent_claim_unverified`.

The model view is bounded in serialized JavaScript characters, with explicit truncation and omission counts. switch estimates provider tokens using characters; this is not a guarantee about the receiving model's tokenizer or the complete downstream prompt. Returned evidence may differ from the abbreviated view the model saw, so inspect `model_requests` and its `view_truncated` fields. The snapshot includes hard step, character and logical model-call caps; the bridge separately caps physical HTTP requests, including option-order trials. Missing provider usage remains unknown. No operational score threshold is selected.

The OpenRouter decider uses the [OpenRouter Decisions endpoint](https://openrouter.ai/openai/gpt-6-luna-decisions/providers) with typed choices. It validates answers and, in the live smoke, sends each choice set in two orders; disagreement, invalid output, timeout or unavailable service produces insufficient evidence. Reversing options detects one kind of instability only; agreement is not calibration or accuracy. The emitted switch trace records states, questions and answers, while `model_requests` records the model views and questions. `replayNavigation` repeats a trace without model calls and rechecks sources; replay traces are not authenticated and do not prove relevance or truth.

The first live project-document smokes produced no usable evidence: Joey, Liquid d1.1 and Perplexity Decider disagreed across option orders on the original prompt. With a reduced initial set, Joey took one stable broaden step before disagreeing on the next; Perplexity disagreed immediately and Liquid stopped without inspecting evidence. These are a few observed integration calls, not a provider comparison or proof of improvement. Full results and costs are recorded in `PROGRESS.md` and local raw reports.

A later five-task exploratory run produced one complete Joey navigation trace with one source-bound passage. Its exact saved trace was replayed without model calls and with the same final state. From the repository root, while the original local catalog, report and cited source revisions remain available, reproduce that replay with:

```sh
PYTHONPATH=src python experiments/switch-navigation/replay_saved.py \
  .local/agent-live-v1/catalog-copy.db .local/agent-live-v1/retrieval-report.json agent-timeout
```

The command opens the catalog read-only, reconstructs the snapshot from the report's task and limits, rechecks the catalog fingerprint and source revisions, and feeds the recorded trace to the local switch replay. It reports the outcome and a trace digest without printing source bodies. It does not use `.env` or call a model. A valid replay can still have `insufficient_evidence`; an unchanged trace does not establish that its selected passage is relevant or that the trace is authentic. A changed or missing source, catalog or incompatible trace makes replay fail. Since IDs and fingerprints include local paths, a fresh checkout or moved corpus does not automatically reproduce the original case.

New agent-study snapshots can set `choice_mode: "bounded-v1"`. This ranks candidates by deterministic task-word overlap, offers up to six passages per page with a source ID and short source snippet, offers up to two task-matching topics, and provides next/previous pages. It retains the complete candidate snapshot and does not discard low role scores. The model can still abstain or disagree on option order; the caller falls back to baseline when navigation is insufficient. The pilot with this mode still fell back on all four tasks. Snapshots without this setting retain the original behavior so old traces can be replayed. The new runner allows 20 navigation steps and calls, enough to page through the maximum 100 candidates and inspect one before stopping; that is an upper bound, not a guarantee that a model will choose to do so.
