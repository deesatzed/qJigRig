# Research model cascade selection

## 2026-11-04: selected research model roles

The user selected [`tencent/hy4`](https://openrouter.ai/tencent/hy4) as the **preferred escalation model** for the next research integration, informed by other reviews the user has seen. Those reviews have not been supplied or independently assessed here. Hy4 is a text-generation and tool-capable model, distinct from the typed decision endpoint. The current code does not yet automatically route to Hy4; the selection is a design decision for implementation and evaluation, not a claim of deployment or measured superiority.

The intended research cascade is:

1. Preserve source revisions, original sections and explicit unsupported or stale evidence labels.
2. Use BM25 and, when adapters are tested, optional Cohere Embed 5 Pro and Rerank 5 Pro to retrieve and order source candidates. Role scores remain provisional ranking metadata, never proof or a reason to discard evidence.
3. Evaluate Morph Reflex for bounded typed decisions and switch navigation. Timeout, unstable results, absent evidence and unsupported output stay explicit, with deterministic baseline fallback. Do not infer operational thresholds from model scores alone.
4. Escalate a bounded, source-linked task to **Hy4** when a stronger generative agent is needed: for example, to synthesize conflicting evidence, make a source-backed plan, or review unresolved ambiguity. Supply the agent's role and purpose, task, evidence IDs/revisions/anchors, explicit uncertainty and a request/token budget. Record configured and resolved model, prompt version, sources, usage, cost, latency and failures. Output is a proposal with citations, not verified truth or authority to mutate the catalog.
5. Use Clairic's separate extraction API as an optional ingestion candidate for typed metadata. Preserve nulls and the source span; a guess or confidence is not a verified field.

The 2026-11-04 synthetic Hy4 smoke returned a valid short JSON answer with a matching source excerpt. This is a contract observation from one simple request, not a quality comparison. A bounded role-aware task pilot with frozen inputs should compare Hy4 with the existing planner and separate AI reviewer, report unsupported citations, uncertainty, latency and actual cost, and preserve all failures. Reusing the same model to generate and review its own output is not independent review. Any live swarm or MindStore integration remains outside the approved isolated slice.
