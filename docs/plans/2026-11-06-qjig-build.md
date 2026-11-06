# qJig granular implementation plan

> **For Codex:** Use the available `executing-plans` skill to implement this plan task by task after design review. The legacy `superpowers:executing-plans` name in older templates is not an installed namespace here.

**Goal:** Build a shared evidence and explicit decision workbench through independently testable behaviors.

**Architecture:** One canonical source/trace contract with immutable source blobs and one SQLite owner. Small pure decision functions compose evidence observations; bounded acquisition and provider adapters sit outside the logic. Source apps are references and temporary adapters, not ambient runtime dependencies.

**Tech stack:** Python 3.11+, standard-library domain/storage/runtime initially, pytest development tests, thin loopback HTML/HTTP after the CLI. Optional model libraries remain isolated.

---

Status: proposed build sequence for review. No runtime tasks are marked complete. Use the dependencies in `plan/tasks.json`; a later task cannot close before its prerequisites. Tests below are planned names and commands, not present tests. A first missing import is acceptable to establish the boundary; all subsequent red tests must fail because the named behavior is absent. Commit subjects are suggestions.

The fixtures in tests should be a few lines, not copied live provider output. For provider-bound tasks a deterministic transport proves mapping and accounting only; the separate opt-in real smoke must run before claiming model integration. Every task's acceptance sentence is the implementation contract; when insufficient to resolve a semantic choice, add the smallest counterexample and record the decision before writing code.

## T001: Establish the isolated qjig package and pytest configuration

Phase: P1. Depends on: reviewed design. Status: pending.

Files: `pyproject.toml`, `src/qjig/__init__.py`. Test: `tests/test_bootstrap.py::test_import_has_no_io`.

Acceptance: Import succeeds without opening config, connecting or creating data.

1. Add `test_import_has_no_io` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_bootstrap.py::test_import_has_no_io -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_bootstrap.py::test_import_has_no_io -q`, then `python -m pytest tests/test_bootstrap.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add pyproject.toml src/qjig/__init__.py tests/test_bootstrap.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T001: import_has_no_io"`. Include the actual test receipt before marking complete.

## T002: Round-trip a minimal versioned Request with exact role and scope

Phase: P1. Depends on: T001. Status: pending.

Files: `src/qjig/contracts.py`. Test: `tests/test_contracts.py::test_roundtrip_request`.

Acceptance: The parsed request equals the serialized request and rejects unknown schema version.

1. Add `test_roundtrip_request` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_contracts.py::test_roundtrip_request -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_contracts.py::test_roundtrip_request -q`, then `python -m pytest tests/test_contracts.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/contracts.py tests/test_contracts.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T002: roundtrip_request"`. Include the actual test receipt before marking complete.

## T003: Validate budgets without coercing booleans or negative numbers

Phase: P1. Depends on: T002. Status: pending.

Files: `src/qjig/contracts.py`. Test: `tests/test_contracts.py::test_reject_invalid_budget`.

Acceptance: True and negative limits are rejected before external work.

1. Add `test_reject_invalid_budget` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_contracts.py::test_reject_invalid_budget -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_contracts.py::test_reject_invalid_budget -q`, then `python -m pytest tests/test_contracts.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/contracts.py tests/test_contracts.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T003: reject_invalid_budget"`. Include the actual test receipt before marking complete.

## T004: Store original source bytes and separate decoded text hash

Phase: P1. Depends on: T002. Status: pending.

Files: `src/qjig/sources.py`. Test: `tests/test_sources.py::test_preserve_raw_bytes`.

Acceptance: CRLF bytes retain original raw hash while text decoding is explicit.

1. Add `test_preserve_raw_bytes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_sources.py::test_preserve_raw_bytes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_sources.py::test_preserve_raw_bytes -q`, then `python -m pytest tests/test_sources.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/sources.py tests/test_sources.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T004: preserve_raw_bytes"`. Include the actual test receipt before marking complete.

## T005: Separate source identity from workstation path

Phase: P1. Depends on: T004. Status: pending.

Files: `src/qjig/sources.py`. Test: `tests/test_sources.py::test_portable_source_identity`.

Acceptance: Relocating an origin does not silently change a pinned revision identity.

1. Add `test_portable_source_identity` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_sources.py::test_portable_source_identity -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_sources.py::test_portable_source_identity -q`, then `python -m pytest tests/test_sources.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/sources.py tests/test_sources.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T005: portable_source_identity"`. Include the actual test receipt before marking complete.

## T006: Verify end-exclusive Unicode text offsets and reject forged body

Phase: P1. Depends on: T004. Status: pending.

Files: `src/qjig/spans.py`. Test: `tests/test_spans.py::test_verify_unicode_span`.

Acceptance: A multibyte string slice matches exactly and an altered quote fails.

1. Add `test_verify_unicode_span` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_spans.py::test_verify_unicode_span -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_spans.py::test_verify_unicode_span -q`, then `python -m pytest tests/test_spans.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/spans.py tests/test_spans.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T006: verify_unicode_span"`. Include the actual test receipt before marking complete.

## T007: Translate one CRLF QUIXER line span into canonical offsets

Phase: P1. Depends on: T006. Status: pending.

Files: `src/qjig/legacy_quix.py`. Test: `tests/test_legacy_quix.py::test_translate_normalized_lines`.

Acceptance: Legacy normalized hash and canonical raw/text identities stay distinct.

1. Add `test_translate_normalized_lines` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_legacy_quix.py::test_translate_normalized_lines -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_legacy_quix.py::test_translate_normalized_lines -q`, then `python -m pytest tests/test_legacy_quix.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/legacy_quix.py tests/test_legacy_quix.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T007: translate_normalized_lines"`. Include the actual test receipt before marking complete.

## T008: Translate a JIG snapshot quote into canonical span

Phase: P1. Depends on: T006. Status: pending.

Files: `src/qjig/legacy_jig.py`. Test: `tests/test_legacy_jig.py::test_translate_raw_offsets`.

Acceptance: The same text cannot bind to another revision with changed content.

1. Add `test_translate_raw_offsets` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_legacy_jig.py::test_translate_raw_offsets -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_legacy_jig.py::test_translate_raw_offsets -q`, then `python -m pytest tests/test_legacy_jig.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/legacy_jig.py tests/test_legacy_jig.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T008: translate_raw_offsets"`. Include the actual test receipt before marking complete.

## T009: Persist immutable source revisions and reopen the catalog

Phase: P1. Depends on: T004. Status: pending.

Files: `src/qjig/store.py`. Test: `tests/test_store.py::test_reopen_revision`.

Acceptance: Two revisions survive close/reopen and cannot overwrite one another.

1. Add `test_reopen_revision` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_store.py::test_reopen_revision -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_store.py::test_reopen_revision -q`, then `python -m pytest tests/test_store.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/store.py tests/test_store.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T009: reopen_revision"`. Include the actual test receipt before marking complete.

## T010: Represent independently dated collection members

Phase: P1. Depends on: T009. Status: pending.

Files: `src/qjig/applicability.py`. Test: `tests/test_applicability.py::test_per_member_dates`.

Acceptance: Old and new policy coexist without a shared effective interval.

1. Add `test_per_member_dates` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_applicability.py::test_per_member_dates -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_applicability.py::test_per_member_dates -q`, then `python -m pytest tests/test_applicability.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/applicability.py tests/test_applicability.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T010: per_member_dates"`. Include the actual test receipt before marking complete.

## T011: Return unknown for missing entity binding

Phase: P1. Depends on: T010. Status: pending.

Files: `src/qjig/applicability.py`. Test: `tests/test_applicability.py::test_missing_entity_unknown`.

Acceptance: An absent required subject never passes as inapplicable.

1. Add `test_missing_entity_unknown` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_applicability.py::test_missing_entity_unknown -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_applicability.py::test_missing_entity_unknown -q`, then `python -m pytest tests/test_applicability.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/applicability.py tests/test_applicability.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T011: missing_entity_unknown"`. Include the actual test receipt before marking complete.

## T012: Apply effective and observation dates independently

Phase: P1. Depends on: T010. Status: pending.

Files: `src/qjig/applicability.py`. Test: `tests/test_applicability.py::test_historical_observation`.

Acceptance: A review observed after the historical request cannot settle it.

1. Add `test_historical_observation` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_applicability.py::test_historical_observation -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_applicability.py::test_historical_observation -q`, then `python -m pytest tests/test_applicability.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/applicability.py tests/test_applicability.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T012: historical_observation"`. Include the actual test receipt before marking complete.

## T013: Index one Markdown heading as a source-derived view

Phase: P2. Depends on: T009. Status: pending.

Files: `src/qjig/indexing.py`. Test: `tests/test_indexing.py::test_heading_span`.

Acceptance: The stored heading section resolves to exact pinned text.

1. Add `test_heading_span` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_indexing.py::test_heading_span -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_indexing.py::test_heading_span -q`, then `python -m pytest tests/test_indexing.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/indexing.py tests/test_indexing.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T013: heading_span"`. Include the actual test receipt before marking complete.

## T014: Create an explicitly generated extractive fallback span

Phase: P2. Depends on: T013. Status: pending.

Files: `src/qjig/indexing.py`. Test: `tests/test_indexing.py::test_missing_heading_fallback`.

Acceptance: Unheaded text stays searchable without invented authoritative headings.

1. Add `test_missing_heading_fallback` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_indexing.py::test_missing_heading_fallback -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_indexing.py::test_missing_heading_fallback -q`, then `python -m pytest tests/test_indexing.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/indexing.py tests/test_indexing.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T014: missing_heading_fallback"`. Include the actual test receipt before marking complete.

## T015: Split a broad section into proposed paragraph entries

Phase: P2. Depends on: T014. Status: pending.

Files: `src/qjig/indexing.py`. Test: `tests/test_indexing.py::test_broad_heading_paragraphs`.

Acceptance: Each child is an exact source slice with proposed status.

1. Add `test_broad_heading_paragraphs` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_indexing.py::test_broad_heading_paragraphs -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_indexing.py::test_broad_heading_paragraphs -q`, then `python -m pytest tests/test_indexing.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/indexing.py tests/test_indexing.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T015: broad_heading_paragraphs"`. Include the actual test receipt before marking complete.

## T016: Invalidate derived indexes after an origin revision

Phase: P2. Depends on: T015. Status: pending.

Files: `src/qjig/indexing.py`. Test: `tests/test_indexing.py::test_revision_stales_indexes`.

Acceptance: Old entries are inspectable but cannot appear current for the new source.

1. Add `test_revision_stales_indexes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_indexing.py::test_revision_stales_indexes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_indexing.py::test_revision_stales_indexes -q`, then `python -m pytest tests/test_indexing.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/indexing.py tests/test_indexing.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T016: revision_stales_indexes"`. Include the actual test receipt before marking complete.

## T017: Return deterministic lexical candidates and score provenance

Phase: P2. Depends on: T013. Status: pending.

Files: `src/qjig/retrieval.py`. Test: `tests/test_retrieval.py::test_deterministic_bm25`.

Acceptance: Equal scores have stable ID ordering on repeated runs.

1. Add `test_deterministic_bm25` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_retrieval.py::test_deterministic_bm25 -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_retrieval.py::test_deterministic_bm25 -q`, then `python -m pytest tests/test_retrieval.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/retrieval.py tests/test_retrieval.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T017: deterministic_bm25"`. Include the actual test receipt before marking complete.

## T018: Attach multiple topic views without copying evidence

Phase: P2. Depends on: T017. Status: pending.

Files: `src/qjig/topics.py`. Test: `tests/test_topics.py::test_multi_topic_links`.

Acceptance: Two topics reference the same immutable span identity.

1. Add `test_multi_topic_links` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_topics.py::test_multi_topic_links -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_topics.py::test_multi_topic_links -q`, then `python -m pytest tests/test_topics.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/topics.py tests/test_topics.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T018: multi_topic_links"`. Include the actual test receipt before marking complete.

## T019: Store an estimated role score against role and revision

Phase: P2. Depends on: T017. Status: pending.

Files: `src/qjig/roles.py`. Test: `tests/test_roles.py::test_role_version_binding`.

Acceptance: Changing role version makes the old estimate unavailable as a current prior.

1. Add `test_role_version_binding` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_roles.py::test_role_version_binding -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_roles.py::test_role_version_binding -q`, then `python -m pytest tests/test_roles.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/roles.py tests/test_roles.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T019: role_version_binding"`. Include the actual test receipt before marking complete.

## T020: Order candidates without removing a mandatory exception channel

Phase: P2. Depends on: T019. Status: pending.

Files: `src/qjig/retrieval.py`. Test: `tests/test_retrieval.py::test_role_cannot_hide_exception`.

Acceptance: A low role score cannot eliminate the task's required exception source.

1. Add `test_role_cannot_hide_exception` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_retrieval.py::test_role_cannot_hide_exception -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_retrieval.py::test_role_cannot_hide_exception -q`, then `python -m pytest tests/test_retrieval.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/retrieval.py tests/test_retrieval.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T020: role_cannot_hide_exception"`. Include the actual test receipt before marking complete.

## T021: Budget the complete evidence packet and mark truncation

Phase: P2. Depends on: T017, T006. Status: pending.

Files: `src/qjig/packets.py`. Test: `tests/test_packets.py::test_serialized_budget`.

Acceptance: Included packet is within named limit and every omission has a reason.

1. Add `test_serialized_budget` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_packets.py::test_serialized_budget -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_packets.py::test_serialized_budget -q`, then `python -m pytest tests/test_packets.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/packets.py tests/test_packets.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T021: serialized_budget"`. Include the actual test receipt before marking complete.

## T022: Exclude an unavailable candidate and return a verified alternative

Phase: P2. Depends on: T021. Status: pending.

Files: `src/qjig/recovery.py`. Test: `tests/test_recovery.py::test_missing_source_alternative`.

Acceptance: Packet records missing-source reason and alternative exact span.

1. Add `test_missing_source_alternative` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_recovery.py::test_missing_source_alternative -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_recovery.py::test_missing_source_alternative -q`, then `python -m pytest tests/test_recovery.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/recovery.py tests/test_recovery.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T022: missing_source_alternative"`. Include the actual test receipt before marking complete.

## T023: Keep insufficient evidence when only wrong-subject candidates remain

Phase: P2. Depends on: T022. Status: pending.

Files: `src/qjig/recovery.py`. Test: `tests/test_recovery.py::test_no_suitable_alternative`.

Acceptance: Unrelated or inapplicable text does not fill a decisive evidence slot.

1. Add `test_no_suitable_alternative` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_recovery.py::test_no_suitable_alternative -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_recovery.py::test_no_suitable_alternative -q`, then `python -m pytest tests/test_recovery.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/recovery.py tests/test_recovery.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T023: no_suitable_alternative"`. Include the actual test receipt before marking complete.

## T024: Track unresolved evidence obligations after no retrieval hit

Phase: P2. Depends on: T021, T011, T012. Status: pending.

Files: `src/qjig/obligations.py`. Test: `tests/test_obligations.py::test_no_hit_is_unknown`.

Acceptance: No hit cannot become a negative fact or proof that no exception exists.

1. Add `test_no_hit_is_unknown` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_obligations.py::test_no_hit_is_unknown -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_obligations.py::test_no_hit_is_unknown -q`, then `python -m pytest tests/test_obligations.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/obligations.py tests/test_obligations.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T024: no_hit_is_unknown"`. Include the actual test receipt before marking complete.

## T025: Implement the four explicit paired-support states

Phase: P3. Depends on: T002. Status: pending.

Files: `src/qjig/logic.py`. Test: `tests/test_logic.py::test_support_state_table`.

Acceptance: The four distinct support combinations yield true false unknown conflict.

1. Add `test_support_state_table` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_logic.py::test_support_state_table -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_logic.py::test_support_state_table -q`, then `python -m pytest tests/test_logic.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/logic.py tests/test_logic.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T025: support_state_table"`. Include the actual test receipt before marking complete.

## T026: Validate unique refs operators depth and predicate cap

Phase: P3. Depends on: T025. Status: pending.

Files: `src/qjig/plans.py`. Test: `tests/test_plans.py::test_validate_ast`.

Acceptance: Dangling refs cycles unknown operators and more than six predicates fail.

1. Add `test_validate_ast` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_plans.py::test_validate_ast -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_plans.py::test_validate_ast -q`, then `python -m pytest tests/test_plans.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/plans.py tests/test_plans.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T026: validate_ast"`. Include the actual test receipt before marking complete.

## T027: Evaluate bounded AND OR NOT with unresolved states

Phase: P3. Depends on: T026. Status: pending.

Files: `src/qjig/logic.py`. Test: `tests/test_logic.py::test_compose_truth_table`.

Acceptance: Exact truth-table cases preserve unknown and conflict reasons.

1. Add `test_compose_truth_table` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_logic.py::test_compose_truth_table -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_logic.py::test_compose_truth_table -q`, then `python -m pytest tests/test_logic.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/logic.py tests/test_logic.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T027: compose_truth_table"`. Include the actual test receipt before marking complete.

## T028: Enumerate consistent completions by unique predicate ID

Phase: P3. Depends on: T027. Status: pending.

Files: `src/qjig/logic.py`. Test: `tests/test_logic.py::test_reachable_outcomes`.

Acceptance: Repeated references share one assignment across the expression.

1. Add `test_reachable_outcomes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_logic.py::test_reachable_outcomes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_logic.py::test_reachable_outcomes -q`, then `python -m pytest tests/test_logic.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/logic.py tests/test_logic.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T028: reachable_outcomes"`. Include the actual test receipt before marking complete.

## T029: Determine whether one unresolved fact can change the result

Phase: P3. Depends on: T028. Status: pending.

Files: `src/qjig/logic.py`. Test: `tests/test_logic.py::test_material_predicate`.

Acceptance: Unknown exception stays material after ordinary=false under OR.

1. Add `test_material_predicate` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_logic.py::test_material_predicate -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_logic.py::test_material_predicate -q`, then `python -m pytest tests/test_logic.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/logic.py tests/test_logic.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T029: material_predicate"`. Include the actual test receipt before marking complete.

## T030: Check evidence obligations before accepting graph stability

Phase: P3. Depends on: T029, T024. Status: pending.

Files: `src/qjig/stopping.py`. Test: `tests/test_stopping.py::test_coverage_blocks_stop`.

Acceptance: A stable expression cannot bypass an unresolved material applicability obligation.

1. Add `test_coverage_blocks_stop` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_stopping.py::test_coverage_blocks_stop -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_stopping.py::test_coverage_blocks_stop -q`, then `python -m pytest tests/test_stopping.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/stopping.py tests/test_stopping.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T030: coverage_blocks_stop"`. Include the actual test receipt before marking complete.

## T031: Evaluate one exact numeric rule under the applicable policy

Phase: P3. Depends on: T012, T025. Status: pending.

Files: `src/qjig/exact.py`. Test: `tests/test_exact.py::test_dated_numeric_rule`.

Acceptance: Same observation passes old threshold and fails new threshold.

1. Add `test_dated_numeric_rule` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_exact.py::test_dated_numeric_rule -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_exact.py::test_dated_numeric_rule -q`, then `python -m pytest tests/test_exact.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/exact.py tests/test_exact.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T031: dated_numeric_rule"`. Include the actual test receipt before marking complete.

## T032: Choose next material need by dependencies then planner order then ID

Phase: P3. Depends on: T030. Status: pending.

Files: `src/qjig/scheduler.py`. Test: `tests/test_scheduler.py::test_deterministic_next_need`.

Acceptance: Same state schedules the same need and never skips a prerequisite.

1. Add `test_deterministic_next_need` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_scheduler.py::test_deterministic_next_need -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_scheduler.py::test_deterministic_next_need -q`, then `python -m pytest tests/test_scheduler.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/scheduler.py tests/test_scheduler.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T032: deterministic_next_need"`. Include the actual test receipt before marking complete.

## T033: Run one acquisition and exact-evaluation round

Phase: P3. Depends on: T032, T022, T031. Status: pending.

Files: `src/qjig/acquisition.py`. Test: `tests/test_acquisition.py::test_one_round_trace`.

Acceptance: Trace binds request predicate source span and observation.

1. Add `test_one_round_trace` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acquisition.py::test_one_round_trace -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acquisition.py::test_one_round_trace -q`, then `python -m pytest tests/test_acquisition.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acquisition.py tests/test_acquisition.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T033: one_round_trace"`. Include the actual test receipt before marking complete.

## T034: Allow one targeted followup for a material unresolved need

Phase: P3. Depends on: T033, T024. Status: pending.

Files: `src/qjig/acquisition.py`. Test: `tests/test_acquisition.py::test_bounded_followup`.

Acceptance: A third round is refused and remains an explicit unknown.

1. Add `test_bounded_followup` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acquisition.py::test_bounded_followup -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acquisition.py::test_bounded_followup -q`, then `python -m pytest tests/test_acquisition.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acquisition.py tests/test_acquisition.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T034: bounded_followup"`. Include the actual test receipt before marking complete.

## T035: Skip immaterial facts only with a recorded stopping witness

Phase: P3. Depends on: T034, T030. Status: pending.

Files: `src/qjig/acquisition.py`. Test: `tests/test_acquisition.py::test_stop_after_blocker`.

Acceptance: A conclusive AND blocker skips unrelated work with preserved reason.

1. Add `test_stop_after_blocker` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acquisition.py::test_stop_after_blocker -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acquisition.py::test_stop_after_blocker -q`, then `python -m pytest tests/test_acquisition.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acquisition.py tests/test_acquisition.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T035: stop_after_blocker"`. Include the actual test receipt before marking complete.

## T036: Retain conflicting applicable observations

Phase: P3. Depends on: T034. Status: pending.

Files: `src/qjig/acquisition.py`. Test: `tests/test_acquisition.py::test_material_conflict_defers`.

Acceptance: A material contradiction cannot be chosen away by score or latest file time.

1. Add `test_material_conflict_defers` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acquisition.py::test_material_conflict_defers -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acquisition.py::test_material_conflict_defers -q`, then `python -m pytest tests/test_acquisition.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acquisition.py tests/test_acquisition.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T036: material_conflict_defers"`. Include the actual test receipt before marking complete.

## T037: Handle origin updates according to pinned/current-required policy

Phase: P3. Depends on: T033, T009. Status: pending.

Files: `src/qjig/finalize.py`. Test: `tests/test_finalize.py::test_source_change_policy`.

Acceptance: A current-required run restarts once or defers and never mixes revisions.

1. Add `test_source_change_policy` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_finalize.py::test_source_change_policy -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_finalize.py::test_source_change_policy -q`, then `python -m pytest tests/test_finalize.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/finalize.py tests/test_finalize.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T037: source_change_policy"`. Include the actual test receipt before marking complete.

## T038: Expose the deterministic vertical slice through a real subprocess

Phase: P3. Depends on: T035, T036, T037. Status: pending.

Files: `src/qjig/cli.py`. Test: `tests/test_cli.py::test_fixture_end_to_end`.

Acceptance: Import ask trace and missing-exception deferral work with no provider calls.

1. Add `test_fixture_end_to_end` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_cli.py::test_fixture_end_to_end -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_cli.py::test_fixture_end_to_end -q`, then `python -m pytest tests/test_cli.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/cli.py tests/test_cli.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T038: fixture_end_to_end"`. Include the actual test receipt before marking complete.

## T039: Record call intent before a provider side effect

Phase: P4. Depends on: T038. Status: pending.

Files: `src/qjig/journal.py`. Test: `tests/test_journal.py::test_intent_before_call`.

Acceptance: A crash point retains pending intent with request/input identity.

1. Add `test_intent_before_call` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_journal.py::test_intent_before_call -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_journal.py::test_intent_before_call -q`, then `python -m pytest tests/test_journal.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/journal.py tests/test_journal.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T039: intent_before_call"`. Include the actual test receipt before marking complete.

## T040: Refuse blind retry of an uncertain paid call

Phase: P4. Depends on: T039. Status: pending.

Files: `src/qjig/journal.py`. Test: `tests/test_journal.py::test_uncertain_resume`.

Acceptance: Resume reports reconciliation required without a second invocation.

1. Add `test_uncertain_resume` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_journal.py::test_uncertain_resume -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_journal.py::test_uncertain_resume -q`, then `python -m pytest tests/test_journal.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/journal.py tests/test_journal.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T040: uncertain_resume"`. Include the actual test receipt before marking complete.

## T041: Enforce request-wide physical call reservations

Phase: P4. Depends on: T003, T039. Status: pending.

Files: `src/qjig/budgets.py`. Test: `tests/test_budgets.py::test_physical_call_cap`.

Acceptance: Planner repair stability probes final checks and fallback share the cap.

1. Add `test_physical_call_cap` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_budgets.py::test_physical_call_cap -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_budgets.py::test_physical_call_cap -q`, then `python -m pytest tests/test_budgets.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/budgets.py tests/test_budgets.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T041: physical_call_cap"`. Include the actual test receipt before marking complete.

## T042: Validate typed responses and preserve invalid HTTP-success output

Phase: P4. Depends on: T041. Status: pending.

Files: `src/qjig/providers.py`. Test: `tests/test_providers.py::test_malformed_is_unknown`.

Acceptance: Malformed output creates failure/unknown with a retained receipt.

1. Add `test_malformed_is_unknown` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_providers.py::test_malformed_is_unknown -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_providers.py::test_malformed_is_unknown -q`, then `python -m pytest tests/test_providers.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/providers.py tests/test_providers.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T042: malformed_is_unknown"`. Include the actual test receipt before marking complete.

## T043: Bind a fresh bounded planner response to request corpus and model

Phase: P4. Depends on: T042, T026. Status: pending.

Files: `src/qjig/planner.py`. Test: `tests/test_planner.py::test_fresh_plan_binding`.

Acceptance: Plan stores its origin and unresolved completeness caveat.

1. Add `test_fresh_plan_binding` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_planner.py::test_fresh_plan_binding -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_planner.py::test_fresh_plan_binding -q`, then `python -m pytest tests/test_planner.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/planner.py tests/test_planner.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T043: fresh_plan_binding"`. Include the actual test receipt before marking complete.

## T044: Translate semantic support with explicit unknown/conflict

Phase: P4. Depends on: T042, T025. Status: pending.

Files: `src/qjig/judge.py`. Test: `tests/test_judge.py::test_false_support_unknown`.

Acceptance: A false support score never alone proves the negative proposition.

1. Add `test_false_support_unknown` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_judge.py::test_false_support_unknown -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_judge.py::test_false_support_unknown -q`, then `python -m pytest tests/test_judge.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/judge.py tests/test_judge.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T044: false_support_unknown"`. Include the actual test receipt before marking complete.

## T045: Retain separate span-integrity and semantic-support assurance

Phase: P4. Depends on: T044, T006. Status: pending.

Files: `src/qjig/judge.py`. Test: `tests/test_judge.py::test_quote_not_semantic_proof`.

Acceptance: An exact wrong-entity quote cannot be marked independently supported.

1. Add `test_quote_not_semantic_proof` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_judge.py::test_quote_not_semantic_proof -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_judge.py::test_quote_not_semantic_proof -q`, then `python -m pytest tests/test_judge.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/judge.py tests/test_judge.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T045: quote_not_semantic_proof"`. Include the actual test receipt before marking complete.

## T046: Add opt-in real planner/judge smoke entrypoint and receipts

Phase: P4. Depends on: T043, T044. Status: pending.

Files: `src/qjig/providers.py`. Test: `tests/test_providers.py::test_real_adapter_smoke_contract`.

Acceptance: Successful real path and unavailable path are explicitly labeled with usage.

1. Add `test_real_adapter_smoke_contract` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_providers.py::test_real_adapter_smoke_contract -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_providers.py::test_real_adapter_smoke_contract -q`, then `python -m pytest tests/test_providers.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/providers.py tests/test_providers.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T046: real_adapter_smoke_contract"`. Include the actual test receipt before marking complete.

## T047: Validate optional local judge environment and input envelope

Phase: P4. Depends on: T041, T044. Status: pending.

Files: `src/qjig/local_judge.py`. Test: `tests/test_local_judge.py::test_oversize_no_truncation`.

Acceptance: Oversize input is rejected before inference and no automatic environment copy occurs.

1. Add `test_oversize_no_truncation` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_local_judge.py::test_oversize_no_truncation -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_local_judge.py::test_oversize_no_truncation -q`, then `python -m pytest tests/test_local_judge.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/local_judge.py tests/test_local_judge.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T047: oversize_no_truncation"`. Include the actual test receipt before marking complete.

## T048: Connect fresh decomposition to canonical retrieval and observation

Phase: P4. Depends on: T046, T033. Status: pending.

Files: `src/qjig/acquisition.py`. Test: `tests/test_acquisition.py::test_fresh_pipeline`.

Acceptance: Fresh run preserves each decisive evidence binding and unresolved gap.

1. Add `test_fresh_pipeline` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acquisition.py::test_fresh_pipeline -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acquisition.py::test_fresh_pipeline -q`, then `python -m pytest tests/test_acquisition.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acquisition.py tests/test_acquisition.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T048: fresh_pipeline"`. Include the actual test receipt before marking complete.

## T049: Add the selected Hy4 escalation path with explicit reason

Phase: P4. Depends on: T048, T041. Status: pending.

Files: `src/qjig/escalation.py`. Test: `tests/test_escalation.py::test_hy4_separate_outcome`.

Acceptance: Standalone failure/deferral remains saved and escalation is separately costed.

1. Add `test_hy4_separate_outcome` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_escalation.py::test_hy4_separate_outcome -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_escalation.py::test_hy4_separate_outcome -q`, then `python -m pytest tests/test_escalation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/escalation.py tests/test_escalation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T049: hy4_separate_outcome"`. Include the actual test receipt before marking complete.

## T050: Exercise source instructions and omitted-condition counterexamples

Phase: P4. Depends on: T048. Status: pending.

Files: `src/qjig/assurance.py`. Test: `tests/test_assurance.py::test_instruction_contamination_case`.

Acceptance: Known attacks are classified and no generic semantic-security claim is emitted.

1. Add `test_instruction_contamination_case` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_assurance.py::test_instruction_contamination_case -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_assurance.py::test_instruction_contamination_case -q`, then `python -m pytest tests/test_assurance.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/assurance.py tests/test_assurance.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T050: instruction_contamination_case"`. Include the actual test receipt before marking complete.

## T051: Verify recorded composition and evidence without new inference

Phase: P4. Depends on: T039, T048. Status: pending.

Files: `src/qjig/replay.py`. Test: `tests/test_replay.py::test_verify_saved_structure`.

Acceptance: Replay changes no outcomes and cannot certify model semantics.

1. Add `test_verify_saved_structure` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_replay.py::test_verify_saved_structure -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_replay.py::test_verify_saved_structure -q`, then `python -m pytest tests/test_replay.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/replay.py tests/test_replay.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T051: verify_saved_structure"`. Include the actual test receipt before marking complete.

## T052: Aggregate all actual work with explicit unobserved cost

Phase: P4. Depends on: T041, T049. Status: pending.

Files: `src/qjig/costs.py`. Test: `tests/test_costs.py::test_unknown_not_zero`.

Acceptance: Missing cost stays unknown and failed/escalated calls remain included.

1. Add `test_unknown_not_zero` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_costs.py::test_unknown_not_zero -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_costs.py::test_unknown_not_zero -q`, then `python -m pytest tests/test_costs.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/costs.py tests/test_costs.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T052: unknown_not_zero"`. Include the actual test receipt before marking complete.

## T053: Expose a thin local source/request/run API

Phase: P5. Depends on: T038, T051. Status: pending.

Files: `src/qjig/service.py`. Test: `tests/test_service.py::test_loopback_routes`.

Acceptance: Valid requests have stable envelopes and malformed requests fail explicitly.

1. Add `test_loopback_routes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_service.py::test_loopback_routes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_service.py::test_loopback_routes -q`, then `python -m pytest tests/test_service.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/service.py tests/test_service.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T053: loopback_routes"`. Include the actual test receipt before marking complete.

## T054: Build import and question views over the actual service

Phase: P5. Depends on: T053. Status: pending.

Files: `src/qjig/web.py`. Test: `tests/test_web.py::test_source_to_decision`.

Acceptance: Browser smoke imports a source and opens a real run result.

1. Add `test_source_to_decision` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_web.py::test_source_to_decision -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_web.py::test_source_to_decision -q`, then `python -m pytest tests/test_web.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/web.py tests/test_web.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T054: source_to_decision"`. Include the actual test receipt before marking complete.

## T055: Render decisive spans exclusions unknowns conflicts and caveats

Phase: P5. Depends on: T054. Status: pending.

Files: `src/qjig/web.py`. Test: `tests/test_web.py::test_inspect_unknowns`.

Acceptance: An unknown reason and its source need are visible without reading JSON.

1. Add `test_inspect_unknowns` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_web.py::test_inspect_unknowns -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_web.py::test_inspect_unknowns -q`, then `python -m pytest tests/test_web.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/web.py tests/test_web.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T055: inspect_unknowns"`. Include the actual test receipt before marking complete.

## T056: Create derived source interventions with exact parent links

Phase: P5. Depends on: T055, T037. Status: pending.

Files: `src/qjig/interventions.py`. Test: `tests/test_interventions.py::test_decisive_and_irrelevant_changes`.

Acceptance: Decisive change alters outcome or uncertainty while irrelevant change does not.

1. Add `test_decisive_and_irrelevant_changes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_interventions.py::test_decisive_and_irrelevant_changes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_interventions.py::test_decisive_and_irrelevant_changes -q`, then `python -m pytest tests/test_interventions.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/interventions.py tests/test_interventions.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T056: decisive_and_irrelevant_changes"`. Include the actual test receipt before marking complete.

## T057: Implement draft/reviewed program lifecycle under exact binding

Phase: P5. Depends on: T051, T056. Status: pending.

Files: `src/qjig/programs.py`. Test: `tests/test_programs.py::test_reviewed_exact_binding`.

Acceptance: A different request or source cannot inherit reviewed applicability.

1. Add `test_reviewed_exact_binding` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_programs.py::test_reviewed_exact_binding -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_programs.py::test_reviewed_exact_binding -q`, then `python -m pytest tests/test_programs.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/programs.py tests/test_programs.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T057: reviewed_exact_binding"`. Include the actual test receipt before marking complete.

## T058: Add two role-defined client adapters sharing canonical evidence

Phase: P5. Depends on: T053, T019. Status: pending.

Files: `src/qjig/agents.py`. Test: `tests/test_agents.py::test_two_roles_shared_evidence`.

Acceptance: Both clients retain source identities while ranking/context may differ.

1. Add `test_two_roles_shared_evidence` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_agents.py::test_two_roles_shared_evidence -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_agents.py::test_two_roles_shared_evidence -q`, then `python -m pytest tests/test_agents.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/agents.py tests/test_agents.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T058: two_roles_shared_evidence"`. Include the actual test receipt before marking complete.

## T059: Serialize catalog/claim writes with idempotency

Phase: P5. Depends on: T058, T009. Status: pending.

Files: `src/qjig/writer.py`. Test: `tests/test_writer.py::test_serialized_idempotent_writes`.

Acceptance: Concurrent identical client writes create one record and no lost revision.

1. Add `test_serialized_idempotent_writes` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_writer.py::test_serialized_idempotent_writes -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_writer.py::test_serialized_idempotent_writes -q`, then `python -m pytest tests/test_writer.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/writer.py tests/test_writer.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T059: serialized_idempotent_writes"`. Include the actual test receipt before marking complete.

## T060: Share an agent finding as an interpretation with evidence links

Phase: P5. Depends on: T058. Status: pending.

Files: `src/qjig/claims.py`. Test: `tests/test_claims.py::test_claim_is_not_source`.

Acceptance: A second client cannot receive that finding as original source text.

1. Add `test_claim_is_not_source` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_claims.py::test_claim_is_not_source -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_claims.py::test_claim_is_not_source -q`, then `python -m pytest tests/test_claims.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/claims.py tests/test_claims.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T060: claim_is_not_source"`. Include the actual test receipt before marking complete.

## T061: Export trace provenance configuration and resource records

Phase: P5. Depends on: T055, T052. Status: pending.

Files: `src/qjig/export.py`. Test: `tests/test_export.py::test_trace_export_roundtrip`.

Acceptance: Reimported export retains unknowns costs source bindings and role version.

1. Add `test_trace_export_roundtrip` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_export.py::test_trace_export_roundtrip -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_export.py::test_trace_export_roundtrip -q`, then `python -m pytest tests/test_export.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/export.py tests/test_export.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T061: trace_export_roundtrip"`. Include the actual test receipt before marking complete.

## T062: Verify full CLI/browser/two-client workflow and interruption

Phase: P5. Depends on: T056, T057, T059, T060, T061. Status: pending.

Files: `src/qjig/acceptance.py`. Test: `tests/test_acceptance.py::test_complete_local_workflow`.

Acceptance: Actual walkthrough receipt distinguishes real models from deterministic providers.

1. Add `test_complete_local_workflow` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_acceptance.py::test_complete_local_workflow -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_acceptance.py::test_complete_local_workflow -q`, then `python -m pytest tests/test_acceptance.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/acceptance.py tests/test_acceptance.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T062: complete_local_workflow"`. Include the actual test receipt before marking complete.

## T063: Keep reference labels and arm mappings outside retrievable sources

Phase: P6. Depends on: T061. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_exclude_gold_from_index`.

Acceptance: Index/provider input rejects evaluation-only files.

1. Add `test_exclude_gold_from_index` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_exclude_gold_from_index -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_exclude_gold_from_index -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T063: exclude_gold_from_index"`. Include the actual test receipt before marking complete.

## T064: Freeze development/pilot/holdout by related source families

Phase: P6. Depends on: T063. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_grouped_frozen_cases`.

Acceptance: Near duplicates and paired interventions cannot cross splits.

1. Add `test_grouped_frozen_cases` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_grouped_frozen_cases -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_grouped_frozen_cases -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T064: grouped_frozen_cases"`. Include the actual test receipt before marking complete.

## T065: Add direct small-model retrieval baseline with matched access

Phase: P6. Depends on: T064, T048. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_competent_direct_arm`.

Acceptance: Direct arm gets the same corpus and opportunity for bounded followup.

1. Add `test_competent_direct_arm` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_competent_direct_arm -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_competent_direct_arm -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T065: competent_direct_arm"`. Include the actual test receipt before marking complete.

## T066: Define direct full evidence retrieval-only decomposition-only and combined arms

Phase: P6. Depends on: T065. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_factorial_arms`.

Acceptance: Exactly named arms isolate catalog and decomposition contributions.

1. Add `test_factorial_arms` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_factorial_arms -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_factorial_arms -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T066: factorial_arms"`. Include the actual test receipt before marking complete.

## T067: Keep authored reuse and Hy4 fallback arms out of standalone result

Phase: P6. Depends on: T066, T049. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_separate_reuse_escalation`.

Acceptance: A fallback success cannot overwrite the original arm outcome.

1. Add `test_separate_reuse_escalation` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_separate_reuse_escalation -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_separate_reuse_escalation -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T067: separate_reuse_escalation"`. Include the actual test receipt before marking complete.

## T068: Score every assigned case and complete cost/latency ledger

Phase: P6. Depends on: T066, T052. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_all_assigned_denominator`.

Acceptance: Timeout invalid output unjustified deferral and unknown review stay visible.

1. Add `test_all_assigned_denominator` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_all_assigned_denominator -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_all_assigned_denominator -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T068: all_assigned_denominator"`. Include the actual test receipt before marking complete.

## T069: Support separate AI review and independently adjudicated references

Phase: P6. Depends on: T068. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_review_provenance`.

Acceptance: AI labels are explicitly unvalidated and reviewer provenance is retained.

1. Add `test_review_provenance` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_review_provenance -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_review_provenance -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T069: review_provenance"`. Include the actual test receipt before marking complete.

## T070: Report decisive missing and irrelevant changes as grouped pairs

Phase: P6. Depends on: T069. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_intervention_pair_report`.

Acceptance: Both answer and decisive evidence are checked with expectations.

1. Add `test_intervention_pair_report` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_intervention_pair_report -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_intervention_pair_report -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T070: intervention_pair_report"`. Include the actual test receipt before marking complete.

## T071: Run a bounded predeclared real-agent development pilot

Phase: P6. Depends on: T070. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_locked_pilot`.

Acceptance: No model or retrieval improvement claim exceeds measured outcomes.

1. Add `test_locked_pilot` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_locked_pilot -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_locked_pilot -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T071: locked_pilot"`. Include the actual test receipt before marking complete.

## T072: Generate retain revise or remove recommendation from prespecified criteria

Phase: P6. Depends on: T071. Status: pending.

Files: `src/qjig/evaluation.py`. Test: `tests/test_evaluation.py::test_benefit_decision`.

Acceptance: No-gain result can remove complexity and all negative results remain.

1. Add `test_benefit_decision` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_evaluation.py::test_benefit_decision -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_evaluation.py::test_benefit_decision -q`, then `python -m pytest tests/test_evaluation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/evaluation.py tests/test_evaluation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T072: benefit_decision"`. Include the actual test receipt before marking complete.

## T073: Verify clean install startup tests and documented commands

Phase: P6. Depends on: T062, T072. Status: pending.

Files: `src/qjig/release.py`. Test: `tests/test_release.py::test_clean_install_smoke`.

Acceptance: Fresh environment works without legacy data envs or absolute imports.

1. Add `test_clean_install_smoke` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_release.py::test_clean_install_smoke -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_release.py::test_clean_install_smoke -q`, then `python -m pytest tests/test_release.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/release.py tests/test_release.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T073: clean_install_smoke"`. Include the actual test receipt before marking complete.

## T074: Reconcile goal queue implementation docs and receipts

Phase: P6. Depends on: T073. Status: pending.

Files: `src/qjig/documentation.py`. Test: `tests/test_documentation.py::test_evidence_audit`.

Acceptance: Every completion claim links actual evidence and every open gate remains visible.

1. Add `test_evidence_audit` with the smallest input exposing that behavior; assert the acceptance above. Keep failures/unknowns explicit.
2. Run `python -m pytest tests/test_documentation.py::test_evidence_audit -q`. Expect an intended assertion failure (or missing initial contract); record why it is red.
3. Implement only this behavior in the listed files. Preserve previously passing contracts and source provenance.
4. Rerun `python -m pytest tests/test_documentation.py::test_evidence_audit -q`, then `python -m pytest tests/test_documentation.py -q`. Expect PASS. At the phase endpoint run `python -m pytest -q` for the new qJig suite only.
5. Commit only listed code, test, `PROGRESS.md` and task status: `git add src/qjig/documentation.py tests/test_documentation.py PROGRESS.md plan/tasks.json` then `git commit -m "Implement T074: evidence_audit"`. Include the actual test receipt before marking complete.

## First behavioral examples

Illustrative test contracts to make the early code shape concrete; these are design examples, not implemented API evidence.

```python
def test_preserve_raw_bytes(tmp_path):
    raw = b"Policy\r\nLimit: 2\r\n"
    revision = snapshot_bytes(raw, origin="project/policy.txt")
    assert revision.raw_sha256 == sha256(raw).hexdigest()
    assert load_raw(revision) == raw
    assert revision.normalization_version == "identity-v1"


def test_exception_stays_unknown():
    plan = OR(REF("ordinary"), REF("exception"))
    observations = {"ordinary": FALSE, "exception": UNKNOWN}
    assert reachable(plan, observations) == {False, True}
    assert is_material("exception", plan, observations)


def test_conflict_is_not_a_false_fact():
    assert combine_support("supported", "supported") == CONFLICT
    assert combine_support("unknown", "unknown") == UNKNOWN


def test_role_cannot_hide_exception():
    need = required_exception_need(role="developer", role_version="1")
    candidates = [current_exception(role_estimate=0.0), irrelevant_note(role_estimate=1.0)]
    packet = acquire(need, candidates)
    assert packet.includes_required_exception
    assert not packet.treats_no_hit_as_no_exception
```

For each task choose the public helper names when the contract is implemented, keep test intent, and update the plan if an interface name changes. Do not introduce all these interfaces during bootstrap.

## Review and release procedure

After each phase inspect diff and task/goal drift. At P3, review the deterministic trace before adding model work. At P4, inspect actual invalid responses and all usage before promoting providers. At P5, exercise the actual browser and two-client flow. At P6, accept negative or inconclusive findings; retain complexity only when supported outcomes, evidence quality, cost or diagnosis justify it.
