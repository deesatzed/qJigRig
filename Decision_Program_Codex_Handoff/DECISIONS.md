# Decisions

- Use Python standard library and loopback HTTP for the first runnable slice. Separate storage and runtime from presentation; no dependency installation is required for this slice.
- Keep source snapshots and run records in local append-only JSON files, identified by random IDs and source hashes. Records are not a substitute for a full provenance or benchmark database.
- Send source text to OpenRouter only after per-run consent. Use a fixed OpenRouter HTTPS endpoint and reject redirects.
- Label supplied-evidence frontier and small-model judge accurately; neither implies broad research nor the required local judge.
