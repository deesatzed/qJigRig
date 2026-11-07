# Two browser clients: local source-change verification

On 2026-11-07, two isolated Chrome browser contexts opened the same loopback qJig service backed by a temporary catalog. All content was synthetic. The reader used a 1280 × 900 viewport; the editor used 390 × 844.

The reader ran an authored numeric control asking about a refund after 20 days. Against a source permitting refunds within 14 days, it displayed `Decided · no` and the 14-day evidence. The editor independently opened that source and used the source intervention form to change 14 to 30. The reader's existing result was marked `Source changed · rerun`, while its original 14-day evidence remained visible as the prior result. Rerunning displayed `Decided · yes` with the 30-day evidence. The editor viewport had no horizontal overflow.

The optional reproducible check is `tests/test_source_browser.py::test_two_browser_clients_show_cross_client_source_change`; it was run with locally installed Chrome and Playwright in ignored verification storage. The two source-browser checks and existing web tests passed together (9 passed). No model call occurred.

This demonstrates one authored-control path across two isolated browser contexts, not separate browser processes, authenticated users, independent semantic evaluation, full accessibility, all concurrent edits or the full browser/two-client acceptance workflow. Source-state polling is not instantaneous and does not monitor external files.
