# Risks and regression requirements

| ID | Risk / consequence | Required mitigation/test | Phase |
|---|---|---|---|
| R01 | Normalized/raw hash or offset confusion cites wrong text | Separate hashes, explicit translation, CRLF/BOM/Unicode probes | P1 |
| R02 | Wrong entity or dates appear relevant | Key-bound facts and applicability reason states | P1/P2 |
| R03 | Missing exception becomes false | Explicit obligation and absence policy; missing register -> unknown | P2/P3 |
| R04 | Incomplete generated graph yields plausible stable answer | Authored diagnostic, coverage-gap trace, fresh-plan negative cases, final assessment | P3/P4 |
| R05 | Role prior hides decisive source | Exception channel and no role-only exclusion test | P2 |
| R06 | Provider confidence mistaken for truth | Typed support + unknown/conflict; no default calibrated claim | P4 |
| R07 | Source text injects instructions or wrong relationships | Separate data/control plus held adversarial cases; document unresolved semantics | P4/P6 |
| R08 | Paid call repeated after uncertain completion | Intent-before-call, terminal receipt, reconciliation on resume | P4 |
| R09 | Two agents overwrite claims or revisions | Append-only ownership, idempotency, serialized writer; concurrent request test | P5 |
| R10 | Small fixtures or AI reviews claimed as general benefit | Separate fixture/live/exploratory/independent evidence and arms | P6 |
| R11 | Legacy source folder still changes | Manifest recheck before commit/import; audit only frozen snapshots | P0 |
| R12 | Incomplete budget excludes prompts/extra calls | Complete serialized envelope accounting and actual receipts, unknown cost state | P4/P6 |
| R13 | Monolithic merge creates hidden dependencies | New core isolated from legacy config/data; import-no-side-effect test | P1 |
| R14 | Missing license/provenance for source distribution | Preserve provenance and inspect rights before publishing copied source | Before publication |
| R15 | PDF page anchors overstate semantic/text assurance | Distinguish raw bytes, extraction/text/span assurance; no OCR claim | Optional |
| R16 | Moved virtualenv has old absolute paths | Recreate separately from pinned config if local judge needed; no env copying into Git | P4 |
| R17 | Excessive planning obscures action | One ready task at a time; first vertical slice gate after T038 | All |
