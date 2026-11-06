# Private knowledge decision pilot

This companion to the Decision Program Workbench handoff contains a new fictional ED operations report release folder. The rules, report names, statuses, and dates were authored for this exercise. They were not drawn from a public benchmark or a real hospital. The corpus ID is `ALDERLINE-7759F34F9E`. Use fresh model sessions for a blind comparison and provide only the requested test inputs.

The question for each case is whether a named report can be released to a named route on a specified date. Two policy versions govern the lag limit and peer review. Separate records govern hold status, route authorization, observed lag, reviews, and scoped waivers. Missing rows, an unavailable source, conflicts, expired waivers, and draft documents create different evidence problems.

## Measured offline comparison

The same deterministic engine and hand-authored decision logic executed all three modes. The only changes were which files reached the case evaluator, whether it stopped after a definitive blocker, and whether it passed entire documents or matched rows with their source metadata. The evaluation rubric is hand-authored and the cases are development fixtures. The source index is built once. Access counts are logical documents delivered per case, summed over the batch. Byte counts use the same JSON formatting and count evidence only.

| Source-access mode | Correct on fixture | Expected source IDs present | Document deliveries | Evidence bytes |
|---|---:|---:|---:|---:|
| Whole folder | 18/18 | 18/18 | 179 | 187,565 |
| Predicate-directed, whole selected documents | 18/18 | 18/18 | 72 | 123,625 |
| Predicate-directed, only matched rows | 18/18 | 18/18 | 72 | 38,059 |

Targeting reduced logical document deliveries by 59.8%. Keyed row selection reduced the final evidence payload by 79.7% versus whole-folder delivery. This is a measured input reduction on one structured corpus. The sizes exclude system and model prompts, retrieval/index work, and repeated context across model calls. The offline harness does not measure model accuracy, token usage, wall time, or cost. It recorded zero live calls. The local MLX model was unavailable in the execution environment and the attempted frontier CLI probe failed during initialization.

Among the controlled examples:

- `C01` / `C02`: the same 72-minute lag passes the October rule and fails the November rule.
- `C03` / `C04`: a signed review is in the folder but begins after the first request date. The first decision defers and the later one releases.
- `C05` / `C06` / `C15`: an internal waiver allows release. It fails to cover the partner route, and withholding the waiver register leaves the original internal request unresolved.
- `C11`: a definitive route prohibition makes missing lag immaterial. The targeted arm reads only `R01`.
- `C10` and `C12`: contradictory dated records and an omitted required entity each yield deferral when material.

## Files and commands

```sh
python3 pilot.py compare
python3 pilot.py prompt C05 --mode blind
python3 pilot.py prompt C05 --mode full
python3 pilot.py prompt C05 --mode planner
python3 pilot.py prompt C05 --mode scripted-packet
```

The fixture runner needs only the Python standard library. `corpus/` contains the source files. `cases.json` contains questions and fixture binding fields. Live models should receive the question text and permitted evidence or index, with fixture binding fields withheld in the fresh-planner arm. `evaluation/gold.json` contains reference outcomes, expected source IDs, and reasons. `evaluation/offline_results.json` contains the measured counts and individual traces. Keep both evaluation files out of the model inputs and any indexed corpus. `scripted-packet` emits full documents chosen by the reference scheduler and is a diagnostic aid. It is distinct from a fresh model-planned run or the keyed row mode.

## Live comparison to run next

1. **Blind control.** Give the frontier model a question with no source access. The outcome should be a justified deferral. This demonstrates source dependence and stays outside the accuracy contest.
2. **Frontier with the folder.** Give an independently run frontier model the same private sources, including the applicable draft and distractor files. For this small folder, full direct context is a strong baseline. On larger copies, include a frontier arm with the same indexed access. Honor the C15 withheld source in every evidence-bearing arm.
3. **Smaller model with direct RAG.** Let the same small model used by the planner answer directly under the same bounded knowledge access and allowance for a second search. Include a direct answer arm with the same evidence packet when isolating the value of predicate decomposition and judging.
4. **Fresh smaller pipeline.** Give the planner the question and the source index. It proposes the predicates, material exceptions, and evidence requirements. Fetch scoped records with their metadata and relevant contradictory rows. Use code for exact comparisons and the local Jev judge for semantic interpretation. Use one bounded second search for a material gap and combine without frontier fallback.
5. **Score independently.** Blind reviewers to the arm. Grade decision correctness and evidence support separately. Record input/output tokens, all model calls, retrieval time, end-to-end latency, and total cost. Report any frontier fallback or reviewed program reuse in separate arms. Use a fresh set of cases and source variations before making a non-inferiority claim.

The best candidate for a live win is a question with explicit local authority, a short policy plus several keyed registers, and a material exception. Scoped evidence can be much smaller than the entire folder, and exact work is cheap. The unresolved question is whether a fresh planner finds every decisive requirement and whether the judge correctly handles the material semantic cases. A separate contrast against an equally well-supplied direct model addresses that question.
