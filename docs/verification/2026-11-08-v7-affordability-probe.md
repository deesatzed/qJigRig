# V7 campaign affordability probe

**Read-only feasibility check, not an experiment freeze or permission to dispatch.** No inference call was made. Observations are time-sensitive provider assertions; the full cost of BYOK, plugins and other account-specific charges remains unresolved.

At approximately 05:51 UTC on 2026-11-08, the configured key/account observations indicated $18 key limit remaining and $6.220619885 in account credit. The derived BYOK spend assurance was `unknown`. The public endpoint catalogs listed 51 DeepSeek Flash endpoints and one Hy4 endpoint. The candidate route filter included two `relace` variants for DeepSeek and one `tencent` variant for Hy4. Route enforcement and catalog completeness were not proven by this observation.

The current **unfrozen** draft declares 105 assignments. A provisional v7 allocation reserved two positive and two negative judge calls per fresh assignment plus both separate reviews: 567 slots, comprising 105 direct, 42 planner, 168 judge, 42 plan review, 105 semantic review and 105 outcome review. It retained every declared assignment and included unused possible direct followups and reviews. It did **not** reserve the separately required smoke, acceptance, escalation or retry work.

For an illustrative calculation, use the approved input estimator `4096 + 2 × UTF-8 prompt bytes`. Maximum estimates measured in the retained v7 stand-in campaign were 7,712 for direct, 8,810 for planner, 5,606 for judge, 9,498 for plan review, 6,472 for semantic review and 6,398 for outcome review. Apply each stage maximum to every corresponding held slot and assume 512 output tokens per slot. Set per-token routing ceilings to the current selected catalog maxima, rounded upward. Use the existing reservation formula that adds catalog cost and the routing ceiling; it is conservative arithmetic, not predicted or verified actual charges.

| Provisional allocation | Total reserved tokens | Largest request | Reserved cost |
|---|---:|---:|---:|
| All listed routes | 4,162,158 | 57,698 tokens / $0.1471 | $12.8437 |
| `relace` / `tencent` candidate groups | 4,162,158 | 57,698 tokens / $0.1008 | $6.5319 |

Both exceed the observed $6.2206 credit before the additional mandatory work. The second exceeds it by approximately $0.3112. These numbers do **not** prove every possible safe plan is unaffordable: the synthetic maxima are not future prompt bounds, 512 output tokens are not established as adequate, two judge pairs are not selected or demonstrated sufficient, and provider prices or credit can change. All real prompts must be checked against the approved estimator and any resulting reservation before dispatch.

For comparison only, the existing `candidate_token_price_bound` calculation takes the maximum of catalog and routing ceilings for overlapping prompt/completion categories and adds listed cache rates. Applied to these same candidate groups and stage counts, it produced approximately $3.3272. That arithmetic is **not** used by the current goal ledger or hosted dispatch, is not a complete billing guarantee, and does not establish that smoke and acceptance are affordable. It requires its own evidence and integration before it can affect any paid decision; do not substitute it for the current reservation or treat unknown charges as zero.

Before any real run: reconcile prior goal spending, establish account and billing restrictions, validate route and category bounds, select and freeze the complete evaluation policy, re-observe prices/credit, and reserve the entire mandatory run set under one durable goal budget. A partial or budget-exhausted comparison is not complete.
