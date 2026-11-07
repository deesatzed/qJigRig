# qJig handoff — 2026-11-07 (for the next AI session)

Read this file first. It supersedes `HANDOFF_2026-11-06.md`, which describes the pre-implementation review state and is now stale (it says "no runtime exists"; that is no longer true).

## 0. What qJig is, in plain words

qJig is a Python tool that takes a question (for example "Can customer 42 get a refund 20 days after purchase?"), breaks it into specific yes/no sub-questions, retrieves the exact passages of versioned source documents needed for each, judges each with deterministic code or a model, combines the answers with three-valued logic, and returns either a decision with traceable evidence or an explicit **deferral** that names what is missing. It never treats "not found" as "does not exist", and never treats "model said so" as independent proof.

Repo: `/Volumes/WS4TB/qJig` (GitHub `deesatzed/qJigRig`, branch `main`). Python ≥3.11 (3.13.9 in use), standard library + pytest. Source: `src/qjig`, tests: `tests/`, queue: `plan/tasks.json` (74 tasks), exact per-task steps: `docs/plans/2026-11-06-qjig-build.md`.

## 1. OPEN ITEMS (read these first)

1. **Retrieval often finds nothing in live runs (unfixed, needs owner approval).** In two live runs through `run_fresh` (reports/t048-fresh-live.json), 3 of 8 predicates got `no_retrieval_hit` and 2 more got `judge_no_support`, so most predicates stayed UNKNOWN. Probable cause, NOT yet confirmed: `retrieval.tokenize`/BM25 does not stem ("refund" does not match "Refunds"), and the query is the whole predicate sentence. Fixing it changes the T017 retrieval contract, so propose it as its own small task (failing test first) and get the owner's OK. Confirm the cause first with a one-line check of `tokenize` and `bm25_candidates` on those strings before changing anything.
2. **Hy4 is unreliable as planner; fine as judge.** `tencent/hy4` is a reasoning model: it can spend its whole `max_tokens` on hidden reasoning and return no content (`finish_reason=length`). At 1500/800 tokens it failed planner and judge. At 6000 the judge worked (both sides) but the planner still exhausted 6000. A Hy4 judge call in `t048-fresh-live.json` (p4, run 1) also returned malformed output; not diagnosed.
3. **Fresh (model-planned) runs always defer — by design.** `run_fresh` opens a material obligation `ob-plan-coverage`; retrieval can list exception passages for review but never closes it. There is no reviewer mechanism to close it yet. Do not "fix" this by auto-closing.
4. **All quality evidence is one synthetic corpus and one question.** The refund sample document is authored by us. Live runs prove the provider path works; they say nothing about decision quality, reproducibility, or which model is better.
5. **14 commits are local only (origin/main is 14 behind).** Pushing needs fresh owner approval each time. An earlier approval covered only an earlier push.
6. **Stand-ins and synthetic data remain** (owner rule: label them and keep removal on the open list): `StandInTransport` ("STAND_IN: authored responses, not a model") in offline tests; authored plans; synthetic fixtures. No local model / `.venv-judge` was ever run (T047 only checks environment/size guards with a stand-in runner).
7. **`reports/verify_packet.py` fails by design** (it asserts all 74 tasks pending — a review baseline). No implementation-aware replacement exists. Do not mark tasks pending to make it pass.
8. Remaining pending tasks: **T049–T074** (26 tasks). See §6.

## 2. Verified status (all re-run this session)

- Full suite: **236 passed** (`python -m pytest -q`, ~2 s, offline, no network, no keys).
- Tasks complete: **48 of 74** (T001–T048). Pending: T049–T074.
- Phases: P1 (T001–T012 identity/spans/revisions/applicability), P2 (indexing/retrieval/packets/recovery/obligations), P3 (logic, plans, stopping, scheduler, acquisition, finalize, CLI `python -m qjig import|ask|trace` end to end via real subprocess, T038), P4 through T048 (journal, budgets, typed provider layer, planner, judge, local judge guards, real OpenRouter adapter, fresh pipeline).
- Live (real model) evidence, all with a SYNTHETIC refund corpus: `reports/t046-smoke-receipts.json`, `reports/t046-smoke-receipts-hy4-6000.json`, `reports/t048-fresh-live.json`. Key never appears in them (checked by exact-match grep: 0). Costs are the provider-reported figures (all small, well under $0.1 total).

## 3. Architecture (module map, `src/qjig/`)

contracts (Request, Budget) · sources (raw/text hashes, `SourceRevision`, id `rev1:`+sha256) · spans (code-point, end-exclusive) · legacy_quix / legacy_jig (explicit translation of two legacy contracts) · store (SQLite catalog v3; revisions immutable via triggers; reads re-verify) · applicability (per-source date and entity; unknown never = compatible) · indexing · retrieval (BM25; mandatory exception channels) · packets · recovery · obligations (open/evidence_found/unresolved/satisfied/skipped; `absence_established` always False) · logic (SUPPORTED/UNKNOWN support; TRUE/FALSE/UNKNOWN/CONFLICT outcome; CONFLICT outranks UNKNOWN, D016) · plans (parse/validate, origin authored|fresh) · stopping · exact (dated numeric rules) · scheduler · acquisition (`run_round`, `run_until_done`, **`run_fresh`**, `FreshRun`) · finalize (snapshot vs current_required) · cli · journal (append-only, intent before call, UncertainOutcome/reconcile) · budgets (journal-derived call/token/cost caps; unknown cost stays unknown) · providers (`call_typed`, `StandInTransport`, **`OpenRouterTransport`**, `load_env_value`, `RawResponse.note`) · planner (`request_fresh_plan`, `PlanBinding`; prompt now demands an exception predicate) · judge (paired YES/NO judging, quote must be an exact slice of an applicable retrieved span; assurance is never "independent") · local_judge.

Key invariants: unknown/conflict/provider-failure are distinct; a "not supported" judge answer is never a "no"; HTTP-200 malformed output is a failure with a kept receipt; every attempted provider call counts against the budget; a model-written plan is never known complete.

## 4. Models and credentials (owner decisions)

- Owner-chosen (2026-11-07), IDs given by the owner, all verified listed on OpenRouter's public `/models`: **planner** `deepseek/deepseek-v4.1-flash-1017` (valid plan 6/6 + later runs); **judge / escalation** `tencent/hy4` (needs ≥6000 `max_tokens`); further planner fallbacks in the owner's stated order if deepseek proves insufficient: `meta/muse-spark-open`, then `openai/gpt-6.1-terra` (not called yet). Do not substitute model IDs from memory; look up and ask the owner.
- Key: owner approved reading `Decision_Program_Codex_Handoff/.env` (`OPENROUTER_API_KEY`, `BASE_URL`). The key is capped upstream so the owner set no qJig spend budget; scripts still set their own ceilings. Never print the key; after any live run grep the receipts for it. `.env` files are git-ignored.
- AGENTS.md: live runs never belong in the offline suite; live scripts are opt-in under `scripts/`.

## 5. Prior troubleshooting (what went wrong and what was done)

| Problem | Cause | Resolution |
|---|---|---|
| Hy4 "failed" at T046 | HTTP 200 with `content: null`, `finish_reason=length`: reasoning used the whole token cap | Added `max_tokens` override to `request_fresh_plan` / `judge_predicate`; raised to 6000 (owner approved). Judge fixed; planner still exhausts 6000 (cause of runaway reasoning unknown, one prompt). |
| That failure was labeled `plan_invalid:executable_code_field` | Adapter passed the whole JSON envelope when content was null | Adapter now returns empty body + `RawResponse.note="no_message_content; finish_reason=..."`; typed layer reports `malformed_output`. |
| Plans never asked about exceptions | Planner sees only the question + corpus hash, not documents | Prompt now requires an exception/waiver predicate (2/2 live plans complied); plus the always-open `ob-plan-coverage` obligation. |
| My test helpers read the journal after it closed (`sqlite3.ProgrammingError: closed database`) | Reading `ledger.used_calls()` outside the `with journal` block | Capture counts inside the `with`. Happened in T044 and T048 tests; check for this first if you see that error. |
| A skipped predicate's open obligation blocked stopping (T035) | Stop check ran before skips were recorded | Added ledger status `skipped` (refused for entity/applicability kinds) and compute stop after skips. |
| T031 silent resolution of ambiguous applicable policy | — | Added `applicable_policy_ambiguous`. |
| Wrong expectations in my own tests (T017 "Refunds" vs "refund", T020, T041, T044) | My errors, fixed in tests not code | — Note T017 is the same stemming behavior behind open item 1. |
| A Bash command probing `.env` variable names was denied (before the owner approved `.env` access) | Permission classifier | Not retried; owner later approved reading the key. |
| `reports/verify_packet.py` fails | Asserts all tasks pending | By design; see open item 7. |

Owner rule: if the same failure survives two fix attempts, stop patching, list plausible causes, add logging, and record in `ERROR_LOG.md` (none created yet; nothing has hit that threshold).

## 6. Next steps (in order)

1. **Ask the owner** whether to (a) fix retrieval (stemming and/or a shorter keyword query than the full sentence) as a new small task, and (b) push the 14 local commits. Do neither without a yes.
2. If approved, retrieval fix: failing test first (the `no_retrieval_hit` strings from `reports/t048-fresh-live.json` p1/p3/p4 are the real counterexamples), minimal change, rerun full suite (236 must stay green or be consciously updated), then rerun `scripts/smoke_t048.py` (live, ~2 min for 2 runs; run in background) and record before/after.
3. **T049** Hy4 escalation path (`src/qjig/escalation.py`, test `test_hy4_separate_outcome`): standalone failure/deferral stays saved; escalation costed separately. Then **T050** assurance/attack cases (instruction contamination in sources, omitted-condition counterexamples; never emit a generic "semantically secure" claim), **T051** replay (verify recorded structure without new inference), **T052** cost aggregation (unknown stays unknown, failed/escalated calls included).
4. P5 (T053–T062, browser/two-client use) and P6 (T063–T074, isolated benefit comparisons) per `plan/tasks.json`. Starting them out of order needs a recorded plan change.
5. Build an implementation-aware replacement for `verify_packet.py` when convenient.

## 7. How to work here (rules that apply)

- Read `AGENTS.md`, `GOAL.md`, `STANDARDS.md`, `DECISIONS.md` (D012–D020 are the implementation decisions), `PROGRESS.md`, `TASK_QUEUE.md` before coding. Owner global rules: lead reports with open items, give exact test counts, no time/cost estimates, no mocks/synthetic data without approval and labeling, owner chooses model versions, pause only for irreversible/outward actions or input only the owner can give.
- Per task: smallest failing test → observe the intended failure → minimal implementation → focused + nearest + full suite → one scoped commit → record evidence in `plan/tasks.json` and `PROGRESS.md`, decisions in `DECISIONS.md`. Commit messages end with the Co-Authored-By line for the model in use.
- Helper used previously (session scratchpad, may be gone): a script that runs focused/file/full tests, writes the evidence string into `plan/tasks.json` and `PROGRESS.md`, and commits. Recreate it if needed; do not skip the evidence.
- Tests that call a provider must use `StandInTransport` or the injected fake HTTP layer and say so in the docstring. Live scripts: `scripts/smoke_t046.py`, `scripts/smoke_t048.py` (usage in each docstring; both take the env file path; long runs go to background).
- Nested `sources/quixer` and `Decision_Program_Codex_Handoff` are checkpointed review inputs; do not edit them, and do not run root pytest expecting those suites (pytest is scoped to `tests/`).

## 8. Orientation commands

```sh
cd /Volumes/WS4TB/qJig
git status --short; git log --oneline -8; git rev-list --count origin/main..HEAD   # expect clean, 14
python -m pytest -q                                                               # expect 236 passed
python - <<'P'
import json,collections;d=json.load(open('plan/tasks.json'))['tasks'];print(collections.Counter(t['status'] for t in d))
P
```
