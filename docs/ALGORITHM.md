# Proposed acquisition and decision algorithm

## Deterministic spine

1. Validate request and policy. Pin corpus, role definition, provider/model IDs, prompt/runtime versions and budgets. Refuse malformed inputs before external work; create request journal before any paid call.
2. Create or load a plan. The first slice uses authored fixture plans. The fresh slice obtains bounded JSON from the configured planner and records its untrusted origin. Validate IDs, AST refs, depth, exact operators, dependencies and cycles. A syntax-valid plan is not known complete.
3. Build evidence obligations for entity, scope, applicable policy versions, each predicate, contradictions and material exceptions. Explicitly missing inputs remain unknown. Use an exact authority/source scope only if declared by request/corpus policy; do not invent authority from titles.
4. For each acquisition round, determine unresolved predicates that can still change the expression under some completion. Keep exception and applicability obligations open until satisfied or explicitly unresolved. Unknown/conflict have no assumed Boolean value.
5. Choose the next material predicate deterministically: prerequisites first, then initial planner order, then predicate ID. This conservative ordering is the baseline. Later optional ordering models can propose permutations; reject missing/duplicate IDs, preserve obligations and fall back to this order. Do not tune an opaque cost/utility formula before evidence exists.
6. Retrieve candidates from the shared catalog using predicate evidence requirements plus task/entity/scope/date keys. Seek contradictory and exception evidence in separate channels. BM25/topic/role scores order candidates; role usefulness is a bounded tie-breaker within each applicable evidence channel. Never equate top-k exhaustion with absence of exceptions.
7. Verify source revision and exact spans, record excluded candidates and attempt bounded alternatives. Record applicability as match/no-match/unknown. Unknown applicability cannot support a definitive predicate. Truncation that can hide a material condition leaves an unresolved obligation; fetch a more suitable span within budget.
8. Evaluate whitelisted exact conditions with deterministic code (dates, IDs, numeric comparisons) only when the field binding is verified. Use a configured judge for semantic claims with the complete relevant packet. Parse typed results; unsupported support -> unknown. Separate support for positive and negative claims gives true/false/unknown/conflict; never infer a negative solely from a false support score.
9. Preserve every observation and receipt. Recompute reachable outcomes by enumerating the remaining Boolean assignments of unresolved refs (<=64 for six predicates, repeated refs share one value). Compute materiality by checking whether changing one unresolved ref can change the answer under any completion of the others.
10. Stop when the expression has one reachable outcome AND remaining material applicability/exception obligations are satisfied. Return a conditional plan outcome with evidence assurance and plan-origin caveat. A material conflict, missing decisive evidence, missing entity or unverified applicability causes deferral. A second acquisition round is allowed only for a material unresolved gap and only within policy; irrelevant unknowns may remain recorded as skipped.
11. Recheck required source bindings immediately before producing the result. In snapshot mode the run stays bound to the immutable revision; an origin update is reported separately. In current-required mode an origin update invalidates the candidate result; restart acquisition once under a new snapshot or defer. Never silently mix old and new revisions in one decision.
12. Optional Hy4 escalation requires a recorded reason and remaining call/token budget. Save the standalone outcome first and record escalation as a separate path. Hy4 output still needs source/answer validation. No budget/no usable evidence -> explicit deferral, not an invented result.
13. Export result, decision trace, unresolved needs, source IDs and actual resource ledger. Sharing evidence makes a separate AgentClaim record; it cannot change the authority of the original source.

## Pure functions to test before orchestration

```
combine_support(pos, neg):
    (supported, unknown) -> TRUE
    (unknown, supported) -> FALSE
    (unknown, unknown) -> UNKNOWN
    (supported, supported) -> CONFLICT

reachable(plan, observations):
    validate bounded plan
    map UNKNOWN/CONFLICT to unresolved Boolean variables, retain their reasons
    enumerate every consistent completion by unique predicate ID
    return distinct expression outcomes

is_material(predicate, plan, observations):
    for each completion of other unresolved predicates:
        if expression(predicate=False) != expression(predicate=True): return True
    return False
```

A tautology may be stable without evidence; that is only a property of the expression. It cannot attest to a real-world fact, justify a missing prerequisite or certify that the planner included all conditions. Test that the result renderer retains this limitation.

## Explicit operational bounds

Initial graph cap: six predicates/depth 12. Baseline at most two retrieval rounds per predicate (12 total) and one source-change restart. Exact search result/page/token limits live in a versioned BudgetPolicy and can differ by experiment arm only when disclosed. Offline policies set provider calls to zero. Before a live run, configure physical provider call and complete-input/output token caps, a local inference cap, timeout and any measurable spending limit. Do not treat a requested dollar limit as provider-enforced. Reserve room for required repair/final checks/escalation before starting; every attempted physical call counts, including unstable option-order checks and failed responses. Unknown cost never becomes zero.

Score calibration, learned acquisition order and automatic reviewed-program generalization are later experiments. The deterministic baseline remains available for every comparison.
