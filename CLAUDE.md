# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bonfire: a SQL-analysis agent (LangChain v1 `create_agent` over a Postgres/Olist database) that uses Jev (TypeSafe System One) to decide whether a query result correctly answers the user's question.

The design has two separate layers:

- **Before the SQL runs: deterministic code only.** Postgres guarantees no writes (the `bonfire_agent` role has SELECT only). `sqlcheck` (sqlglot) inside `run_sql` rejects anything that isn't a single read statement, plus explicit cartesian products and joins without a predicate. `statement_timeout` cuts expensive queries. There is no Jev gate before execution.
- **After the SQL runs: one Jev request per attempt**, in a `wrap_tool_call` middleware. Jev sees the question, the SQL, and the result. It answers a `Choice` (`answer | retry | ask_user`) plus one `Noul` per known Olist trap (e.g. counting `customer_id` instead of `customer_unique_id`, summing after a join that duplicates rows). A positive trap is the reason passed to the LLM for its rewrite. Code, not Jev, caps the number of attempts.

It is **not** a benchmark: nothing compares Jev against an LLM or against other configurations. Evaluation (Phase 6) measures whether this one application works: false positives first, then trap detection, accuracy, latency, cost.

**`plan.md` is the source of truth** (in Spanish): phases 0–8, exit criteria, target file layout, and the official doc links for each phase. Read the section for the current phase before starting work.

## Current state

Phase 0 (Jev connection) done. Phase 1 in progress: Postgres with Olist runs in Docker (`docker-compose.yml`, `init.sql`) and the `bonfire_agent` permissions are verified; `sqlcheck` and `run_sql` are next. Besides `docker-compose.yml` and `init.sql`, the only code is `main.py`, an SDK example that calls `TypeSafeClient().system_one(state=..., questions={...})` with the three primitives `Choice`, `Score`, `Noul`. The `src/`, `eval/`, `tests/` tree from `plan.md` exists as stubs: each file holds only a docstring naming its phase and job. `src/middleware/` is deliberately missing; it gets created only after Phase 3 is committed and hashed.

## Commands

Uses `uv` with Python 3.12 (`.python-version`).

```
uv sync                 # install deps from uv.lock
uv run python main.py   # SDK example (needs TYPESAFE_API_KEY in .env, see .env.example)

docker desktop start    # start the Docker engine (Windows, Docker Desktop CLI)
docker compose up -d --wait   # Postgres + Olist; healthy only after init.sql finishes loading
docker compose down -v  # delete the database; next `up` reruns init.sql from scratch
```

The Olist CSVs live in `data/olist/` (git-ignored). Download: `curl -L -o olist.zip https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce` and unzip there. License: CC BY-NC-SA 4.0. `init.sql` runs only when the data volume is empty, so after changing it run `docker compose down -v`. Passwords and the host port (`BONFIRE_DB_PORT`, default 5432) come from `.env`.

No tests, linter, or build config yet. Per the plan, tests will live in `tests/` (`test_sqlcheck.py`, `test_policy.py`, `test_review_middleware.py`) and must run without network access.

## Rules from the plan that apply every time

- **Fast-moving dependencies:** `langchain` v1 (`create_react_agent` is gone; legacy code lives in `langchain-classic`) and `typesafe-sdk`/Jev (released 2026-09-15). Before writing code against either, read the live docs linked in that phase of `plan.md` (Context7 or https://docs.langchain.com/llms.txt). Don't write signatures from memory.
- If the docs contradict the plan, the docs win. Log the discrepancy with a date in `NOTES.md`.
- Pin exact versions in `uv.lock`. Don't upgrade in the middle of a phase.
- Record the **model version returned by the API** on every run. `jev-latest` is a moving alias.
- Order is strict: commit and hash the test cases (Phase 3, tag `eval-frozen`) **before** any file exists in `src/middleware/`.
- Phases marked 🚦 are hard gates. Don't move forward without meeting the exit criterion.
- **Security is deterministic, never Jev.** Postgres permissions, `sqlcheck`, and the timeout are the only safety layers. Jev judges whether an allowed read query correctly answers the question. Never frame Jev as a barrier, a defense, or "protecting the database".
- **Parseable problems belong to `sqlcheck`, not Jev.** Explicit cartesian products, missing join predicates, and non-SELECT statements are rejected in `run_sql` and covered by `tests/test_sqlcheck.py`. Don't add Jev questions or thresholds for them. Jev's questions and Phase 3 cases target SQL that runs fine but answers wrong.
- Don't write probes, notebooks, or benchmarks to check whether Jev or the TypeSafe API works. `main.py` already confirmed it. Jev's behavior and performance inside the app are observed through Langfuse traces (Phase 7).
- **That rule does not cover unit tests of our own logic. Those are required.** `policy.py` and the review middleware get tests with mocked Jev responses and no network. Examples: a trap at 0.9 → `retry` with that reason; a trap at 0.1 and `next_step = answer` → `answer`; attempt cap → stop; SQL error or zero rows → `retry` without calling Jev.
- Never add a comparison against an LLM judge, a baseline configuration, or "Jev vs X". The owner ruled it out on 2026-09-24.
- `policy.py` is pure code with no network calls. Thresholds live there, not in the middleware.
- Jev semantics that shape the policy code (confirmed at https://docs.typesafe.ai/api on 2026-09-24): `Noul` has no `confidence` field (the probability is the answer); `Score` can land between levels; each question is evaluated independently and can't see the others' answers.
- Don't put secrets in tool arguments or agent state. They get sent to TypeSafe. Up to `MAX_ROWS_TO_JEV` result rows also go to TypeSafe.
- In eval results, false positives go first. A reviewer that sends correct results back for a retry makes the agent slow and expensive.
