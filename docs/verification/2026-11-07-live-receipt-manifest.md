# Live campaign receipt inspection

`python scripts/verify_live_receipts.py --manifest PATH --sha256 DIGEST` inspects a retained campaign without model calls. The digest must be independently retained for the exact manifest bytes. Omitting it reports `manifest_anchor_unavailable` and cannot produce a complete result. Changed, missing or malformed evidence exits 1; an incomplete campaign also exits 1. A structurally complete result is not provider authentication, semantic truth, independent label validation or evidence beyond the declared artifacts.

The local private JSON manifest has exactly these keys:

- `schema`: `qjig.live-manifest.v1`.
- `goal_db`, `journal_db`, `archive_root`: existing local paths to the frozen goal ledger, journal and campaign archive directory.
- `plan_id`, `plan_sha256`, `config_sha256`: frozen campaign identity and independently retained digests.
- `references`: case ID to private reference record. Keep the manifest private and out of Git.
- `run_sha256`, `journal_sha256`, `review_sha256`: request ID to independently retained digest; use an empty object when unavailable. Review anchors are mandatory for scored v4 reviews, and fresh runs require journal anchors.
- `reference_sha256`: case ID to independently retained reference digest.
- `case_root`: path to the isolated source root; `case_inputs`: case ID to an object containing `lock`, `reference`, `protected` and serialized `applicability_inputs`. The inspector validates every assigned case and declared source/protected-artifact isolation. Use null when unavailable, which remains incomplete.

SQLite databases and archived runs are opened read-only. The inspector requires the complete assigned denominator, recorded resource accounting and live attribution; declared isolation cannot establish that undeclared or transformed labels were excluded. Manifest paths and externally supplied anchors are assertions, not proofs of provenance. Keep raw receipts, inputs and credentials in ignored local storage.
