# Build qJig

## Intended outcome

Build a local application that lets a software implementation or review agent ask a scoped, dated question, obtain source-linked evidence for its decisive subquestions, produce a traceable decision or explicit deferral, and share that evidence with other role-defined agents. Demonstrate whether this improves supported task completion or reduces work at comparable quality versus direct retrieval.

The central hypothesis is that better acquisition AND explicit reasoning can outperform either alone. It remains unproven. The initial family is source-grounded software release/readiness questions over a bounded, non-sensitive project corpus, with explicit project rules. A release answer is a proposal; this app does not deploy software.

## Smallest complete vertical slice

Import a small text corpus, index headings/fallback spans, submit a request with role/version, entity, scope and as-of date, use a small authored predicate graph, retrieve and validate source spans, evaluate exact facts, preserve an unknown exception, and show the outcome plus its trace. Removing indispensable evidence must cause a recorded deferral. A second role can retrieve the same immutable evidence without inheriting another agent's claims as facts.

The authored graph is a fixture control. Fresh model-generated decomposition is a subsequent milestone and must be labeled accordingly.

## Completion gates

1. Contracts specify byte/text hashes, normalization, character offsets, applicability metadata, role versions and trace schema; round-trip tests pass.
2. The deterministic fixture slice passes missing/changed source, conflicting evidence, temporal, wrong-entity, exception, irrelevant-change and budget regressions.
3. A fresh planner, evidence judge and direct model path return real, recorded outcomes under configured budgets. Invalid outputs, failures and uncertain in-flight calls stay visible. Hy4 escalation is separate from standalone success.
4. A CLI and local browser complete import -> ask -> inspect evidence/unknowns -> controlled intervention -> replay/export. A real UI walkthrough remains required beyond HTTP tests.
5. Two role-defined agent clients share one catalog using an append-only writer queue. Real provider-backed use is evidenced separately from deterministic client fixtures.
6. A comparison isolates direct retrieval, decomposed acquisition and the full combination on the same pinned cases with complete resource accounting. AI-reviewed exploratory labels may be used, as the user previously chose; they must remain labeled unvalidated. Independent reference/adjudication is required before claiming independent accuracy or non-inferiority.
7. Documentation, actual receipts and checkpoint commits agree. The plan's future tasks are never described as completed implementation.

## Scope and stopping points

Local Python/SQLite and a thin loopback browser first. No production deployment, broad web research, general-purpose swarm scheduler, graph database, automatic program activation or automatic role learning in the initial build. PDF source extraction is optional and its assurance must be explicit. The existing JIG folder and QUIXER checkpoint stay inspectable.
