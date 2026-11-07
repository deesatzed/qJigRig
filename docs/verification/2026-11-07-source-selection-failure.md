# Source selection failure: local browser verification

In headless Google Chrome on 2026-11-07, a loopback qJig service exposed two synthetic source revisions. The test focused the first source button and pressed Enter, then confirmed its evidence was visible. It intercepted the second source request with a simulated HTTP 503. Before the repair, the page displayed the error while leaving the first source's evidence visible. After the repair, the prior preview was empty and hidden, and the 390 × 844 viewport had no horizontal overflow.

The optional browser regression is `tests/test_source_browser.py::test_failed_source_selection_hides_prior_preview`. The focused invocation used Playwright from ignored local verification storage and the installed Chrome executable, and passed together with the local web tests (8 passed). The ordinary offline suite skips this browser test when the optional Playwright/browser configuration is absent.

This exercises one failure path and a small keyboard and viewport check; it does not establish full accessibility, all source-selection races, provider behavior, source authority, or the full browser acceptance workflow. All content was synthetic and no hosted model call was made.
