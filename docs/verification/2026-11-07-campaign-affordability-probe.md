# Campaign affordability probe

This is a read-only feasibility probe of the **unfrozen**, 16-case draft. It made no model calls and does not authorize dispatch. Current OpenRouter endpoint metadata and the key/account snapshot are time-sensitive provider assertions. The selected allocation must still be designed, fully bound, checked at dispatch and reserved along with smoke, acceptance, escalation and retry work.

The draft produces 105 assignments and, with the separately budgeted semantic reviewer, 1,302 reserved physical-call slots: 63 direct initial, 42 direct final, 42 planner, 1,008 positive/negative judge, 42 plan review and 105 semantic review. The account read showed approximately $6.220619885 in credit and $18 remaining on the key; BYOK spend assurance was unknown.

An all-listed-route catalog read returned 51 DeepSeek planner routes and one Hy4 route. The current conservative pricing calculation takes the maximum listed route rate and adds the configured routing-price ceiling; the result is a reservation, not a prediction of actual spend. Using DeepSeek for direct and planner and Hy4 for all review/judge stages, and setting the per-token routing ceilings to those all-route maxima, gave these **illustrative, unvalidated** allocations:

| Input and output tokens per slot | Total reserved tokens | Largest request reservation | Reserved cost |
|---|---:|---:|---:|
| 5,000 input / 128 output | 6,676,656 | 138,456 | $14.539292880 |
| 5,200 input / 256 output | 7,103,712 | 147,312 | $16.177596960 |
| 5,500 input / 512 output | 7,827,624 | 162,324 | $19.185434520 |

All three examples exceed the observed account credit before reserving other required work. The third also exceeds the approved 160,000-token request ceiling. These examples do **not** prove that every possible eligible route or allocation is unaffordable: a separately justified and enforced route-specific pricing bound could differ. Nor do they establish that 128, 256 or 512 output tokens are sufficient for the selected models.

The approved input estimate is `4096 + 2 × UTF-8 prompt bytes`. Inspection of the retained 105-assignment synthetic campaign found maximum estimates of 7,712 for direct, 8,810 for planner, 5,606 for judge, 9,498 for plan review and 6,472 for semantic review. Applying those observed maxima to every corresponding reserved slot with 512 output tokens gave 8,575,728 reserved tokens, 173,148 maximum per request and $21.629769000 reserved under the same all-route pricing. This exceeds both token ceilings and the observed credit. These are maxima of synthetic prompts, not bounds on future model-generated prompts; using them cannot authorize a real run.

Next, determine whether an explicitly pinned route and current verified pricing can provide a lower complete monetary bound, and design prompt/output reservations that cover the actual planned work without exceeding the request and goal ceilings. Preserve all 105 assignments, report the full denominator, and retain the unknown BYOK/plugin billing and prior-spend reconciliation gates. Do not infer a safe run from these estimates or silently lower the denominator.

## Provider-route candidate probe

OpenRouter's [routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection) describes provider allowlists and fallbacks, and its [routing explanation](https://openrouter.ai/blog/insights/model-routing/) says a base provider slug can cover multiple endpoint variants. The new `candidate_provider_pricing` function uses fresh catalog tags to include every listed matching variant, refuses missing/ambiguous tags and unknown charges, and labels its output as a candidate only. It does not put a provider allowlist in a request, establish provider enforcement or authorize dispatch.

A later catalog observation had two DeepSeek routes tagged under `relace` and one Hy4 route under `tencent`. Repeating the same illustrative 105-assignment calculations with those candidate groups produced reservations of $11.095494480, $12.281744160 and $14.447800920 for 5,000/128, 5,200/256 and 5,500/512 input/output tokens per slot respectively. Even these candidate estimates exceed the previously observed approximately $6.22 credit, before smoke or acceptance work; the stated input/output caps are still not established as adequate. These are not selected or frozen providers, and the example does not prove that all possible routes, revised safe accounting methods or future prices are infeasible. The requested model, complete task denominator and budget constraints remain unchanged.
