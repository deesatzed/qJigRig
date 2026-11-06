# Test strategy

Unit tests cover one invariant or failure at a time using a few tiny source strings and at most six predicate IDs. Use tables for distinct truth states/AST operators. Deterministically enumerate the small state space instead of using random samples as proof. Test actual observable results, not internal call order unless order controls budget or correctness.

## Verification layers

1. Pure contracts: serialization, types, IDs, exact hashes/spans, source applicability, logical states, repeated refs, possible-outcome and relevance enumeration. No IO or model fakes needed.
2. Small SQLite/blob integrations: two source revisions, one generated index, one role and one exception. Verify preservation, updates, rollback and shared read identity.
3. Acquisition tests: explicit tiny candidate/evaluator functions where provider behavior is the input; verify exclusions, source changes, obligations, bounds and stop witnesses. A deterministic provider only proves orchestration.
4. Opt-in real adapters: public/synthetic source, exact configured models, redacted request/receipt records and all usage. No mock substitution for claimed real inference; failed HTTP 200 JSON remains a failure. Current authorization/config are recorded per run.
5. CLI/process/UI integrations: temp paths, actual subprocess, then browser interactions for import/ask/inspect/intervene/export. HTTP response alone does not prove the workflow or accessibility.
6. Outcome comparison: grouped cases by source family/revision/near duplicate; references outside index/provider input. Direct, retrieval-only, decomposition-only, combined and escalation arms; preserve all failures and unknown reviews.

## Mandatory small counterexamples

- Same CRLF bytes enter both legacy adapters and resolve to the same canonical span while preserving different legacy hashes.
- Missing heading -> extractive proposed span; broad heading -> finer span; unrelated title does not establish relevance.
- Ordinary=false, exception unknown under OR -> deferred. Known prohibition under AND can make a separate fact immaterial.
- Both support sides -> conflict. A semantic judge's false support choice does not prove contradiction.
- Missing entity/date/authority -> unknown applicability. A review dated after request cannot justify a historical-as-known answer.
- Same numeric fact under two rule versions yields different exact outcomes. Do not choose policy by most recent file modification time.
- Missing top-ranked file -> alternate correct-subject span plus exclusion; missing indispensable file -> defer even if other text exists.
- Source changes between retrieval and finalization -> pinned-snapshot disclosure or one bounded current-required restart, never mixed revisions.
- Wrong-entity quote, omitted negation and a forged instruction do not get accepted merely because a quote exists.
- Irrelevant wording/source additions leave exact outcome and decisive evidence stable; changing decisive facts changes outcome or uncertainty.
- Low role score never excludes mandatory exception; role version change invalidates estimate without erasing evidence.
- No hit, budget cap, malformed provider response, timeout, unavailable provider, contradiction and conflict remain distinguishable.
- Crash at intent/receipt boundaries yields no silent duplicate paid call. Missing cost remains unknown.
- One agent's finding remains AgentClaim; another agent cannot treat it as source fact without evaluating evidence.
- Gold labels and arm mappings never enter source index or provider envelopes.

## Promotion gates

Each task must show its red -> green receipt. Each phase must pass focused regressions and the full new runtime suite. UI/real adapters/performance/semantic quality are separately open until directly exercised. Initial evaluation can use a separate AI reviewer per prior user preference; label it exploratory. Independently authored references and adjudication are a different evidence level, not an automatic blocker to implementing the app.

Do not optimize latency until the deterministic vertical slice passes. Then compare total work: preparation at stated reuse volume, all physical calls, complete prompt tokens, retrieval time, local startup, retries, escalation, failed runs and review cost. No claim of 80% inference savings from the private pilot's 79.7% evidence-byte reduction.
