# Draft software evaluation corpus

**Status: draft; not a frozen experiment and not authorization for provider calls.**

This local authored corpus is stored under `.local/evaluation-draft-20261107`, which is ignored by Git. Reference labels and per-case source mappings are in its `private/` directory and must not be provided to retrieval or models. Their completeness and isolation have not been independently verified.

Six source families are assigned to development (release, cache), pilot (deploy, webhook), and holdout (export, lock). The 16 cases comprise 6 development, 5 pilot and 5 holdout cases; pilot and holdout each contain changed, missing and irrelevant paired interventions. Five declared arms and two holdout repeats imply 105 standalone case/arm assignments; separate reuse/escalation work is additional.

The labels are `authored_unvalidated`. The checked-in design digest identifies a local draft, not independent labels or a completed evaluation. Current retain/revise/remove thresholds are placeholders, overlap, and must be replaced with exact, non-overlapping, predeclared criteria before any freeze. Complete price/token preflight, matching of arm access and work, review provenance, leakage checks and the full-run allocation remain open.

Sixteen private source-bound reference records contain 17 exact evidence quotations, all present in locally indexed passages. A synthetic-only check produced `matches_reference` for one cited case and `unknown_review` for one missing-source case without a citation; these are mechanics, not model results.

Sixteen local assertions over these authored sources checked the intended outcomes, including explicit missing-source cases. An initial BM25 search returned no hits for the two missing-source cases; a miss is not evidence of absence. No model call was made.

Local design SHA-256: `21268a1569dd10223f8f4a9e429dc0539593e7da2cedf367ea550df316d419f4`.

## Source snapshots

| Local path relative to draft root | SHA-256 |
|---|---|
| `sources/dev/cache/ttl.py` | `e27efb6f543cf181a51f6d0169666a777a258a71a592804cb32971402471a166` |
| `sources/dev/release/other_rule.py` | `420e74f36b74795b8cadd70c924cbc3e5d23bdc58f63ea73135e046219b5665b` |
| `sources/dev/release/rule.py` | `a26dbdd2afc06166cf5397e3e7889bf295cb5326d0391263cc52088dfa449ff8` |
| `sources/holdout/export_v1/access.py` | `2bf6659b466923f6709087f0bcf4052e57ace8604de352af70fda10e6ad4e06f` |
| `sources/holdout/export_v2/access.py` | `a12e0a6691c29d9640259ba352a1c94c8bbb624de79fe57a46739e5beafbcf1e` |
| `sources/holdout/export_v3/access.py` | `4b2a069ac11fbff6e4150d3ce6628d049e3b9380c5a9fe8b604f07218192ec0d` |
| `sources/holdout/export_v4/notice.txt` | `77d7b69dab5db0259495e25e1ac2fe36e12419fa5eb3df7192ac1a6503f153c4` |
| `sources/holdout/lock/lock.py` | `6107ee0b49fd7b3f8fed7fb445ae066f7ef24d18af44095736ab4fb44190a61f` |
| `sources/pilot/deploy_v1/rule.py` | `159eb6f9e08686faedb9a50446208146b83e13ec4a6703a754959c6fe4e36802` |
| `sources/pilot/deploy_v2/rule.py` | `ea5475ddc94a50de147905b69aff7ba40c4586c917de55ff267c1d5255730c74` |
| `sources/pilot/deploy_v3/rule.py` | `9e53c2dcdc69ea10c922c6885b9cd5623b635917347388563f79bb46e128882c` |
| `sources/pilot/deploy_v4/notice.txt` | `3e5b86d557371051925f85e44d6d4a5a1e27edd160bed5efe20cdeacf19f2e02` |
| `sources/pilot/webhook/retry.py` | `1456799b95c5539fa8e157031d2a454d66acb2b476f7218f032c235b0ca39615` |

## Private artifact identities

These hashes identify local private artifacts without publishing their contents.

| Local path relative to draft root | SHA-256 |
|---|---|
| `private/inputs.json` | `e5abaa4c09ac1b9b2358e87d5d94e5959e797df1bdc8de9e10b45493a31d5f0f` |
| `private/labels.json` | `171e6f2ddebe4a0041be08a65314438da81a0483fbaf3b7ecee93b7542a2205b` |
| `private/references.json` | `12b1b2fa97c879261abec0ca4bffd75ea6c055b77b6559d6d9bd904d99e7864d` |
