# Exploratory comparison report

Dataset run: `e05af1a18465494b89e760d2c2e18357`
Dataset SHA-256: `9e8db1bab2e21f6ed422cdaeebabb73050c70eae9954ea062cb78cf05f47d315`
Stage: shared-corpus
Models: small `qwen/qwen3.5-35b-a3b`, frontier `tencent/hy4`
Fresh evaluator: local; local support threshold: 0.8
Targeted policy: enabled; extra search: disabled

Exploratory adjudication summary; unresolved cases remain unresolved. Not a confirmatory accuracy or non-inferiority claim.

Recorded reviewers: "Developer smoke - not independent". Reviewer independence is not verified.

Latency includes assigned failures and deferrals; cold/warm state was not recorded. Local resource costs are unobserved.

| Arm | Assigned | Correct and supported / justified | Incorrect | Unresolved | Decided | Deferred | Failed | Median s | P95 s | Provider cost USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| direct | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 1.306 | 1.306 | 0.000121 |
| fresh | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 21.105 | 21.105 | 0.000265 |
| frontier | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 1.782 | 1.782 | 0.000181 |

Work recorded per arm:
- direct: 1 provider calls; 1 source searches.
- fresh: 1 provider calls; 3 source searches.
- frontier: 1 provider calls; 1 source searches.

Decision rate uses all assigned cases. Coverage below is restricted to assessed answerable cases; uncertain and legacy cases are reported separately. No confidence interval or non-inferiority conclusion is provided.

- direct: answerable cases 1, issued decisions 1, coverage 100.0%, uncertain or legacy cases 0.
- fresh: answerable cases 1, issued decisions 1, coverage 100.0%, uncertain or legacy cases 0.
- frontier: answerable cases 1, issued decisions 1, coverage 100.0%, uncertain or legacy cases 0.

## Paired adjudications

- fresh vs frontier: left-only correct 0, right-only correct 0, both correct 1, both incorrect 0, unresolved 0.
- fresh vs direct: left-only correct 0, right-only correct 0, both correct 1, both incorrect 0, unresolved 0.
