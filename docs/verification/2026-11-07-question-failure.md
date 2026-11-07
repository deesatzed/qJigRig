# Browser question failure verification

On 2026-11-07, Chrome ran a synthetic authored refund rule against a 14-day source and displayed `Decided · no` for a 20-day request. The test then changed the question and injected HTTP 503 for its new request. Before the repair, the previous decision and passage remained in the current result area despite the failed request. After the repair, the page displayed `Run failed` and no previous passage in the active result; the earlier run remained in the saved-run list.

The optional browser regression is `tests/test_source_browser.py::test_failed_question_does_not_present_previous_result`. The source-browser and web checks passed together (11 tests) using local Chrome and Playwright. The separate saved-run walkthrough also passed after the change, including a local intervention, service restart, reopened historical run, and structurally verified download.

These are synthetic authored-control checks, not full browser acceptance, screen-reader verification, independent outcome evidence or hosted-provider behavior. No hosted model call was made.
