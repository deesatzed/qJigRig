# Browser unknown and conflict states

On 2026-11-07, headless Chrome opened a loopback qJig service containing two synthetic, overlapping refund-policy sources: one said 14 days and the other 30 days. An authored numeric question about day 20 was run twice.

A search term with no matching entry produced a deferred result displaying an unknown observation. A query matching both policies produced a deferred conflict with the reason `multiple_applicable_policies`; the result displayed both the 14-day and 30-day passages. At a 390 × 844 viewport, the conflict view had no horizontal overflow.

The reproducible optional check is `tests/test_source_browser.py::test_browser_distinguishes_unknown_from_source_conflict`; it used the locally installed Chrome and Playwright in ignored verification storage. All three source-browser checks and the existing web tests passed together (10 passed). No hosted model call occurred.

This is a deterministic authored-control demonstration, not proof of general conflict detection, source authority, semantic correctness, screen-reader usability or full browser acceptance. It complements the separate source-error and two-browser-context checks; it does not establish hosted-provider behavior.
