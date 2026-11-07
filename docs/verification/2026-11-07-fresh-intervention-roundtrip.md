# Synthetic fresh intervention round trip

The opt-in browser path in `tests/test_fresh_service.py::test_configured_service_runs_fresh_pipeline_and_preserves_deferral` uses a real local service and Chrome, two role-defined Python clients, and explicit synthetic provider responses. A reviewer and a builder independently run fresh planning over the same revision; their reviews retain the respective role and version. The browser runs a further reviewer request and shows the original passage. The builder applies a parent-linked intervention changing 14 days to 30. The browser marks the previous result stale, reruns, and shows the new passage in a deferred result. The new archive's evidence names the child revision. After service restart, the original archive still replays with the original passage and can be downloaded and structurally replayed.

The browser portion was run with the existing isolated Playwright environment and local Chrome:

```sh
QJIG_CHROMIUM_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' .local/verification/clean-install-20261107/bin/python -m pytest tests/test_fresh_service.py tests/test_agents.py -q
```

Result: 5 passed. The browser path is skipped when no Chrome path is set. All provider outputs and source content are synthetic. This walkthrough does not establish hosted execution, semantic accuracy, independent review, interruption recovery, accessibility conformance, or completion of the full T062 acceptance gate.
