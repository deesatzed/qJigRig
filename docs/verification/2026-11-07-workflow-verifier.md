# Offline workflow verifier

`scripts/verify_workflow.py --offline` runs separate local synthetic checks for an authored browser journey with intervention, restart and verified export; review inspection and stale-source intervention; two browser contexts; two role clients; interruption without retry; and exact review binding. It returns JSON with each check's result and a nonzero exit code if the workflow is incomplete. A skipped browser test is incomplete, not a pass. Set `QJIG_CHROMIUM_PATH` to an available Chrome/Chromium executable and make Playwright available in the Python environment.

On 2026-11-07 the command ran with local Chrome and Playwright: all six checks passed, but the command correctly returned exit code 1 and `complete_fresh_browser_journey_unverified`. These are separate synthetic checks, not a single end-to-end fresh browser journey, hosted-provider evidence, accessibility certification, model-quality evidence or production readiness. The offline verifier makes no provider calls. Its explicit unmet gate must be replaced by actual end-to-end evidence before it can return success.

A subsequent run added `tests/test_workflow_browser.py::test_complete_synthetic_fresh_browser_journey` as a required check. It requires Playwright and `QJIG_CHROMIUM_PATH`, so the verifier cannot pass by silently omitting the browser portion. The journey uses a synthetic fresh backend and two role clients, displays a deferred result and unvalidated review in a 390-pixel browser, applies an intervention, reruns, restarts the service, and reopens and verifies downloaded archives and receipts. With local Chrome all seven checks passed and the offline verifier exited 0. Interruption recovery remains a separate synthetic check; this does not prove hosted execution, independent outcome accuracy, complete accessibility, or the full project acceptance gate.

## 2026-11-08 rerun

At commit `48e7555`, the default `python scripts/verify_workflow.py --offline` exited 1: the default Python environment lacked Playwright, so two browser scripts failed and two browser tests skipped; the role-client, interruption and binding checks passed. A configured rerun exited 0 with all seven checks passing:

```sh
QJIG_CHROMIUM_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' PYTHONPATH=src:.local/verification/playwright-lib python scripts/verify_workflow.py --offline
```

The authored and synthetic fresh browser journeys, review/intervention browser check, two browser clients, two role clients, process interruption and review binding all reported passed. These are local synthetic checks; they do not establish hosted-provider behavior, independent semantic quality, full accessibility, or completion of every T062 product requirement. The default command still needs a Python environment with Playwright and the documented browser configuration to reproduce this result.
