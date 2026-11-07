# Browser foundation verification, 2026-11-07

A local service was started with `PYTHONPATH=src python -m qjig serve --catalog .local/verification/browser-catalog.sqlite --port 0`. In headless Chromium at 1280 × 900, a synthetic refund-policy source was added through the browser and opened from the source list. An authored numeric control for 20 days returned `Decided · no` and displayed the 14-day source passage. Repeating it with an entity outside the source metadata returned `Deferred`, `only_inapplicable_candidates`, and `Excluded: inapplicable`.

At 390 × 844 the document width was 390 pixels and the deferred result remained available. These observations exercise the local deterministic path and a responsive-width check; they are not accessibility certification, independent outcome evaluation, hosted-model verification, complete browser acceptance, or evidence that all policy exceptions were found. The source and questions were synthetic. No hosted call was made.
