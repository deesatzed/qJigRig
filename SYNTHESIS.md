# Synthesis and choice of approach

## Product value

An agent currently either receives a broad document bundle or performs ad hoc searches while reasoning. qJig should make evidence needs explicit, retrieve source-appropriate slices for each need, expose unresolved facts and contradictions, and reuse the source catalog across roles. The intended gain is better-supported work per unit of total inference and retrieval effort. This is a hypothesis to test.

## Three approaches considered

| Approach | Advantage | Cost/risk | Recommendation |
|---|---|---|---|
| Add JIG as a service behind QUIXER | Quick boundary experiment; preserves working apps | Two stores, incompatible hashes and dates, nested budgets and duplicate prompts | Useful temporary bridge only |
| New shared core with adapters, then selective extraction | One source/trace contract, small pure tests, controlled migration | More initial contract work; current UI is not immediately combined | Recommended |
| Merge files and UIs into one application | Appears fast initially | `workbench/core.py` mixes storage/config/models/reasoning; QUIXER has research-specific envelopes; hard to localize regressions | Reject |

## Borrow, adapt, defer

From QUIXER, adapt source/section/revision storage, heading and paragraph indexes, many-to-many topic links, versioned role scores, BM25 retrieval, bounded packets and explicit recovery. Do not inherit workstation path-based identity or the 100-candidate experimental snapshot limit as product architecture. Generated indexes remain proposed navigation aids.

From JIG, adapt typed evidence requirements, true/false/unknown/conflict interpretation, bounded reachable-outcome logic, predicate relevance, pinned runs, controlled interventions, program bindings and comparison journals. Do not copy the 600+ line core wholesale, enforce identical dates on every collection member, or equate model agreement/exact quotes with verified support. A local judge's full-source context does not become a localized citation.

From the private-KB pilot, take keyed retrieval by entity/route/date and the explicit exception tests. Its 18-case authored fixture is a diagnostic control; never use its gold labels as model inputs or call the reference scheduler a fresh planner.

Keep the source web UIs as workflow references. Build a new thin UI after the CLI trace works. HITMCockpit is an optional future consumer adapter; its prototype sample agents are not the new runtime or a demonstrated swarm.

## Why the combination could add value

QUIXER can make JIG's evidence acquisition reusable across documents, revisions and agent roles. JIG can turn QUIXER's broad relevance ranking into question-specific acquisition that knows which unresolved fact could still change an answer. The additional decomposition and judging calls can also cost more or miss conditions, so the full combination must beat a competent direct-retrieval baseline on supported task outcomes, evidence quality or total resource use before complexity is justified.

## First demonstration

Use a synthetic software release packet with two policy versions, test-result evidence, an entity-specific exception and a distractor. Show one decided case, one missing-exception deferral, and a controlled source revision changing the appropriate result. Two role clients must see the same evidence identity. This is a deterministic proof of mechanics; fresh planning and real agents are later gates.
