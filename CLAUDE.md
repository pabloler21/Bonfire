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

Phases 0, 1 and 2 done. Phase 3 is now the owner's manual review of how the generator writes SQL (owner's call, 2026-10-07, `NOTES.md`): 10 normal questions plus 10 trap questions, run with `run_eval`, each trace read in Langfuse, the prompt adjusted by hand. **No test cases for Jev until Jev exists**: the 40/20/40 split and the `eval-frozen` gate in `plan.md` are dropped. Keep it small; the owner rejected the extra machinery (harvest, labeled cases, freeze script) as complexity.

Since 2026-09-29 the repo gained Langfuse tracing, `bonfire.toml` + `prompts/`, and `cases/`. The owner verified them on 2026-10-06: `pytest` passes and `src.main` answers against the database.

What exists:
- `docker-compose.yml` + `init.sql`: Postgres 18.6 with Olist; `bonfire_agent` can only SELECT.
- `src/sqlcheck.py`: `check_sql(sql) -> SqlCheck`, a sqlglot allow-list (rules R1–R5 in the file).
- `src/agent/tools.py`: the `run_sql` tool (`response_format="content_and_artifact"`): text for the LLM, `SqlResult` artifact for the Phase 5 middleware. One new connection per call, `read_only`, 10s timeout, `fetchmany(MAX_ROWS + 1)`, Postgres errors returned as text, connection errors raised.
- `src/models.py`: `SqlCheck`, `SqlResult`.
- `src/agent/build.py`: `build_agent(model=None)` with `create_agent`: the generator model, the `run_sql` tool, the system prompt, and `ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="end")` as the loop safety net. No values are hardcoded there:
  - `bonfire.toml` (repo root, versioned): `[agent] model` (`openai:gpt-5-nano`, the cheapest OpenAI model, chosen by the owner; `BONFIRE_MODEL` in `.env` overrides it), `max_model_calls = 8`, `system_prompt` (path). Loaded by `src/config.py` (`tomllib` + Pydantic with `extra="forbid"`, so a misspelled key fails at startup).
  - `prompts/sql_agent.md`: the generator's system prompt, with the schema structure only (no Olist trap hints: those are for Jev). `render_prompt` fills `$max_rows` from `tools.MAX_ROWS` with `string.Template` (a literal `$` is `$$`) and raises on a missing variable. `prompt_sha` fingerprints the rendered prompt; `run_eval` records it with the config.
  - The `run_sql` tool description stays as its docstring in `tools.py` (owner's call), so `MAX_ROWS` and `STATEMENT_TIMEOUT` stay there too, next to the docstring that states the 200-row limit.
- `src/main.py`: `ask(question)` CLI.
- `eval/run_eval.py`: runs the agent over a questions file, grades the last successful query result, and writes traces (turns, SQL, returned model ID, tokens, latency). `eval/grading.py`: result-set comparison (Phase 6 rules). `eval/questions_dev.jsonl`: 10 dev questions, reviewed by the owner on 2026-10-06. `eval/results/pilot.json`: the Phase 2 pilot with `gpt-5-nano-2025-08-07`, 9/10 correct against the old `d08` reference. The owner then made `d08` "delivered orders only" (2026-10-06, `NOTES.md`), the reading the pilot used, so `pilot.json` predates that reference. `eval/questions_traps.jsonl`: 10 questions, two per Olist trap, with a `bait` field naming the trap. `eval/README.md`: how to run both files, the reference conventions (sales = delivered orders, etc.) and the 5 traps with the numbers measured on the database. `run_eval` grades against `reference_sql` only (`acceptable_sql` is not read yet).
- `main.py`: the TypeSafe SDK example from Phase 0.
- Langfuse Cloud, moved up from Phase 7 by the owner (2026-09-29, `NOTES.md`): `build_agent()` attaches `langfuse.langchain.CallbackHandler` via `with_config` only when `LANGFUSE_PUBLIC_KEY` is set. No key means no callback and no network, which the tests rely on. CLI and eval scripts call `get_client().flush()` before exiting.
- `cases/`: questions the owner runs **by hand**, one at a time, with `src.main`, then reads and annotates the trace in Langfuse (Annotate button, a Score Config). `cases.jsonl` has 22 cases (paraphrases of dev questions, unanswerable, ambiguous, direct prompt injection), each with a `watch` note; `cases/README.md` explains a round. This is error analysis before Phase 3, **not** an automated suite: an automated behavior suite (`run_behavior`, evaluators, `langfuse.run_experiment`) was built on 2026-09-29 and removed on 2026-10-01 at the owner's request. Don't reintroduce automated scoring for these cases without asking. Paraphrases come only from dev questions.

The owner ran `questions_traps.jsonl` on 2026-10-07 (`eval/results/traps.json`, 4/10, same mistakes as the earlier 22-question run). Paused by the owner: reading the traces in Langfuse and deciding whether to fix the traps in `prompts/sql_agent.md` or leave them for Jev. `questions_dev.jsonl` hasn't been rerun.

Phase 4 (started 2026-10-07, owner approved the design): `src/questions/review.py` holds everything Jev-related: `SCHEMA_NOTES` (Olist facts, sent in the state), `QUESTIONS` (`next_step` Choice + one Noul per trap), `build_review_state(question, sql, result)` (at most `MAX_ROWS_TO_JEV = 20` rows, values passed through `json.dumps(default=str)`), and `review(...) -> ReviewVerdict` (one `system_one` call, SDK default model `jev-latest`, records the returned model, tokens and latency). `src/jev/client.py` was deleted (`NOTES.md`). Not run against Jev yet. Next: the owner tries it on the agent's real SQL, one at a time: `uv run python -m src.questions.review eval/results/traps.json t01` (needs the database and `TYPESAFE_API_KEY`), comparing Jev's verdict with the agent's OK/BAD. Then Phase 5 (`policy.py`, middleware). Don't change the grading of a question after seeing a result without the owner's call.

Already known from a 22-question run on 2026-10-06 (since removed, recoverable from commit 4db5522): `gpt-5-nano` fell for `customer_id_not_unique` 4/4, `undelivered_as_sales` 2/4, reviews-as-rows 1/1, never for `join_fanout` or `wrong_date_column`, and once read "approved in January" as `order_status = 'approved'` (count 0).

Deferred by the owner (2026-10-06), not dropped: the manual rounds with `cases/`. Create a Score Config in Langfuse (e.g. categorical `veredicto`: correcta / incorrecta / dudosa), run each case with `src.main`, annotate each trace, write down failure patterns, review `cases/cases.jsonl` (Claude drafted it). A first round was started (it produced the answer-in-English change, 7c65abf) but not finished.

Optional, offered and not yet requested: a `--case ID --round NAME` option in `src/main.py` that tags traces via `langfuse.propagate_attributes(session_id=..., tags=[case id, kind, model], metadata={"watch": ...})` so a round can be filtered in Langfuse; and updating the course artifact (below).

Course for the owner: https://claude.ai/artifact/JLRB69158cxeLH5vGSTZrh ("Bonfire desde cero", 27 modules, hand-drawn SVG diagrams, full source appendix generated from the repo). Published 2026-09-30, so modules 20–21, the replication recipe (M24) and the code appendix (M25) still describe the removed automated suite instead of `cases/`.

The rest of the `src/`, `eval/`, `tests/` tree from `plan.md` is still stubs: each file holds only a docstring naming its phase and job. `src/middleware/` is deliberately missing; it gets created in Phase 5.

## Commands

Uses `uv` with Python 3.12 (`.python-version`).

```
uv sync                 # install deps from uv.lock
uv run python main.py   # SDK example (needs TYPESAFE_API_KEY in .env, see .env.example)

docker desktop start    # start the Docker engine (Windows, Docker Desktop CLI)
docker compose up -d --wait   # Postgres + Olist; healthy only after init.sql finishes loading
docker compose down -v  # delete the database; next `up` reruns init.sql from scratch

uv run pytest           # all tests, no network or database needed
uv run pytest tests/test_sqlcheck.py -k cartesian   # one file, filtered by name
uv run python -m src.agent.tools   # Phase 1 exit criterion against the real database
uv run python -m src.main "How many orders are there?"   # ask the agent (needs OPENAI_API_KEY and the database)
uv run python -m eval.run_eval eval/questions_dev.jsonl eval/results/pilot.json   # rerun the pilot (~US$0.005 with gpt-5-nano)
```

Imports are rooted at the repo (`from src.sqlcheck import check_sql`); `pyproject.toml` sets `pythonpath = ["."]` for pytest. DSNs use `127.0.0.1`, not `localhost` (on Windows `localhost` tries IPv6 first and takes 10s to connect). If Docker Desktop hangs on start: kill the `com.docker.*` processes, run `wsl --shutdown`, then `docker desktop start`.

The Olist CSVs live in `data/olist/` (git-ignored). Download: `curl -L -o olist.zip https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce` and unzip there. License: CC BY-NC-SA 4.0. `init.sql` runs only when the data volume is empty, so after changing it run `docker compose down -v`. Passwords and the host port (`BONFIRE_DB_PORT`, default 5432) come from `.env`, as do `OPENAI_API_KEY` (the generator) and the optional `BONFIRE_MODEL`.

Tests live in `tests/` and must run without network access: `test_sqlcheck.py`, `test_tools.py` (a fake psycopg connection), `test_agent.py` (a scripted fake chat model plus the fake connection), `test_grading.py`, `test_config.py` (`bonfire.toml` and prompt rendering) and `test_review.py` (state building and verdict mapping, Jev replaced by a fake client via `monkeypatch` on `_client`) exist; `test_policy.py` and `test_review_middleware.py` come in Phase 5. To test agent wiring, subclass `GenericFakeChatModel` with a no-op `bind_tools` and yield a new `AIMessage` per turn (LangGraph merges messages by id, so reusing one object collapses the turns). No linter or build config.

## Working with the owner

- This is a study project: the owner wants to understand every piece. Explain in Spanish (rioplatense), with the why, and propose a design before coding; wait for approval.
- The owner runs tests, the agent and the eval scripts. Don't run them unless asked; say plainly what was not run.
- When implementing: separate, focused commits, then push directly to `main`.
- Prefer manual, inspectable workflows over automation (see `cases/`). Ask before adding automated evaluation.

## Rules from the plan that apply every time

- **Fast-moving dependencies:** `langchain` v1 (`create_react_agent` is gone; legacy code lives in `langchain-classic`) and `typesafe-sdk`/Jev (released 2026-09-15). Before writing code against either, read the live docs linked in that phase of `plan.md` (Context7 or https://docs.langchain.com/llms.txt). Don't write signatures from memory.
- If the docs contradict the plan, the docs win. Log the discrepancy with a date in `NOTES.md`.
- Pin exact versions in `uv.lock`. Don't upgrade in the middle of a phase.
- Record the **model version returned by the API** on every run. `jev-latest` is a moving alias. For the generator, `eval/run_eval.py` reads it from `AIMessage.response_metadata["model_name"]`.
- Read message text with `AIMessage.text`, not `.content`: newer OpenAI models return content as a list of blocks (Responses API).
- `gpt-5-nano` is a reasoning model: reasoning tokens are billed as output, so it spent ~11× the output tokens of `gpt-6-sol` on the pilot (still ~8× cheaper overall). When estimating cost, use measured tokens from `eval/results/`, not list prices alone. It also follows prompt instructions less reliably (it answered one English question in Portuguese).
- Model choice is the owner's call and cost-sensitive: don't switch the default generator to a pricier model without asking.
- Test cases for Jev get written once Jev exists, not before (owner, 2026-10-07). The plan's freeze-before-middleware gate (`eval-frozen`) is dropped.
- Phases marked 🚦 are hard gates. Don't move forward without meeting the exit criterion.
- **Security is deterministic, never Jev.** Postgres permissions, `sqlcheck`, and the timeout are the only safety layers. Jev judges whether an allowed read query correctly answers the question. Never frame Jev as a barrier, a defense, or "protecting the database".
- **Every `sqlcheck` rule has a test in both directions**: SQL it must reject and legitimate SQL it must let through. A false positive (a valid query rejected) makes the agent useless. When adding a rule, add both kinds of cases.
- **Parseable problems belong to `sqlcheck`, not Jev.** Explicit cartesian products, missing join predicates, and non-SELECT statements are rejected in `run_sql` and covered by `tests/test_sqlcheck.py`. Don't add Jev questions or thresholds for them. Jev's questions and Phase 3 cases target SQL that runs fine but answers wrong.
- Don't write probes, notebooks, or benchmarks to check whether Jev or the TypeSafe API works. `main.py` already confirmed it. Jev's behavior and performance inside the app are observed through Langfuse traces (Phase 7).
- **That rule does not cover unit tests of our own logic. Those are required.** `policy.py` and the review middleware get tests with mocked Jev responses and no network. Examples: a trap at 0.9 → `retry` with that reason; a trap at 0.1 and `next_step = answer` → `answer`; attempt cap → stop; SQL error or zero rows → `retry` without calling Jev.
- Never add a comparison against an LLM judge, a baseline configuration, or "Jev vs X". The owner ruled it out on 2026-09-24.
- `policy.py` is pure code with no network calls. Thresholds live there, not in the middleware.
- Jev semantics that shape the policy code (confirmed at https://docs.typesafe.ai/api on 2026-09-24): `Noul` has no `confidence` field (the probability is the answer); `Score` can land between levels; each question is evaluated independently and can't see the others' answers.
- Don't put secrets in tool arguments or agent state. They get sent to TypeSafe. Up to `MAX_ROWS_TO_JEV` result rows also go to TypeSafe.
- In eval results, false positives go first. A reviewer that sends correct results back for a retry makes the agent slow and expensive.
