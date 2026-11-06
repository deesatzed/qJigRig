# Shared Knowledge Research Slice Implementation Plan

> **For Codex:** Use the `executing-plans` skill to implement this plan task by task.

**Goal:** Build and evaluate a small evidence-linked catalog for implementation and review agents, with topic, decision, and role-aware retrieval as separately measurable variants.

**Architecture:** A single-writer local catalog stores versioned sources, sections, agent records and their links in SQLite. Deterministic text search provides the baseline; topic links, a decision interface, and role annotations are independently switchable. The first experiment uses recorded or test decision responses; a real provider integration requires its own selection and live evaluation.

**Tech Stack:** Python 3.11+, standard-library SQLite and argparse; pytest for tests; Markdown and plain-text inputs first. PDF extraction is a subsequent adapter, not a prerequisite for the baseline. This stack is a reversible pilot assumption.

---

## Working rules

Read the agreed `docs/plans/2026-10-29-shared-knowledge-design.md` before implementation. Work in an isolated worktree. Keep each variant's corpus, queries and budget identical. Never report a synthetic fixture or mock response as measured model or agent performance. Do not modify the three neighboring repositories. Record decisions and progress in project control files if introduced. Write a focused failing test, run it, implement, and rerun it for each task; commit scoped changes after verification.

### Task 1: Establish package and storage contract

**Files:** Create `pyproject.toml`, `src/quix_knowledge/__init__.py`, `src/quix_knowledge/store.py`, `tests/test_store.py`.

1. Add a test that creates a temporary SQLite catalog, inserts a source with a stable ID, path and SHA-256 revision, closes and reopens it, and verifies the same values. Run `python -m pytest tests/test_store.py -v`; expect failure because the package does not exist.
2. Implement `open_catalog(path)` and explicit schema versioning. Add source, section, agent-record, evidence-link, topic-link, role-annotation and decision-receipt tables with foreign keys. Keep source text and revision distinct; constrain lifecycle and type values. Enable SQLite foreign keys on every connection.
3. Add tests for invalid references, duplicate identities and revision preservation. Run `python -m pytest tests/test_store.py -v`; expect pass. Commit these files.

### Task 2: Ingest text with source anchors

**Files:** Create `src/quix_knowledge/ingest.py`, `tests/test_ingest.py`.

1. Test Markdown headings and plain text: preserve the raw source and create anchored sections; a file without headings yields a clearly labeled generated fallback section. Empty or unreadable text yields a recorded explicit failure. Run `python -m pytest tests/test_ingest.py -v`; expect failure.
2. Implement deterministic heading extraction and line anchors. Store a SHA-256 revision, source path and section ranges. Document the fallback as generated; never fabricate page references or assert that a heading is semantically correct.
3. Test a source revision change flags dependent links and scores stale while preserving old records. Run the focused tests and commit. PDF/printed ToC parsing remains deferred to a separately tested adapter.

### Task 3: Evidence, topics and role annotations

**Files:** Create `src/quix_knowledge/records.py`, `tests/test_records.py`.

1. Test that an agent finding records its producer and supporting section IDs, while an unsupported claim remains explicitly unsupported. Verify a test result references recorded output and a superseded record remains inspectable. Run `python -m pytest tests/test_records.py -v`; expect failure.
2. Implement APIs for agent records, many-to-many topic links and role annotations. Topic links record origin and proposed/accepted/rejected state. Role annotations record role ID/version, score, method, model/version if applicable, and source revision; missing or stale scores stay unknown.
3. Test multi-topic membership, source and role revision staleness, evidence links, and rejection of nonexistent anchors. Run focused tests and commit.

### Task 4: Baseline retrieval and role-aware ranking

**Files:** Create `src/quix_knowledge/retrieve.py`, `tests/test_retrieve.py`.

1. With a fixed small corpus, test task-text retrieval, topic-aware candidate expansion and role-aware ordering. Verify low role usefulness does not filter an otherwise relevant item and missing scores do not prevent retrieval. Run `python -m pytest tests/test_retrieve.py -v`; expect failure.
2. Implement a deterministic lexical section baseline and named variants `baseline`, `topic`, `decision`, `role`. Use the same candidate sources and context budget for comparisons; return identifiers, anchors, provenance, status and score components. Role adjustment must be bounded, with task relevance primary.
3. Test unsupported and stale records are visibly labeled, unrelated candidates are handled deterministically, and results preserve evidence links. Run focused tests and commit.

### Task 5: Typed decision boundary and fallback

**Files:** Create `src/quix_knowledge/decisions.py`, `tests/test_decisions.py`.

1. Define a protocol accepting bounded state and named questions and returning typed outcomes plus model/version and usage metadata. Test valid supported/unclear/unsuitable judgments, malformed output, timeout and provider failure using a deterministic fake. Run `python -m pytest tests/test_decisions.py -v`; expect failure.
2. Implement validation and receipts, with `unknown` for failure. Wire topic and relevance judgments through the interface. Unknown or uncertain retrieval decisions broaden or fall back to baseline; failed indexing decisions never silently become accepted links.
3. Test fallbacks retain relevant baseline results and receipts distinguish fake, unknown and actual providers. Run focused tests and commit. Do not claim a real decision model was exercised by these tests.

### Task 6: Experiment contract and reproducible evaluation

**Files:** Create `src/quix_knowledge/evaluate.py`, `tests/test_evaluate.py`, `docs/evaluation.md`, `examples/fixture/`.

1. Test recall, relevance, stale/unsupported counts, missing-source and unanswerable reporting on a tiny explicitly synthetic fixture. Verify all variants use identical query IDs and corpus revision. Run `python -m pytest tests/test_evaluate.py -v`; expect failure.
2. Implement a run manifest containing corpus revision, independently produced labels and provenance, train/threshold versus held-out split, role version, configuration, provider/model/version, context budget, latency and actual available cost/usage. Produce machine-readable per-query and aggregate results without inventing missing values.
3. Document how an independent reviewer identifies relevant evidence and evaluates agent outcomes; include missing-ToC, broad-topic, stale, conflicting and unsupported cases. Run `python -m pytest tests/ -q`; expect pass. Commit the harness and clearly labeled fixture. Results from this fixture verify calculation only.

### Task 7: Provider and real-corpus checkpoint

**Files:** Create `docs/provider-evaluation.md` and, only after provider selection, a separate adapter and focused tests.

1. Verify current OpenRouter Decisions API, model availability, pricing, context and option limits from official documentation. Compare a candidate local JevEdge0 adapter and hosted alternatives against the same labeled decisions; document actual environment and dependencies. Do not assume local weights or an API key are available.
2. Obtain or designate a non-sensitive real project corpus and independently labeled implementation/review tasks. Partition labels before threshold tuning. Run all four variants; record actual cost, latency, failure rate, retrieval quality and limitations.
3. Report whether decision and role variants improve the baseline with the available evidence. If credentials, weights, labels or a real corpus are absent, report the corresponding experiment as blocked, not passed. Any HITMCockpit integration gets a separate design and approval.

## Completion checks

Run `python -m pytest tests/ -q` and `git diff --check`; report their actual results. Distinguish implemented behavior, test fixtures, provider observations and independent real-task evaluation. The research slice is not validated as beneficial to a swarm until the held-out comparison and any agent outcome review have actually been performed.
