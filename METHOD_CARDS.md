# Method cards

Each card is a candidate adaptation, not an implemented qJig feature. Source evidence paths refer to checkpointed review inputs.

| ID | Source / method | Adaptation and when useful | Acceptance probe | Fallback / provenance |
|---|---|---|---|---|
| M01 | QUIXER `ingest.py`, `store.py`: revisions and anchored sections | Separate immutable source snapshots from rebuildable indexes | Changing origin preserves old run spans and marks current index stale | Use original source span; retain both hashes and origin |
| M02 | QUIXER `indexing.py`: fallback and finer passages | Missing/broad headings produce extractive proposed navigation entries | Every generated passage equals its pinned source slice | Whole section remains searchable; no invented headings as authority |
| M03 | QUIXER `retrieve.py`: topic/role variants | A role prior orders evidence without removing obligations | Low role estimate cannot suppress a decisive exception | Deterministic BM25 and explicit missing score |
| M04 | QUIXER `evidence_recovery.py`: source verification and alternatives | Recover unavailable/changed candidate paths within bounded acquisition | Delete first candidate; replacement gets exact source-bound span and exclusion | Defer if no suitable evidence; do not substitute a different subject |
| M05 | JIG `core.py:275`: bounded composition and possible outcomes | Stop only when remaining graph facts cannot change result | Enumerate all <=6-ref assignments; repeated refs keep identity | Exhaustive evaluation control; semantic completeness separate |
| M06 | JIG `local_judge.py:29`: paired support states | Semantic support does not collapse uncertainty into false | Both supported -> conflict; neither -> unknown | Exact operators where suitable; uncertain model result stays unknown |
| M07 | JIG `collections.py` + private pilot keyed records | Scope evidence by entity/date/authority while preserving exceptions | Same value under different policy dates changes only appropriate case | Retrieve broader relevant sources if key binding unknown |
| M08 | JIG `programs.py`: exact binding and interventions | Save/replay reviewed plans under explicit applicability | New request/snapshot cannot inherit reviewed status | Fresh decomposition; never auto-activate a generalized program |
| M09 | JIG `datasets.py`: intents, receipts, locks | One ledger owns calls and restart decisions | Crash after intent before receipt produces uncertain state, no blind retry | Reconcile or leave incomplete; preserve known charges |
| M10 | JIG benchmark protocol and QUIXER experiment runner | Compare actual arms under pinned inputs | All assigned failures/deferrals/retries appear in denominator and costs | Label exploratory and unknown fields explicitly |

For every adaptation preserve original source identity and method/version in documentation. No top-level license was located in either inspected package; local reference snapshots do not imply distribution rights. Check provenance before importing substantial third-party code (especially JIG's flat upstream reference export). Small new qJig pure modules should be independently implemented from specified behavior and attributed to the design sources.
