# Synthetic canonical-rubric campaign verification

On 2026-11-08, `PYTHONPATH=src python scripts/smoke_factorial_synthetic.py --semantic --outcome --judge-pairs 2 --rubric --canonical-rubric` froze the canonical source-bound rubric contract and exercised all 105 assignments in a derived synthetic design. It reserved 567 slots and recorded 432 stand-in calls. The run was retained under `.local/verification/full-factorial-synthetic-8ecmaif2`. Repeating the command with `--resume .local/verification/full-factorial-synthetic-8ecmaif2` rechecked all assignments and recorded no additional calls. The earlier prose-rubric option remains available for its previous frozen run.

A manifest reconstructed from these same local records has SHA-256 `d2c9ada00c3fb624092ea792578579c8a81164510d429401fe3779919b342c8a`. `python scripts/verify_live_receipts.py --manifest .local/verification/full-factorial-synthetic-8ecmaif2/synthetic-manifest.json --sha256 d2c9ada00c3fb624092ea792578579c8a81164510d429401fe3779919b342c8a` checked 105 receipts and 16 cases, and exited 1 with `provider_attribution_not_live`. The 432 calls, 4,320 input tokens, 2,160 output tokens and $0.0432 are fixture values, not provider usage or spend.

Read-only invocation of the recommendation entrypoint with the locally reconstructed anchors checked the canonical contract and both holdout comparisons. Each baseline had 10 assigned and recorded pairs, all unknown, with null support. The result was incomplete, with no recommendation and `provider_attribution_not_live`. The anchors are derived from the same run and are not independent provenance. This does not validate source authority, labels, semantic review, provider billing, live performance or a real recommendation. No provider inference occurred.

The repeatable recommendation command is `python scripts/verify_recommendation.py --manifest .local/verification/full-factorial-synthetic-8ecmaif2/synthetic-manifest.json --sha256 d2c9ada00c3fb624092ea792578579c8a81164510d429401fe3779919b342c8a`. It exited 1 with `status: incomplete`, `provider_attribution_not_live`, 105 checked receipts, no recommendation and both 10-pair comparisons unknown. The digest is locally derived from the same run; providing it to the command does not make it independently authenticated.

## Source-version follow-up

After the recommendation implementation was extended to retain detailed comparison records, the frozen source-bound rubric no longer matches the current recommendation file. Re-running the same recommendation command still reconstructs 20 scored records per baseline for diagnosis but now returns `rubric_contract_invalid` as well as `provider_attribution_not_live`, and no recommendation. This is expected source-drift detection; the earlier result above remains a historical checkpoint. A new campaign must freeze the current contract before execution.

## Holdout companion diagnostic

After the companion-summary implementation changed, the prior frozen rubric no longer matches the selected source files. A current read-only diagnostic still reconstructs 10 assignments for each of the two direct baselines and the combined arm; all 30 classifications are unknown. Fixture journal totals were 30, 30 and 54 calls respectively, with the combined arm counted once. These are synthetic calls, not provider usage. The command remains incomplete with `provider_attribution_not_live` and `rubric_contract_invalid`, and produces no recommendation. This three-arm holdout summary is not the complete five-arm or intervention report.

## Five-arm holdout diagnostic

After adding the two ablation comparisons, read-only reconstruction of this retained synthetic run reported 10 holdout assignments and 10 unknown outcomes for each of the five arms. Fixture call counts were 30 direct full-evidence, 30 direct retrieval, 30 retrieval-only, 60 decomposition-only and 54 combined, counted once per arm. The current source differs from the frozen rubric and attribution is synthetic, so the result remains incomplete with no recommendation. This is holdout-only diagnostic evidence, not a full campaign/intervention report or real spending.

## Grouped holdout intervention diagnostic

The current read-only reconstruction groups changed-decisive, missing-decisive and irrelevant-change holdout interventions by parent/child, arm and repeat. The retained fixture has 10 pairs in each group; all have an unknown or missing category comparison. This is a comparison of attributed categories, not proof of semantic accuracy. The retained run still has synthetic attribution and a source-contract mismatch, so it remains incomplete and yields no recommendation.

## Full-campaign companion diagnostic

A later read-only reconstruction included all fully inspected assignments, partitioned by the frozen design. It reported 6 development, 5 pilot and 10 holdout assignments per arm; each partition covers all five arms. Pilot groups contained 5 pairs each for changed-decisive, missing-decisive and irrelevant-change interventions; holdout groups contained 10 pairs each. These are locally reconstructed synthetic records and their categories remain unknown, not real outcome evidence. The run remains incomplete for synthetic attribution and a changed source contract; no recommendation is produced. Reported source access differences, live evidence and final acceptance remain open.
