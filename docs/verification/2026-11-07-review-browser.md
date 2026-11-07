# Saved review browser walkthrough

On 2026-11-07, `scripts/verify_review_browser.py` created a non-sensitive synthetic source and ran one stand-in plan review through the separate review stage. After closing and reopening the catalog through the loopback service, headless Chromium displayed the synthetic, unvalidated review and its reason. Keyboard focus and Enter opened the exact bound source. At a 390-pixel viewport the document did not overflow horizontally.

The optional script uses Playwright and an existing Chromium executable; the local invocation set `PYTHONPATH=src:.local/verification/playwright-lib` and `QJIG_CHROMIUM_PATH` to the locally installed browser. The script reported `status: passed`, `synthetic_review_visible: true`, `keyboard_source_inspection: true`, and zero hosted calls.

This checks a read-only review inspection path. It does not demonstrate hosted review, automatic fresh runs from the browser, review freshness, program activation, full accessibility, source authority or semantic quality. The review is an unvalidated snapshot and the source control opens its bound revision; it is not a current-source applicability check.
