# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bonfire: a SQL-analysis agent (LangChain v1 `create_agent` over a Postgres/Olist database) that uses Jev (TypeSafe System One) to decide whether a query result correctly answers the user's question.

The design has two separate layers:

- **Before the SQL runs: deterministic code only.** Postgres guarantees no writes (the `bonfire_agent` role has SELECT only). `sqlcheck` (sqlglot) inside `run_sql` rejects anything that isn't a single read statement, plus explicit cartesian products and joins without a predicate. `statement_timeout` cuts expensive queries. There is no Jev gate before execution.
- **After the SQL runs: one Jev request per attempt**, in a `wrap_tool_call` middleware. Jev sees the question, the SQL, and the result. It answers a `Choice` (`answer | retry | ask_user`) plus one `Noul` per known Olist trap (e.g. counting `customer_id` instead of `customer_unique_id`, summing after a join that duplicates rows). A positive trap is the reason passed to the LLM for its rewrite. Code, not Jev, caps the number of attempts.

It is **not** a benchmark: nothing compares Jev against an LLM or against other configurations. Evaluation (Phase 6) measures whether this one application works: false positives first, then trap detection, accuracy, latency, cost.

**`plan.md` is the source of truth** (in Spanish): phases 0–8, exit criteria, target file layout, and the official doc links for each phase. Read the section for the current phase before starting work. Where the owner changed the plan, `plan.md` carries a dated note and `NOTES.md` the details.

## Current state (2026-10-09)

| Phase | State |
|---|---|
| 0, 1, 2 | done |
| 3 | reduced by the owner (2026-10-07) to a manual review of the generator's SQL; paused |
| 4 | done (2026-10-08): the Jev rubric and call, tried by hand on the agent's real SQL |
| 5 | code written and pushed on 2026-10-08 in 8 commits (`0114cc6`…`eb76ba8`); **not run yet**: no `pytest`, no real question through the loop |
| 6, 7, 8 | not started; `src/api.py` (Phase 7) is the only stub left |

### What exists

Database and safety (Phase 1):
- `docker-compose.yml` + `init.sql`: Postgres 18.6 with Olist; `bonfire_agent` can only SELECT, with `default_transaction_read_only` and `statement_timeout = 10s` set on the role.
- `src/sqlcheck.py`: `check_sql(sql) -> SqlCheck`, a sqlglot allow-list (rules R1–R5 in the file).
- `src/agent/tools.py`: the `run_sql` tool (`response_format="content_and_artifact"`): text for the LLM, a `SqlResult` artifact for code. One new connection per call, `read_only`, 10s timeout, `fetchmany(MAX_ROWS + 1)`, Postgres errors returned as text, connection errors raised.

The agent (Phase 2, extended in Phase 5):
- `src/agent/build.py`: `build_agent(model=None, review=True)` with `create_agent`: the generator model, the `run_sql` tool, the system prompt, and `middleware=[ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="end"), ReviewMiddleware()]`. `review=False` drops `ReviewMiddleware` and gives the Phase 2 agent; `tests/test_agent.py` uses it. So `src.main` and `run_eval` now run **with Jev**. No values are hardcoded there:
  - `bonfire.toml` (repo root, versioned): `[agent] model` (`openai:gpt-5-nano`, the cheapest OpenAI model, chosen by the owner; `BONFIRE_MODEL` in `.env` overrides it), `max_model_calls = 8`, `system_prompt` (path). Loaded by `src/config.py` (`tomllib` + Pydantic with `extra="forbid"`, so a misspelled key fails at startup).
  - `prompts/sql_agent.md`: the generator's system prompt, with the schema structure only (no Olist trap hints: those are for Jev). `render_prompt` fills `$max_rows` from `tools.MAX_ROWS` with `string.Template` (a literal `$` is `$$`) and raises on a missing variable. `prompt_sha` fingerprints the rendered prompt; `run_eval` records it with the config. Since 2026-10-01 it says to always answer in English (gpt-5-nano answered in Portuguese).
  - The `run_sql` tool description stays as its docstring in `tools.py` (owner's call), so `MAX_ROWS` and `STATEMENT_TIMEOUT` stay there too, next to the docstring that states the 200-row limit.
- `src/main.py`: `ask(question)` CLI.
- `src/models.py`: `SqlCheck`, `SqlResult`, `ReviewVerdict` (Phase 4), `NextAction` (Phase 5).

Jev (Phases 4 and 5):
- `src/questions/review.py`, everything that talks to Jev: `SCHEMA_NOTES` (Olist facts, sent in the state: facts go in the state, criteria in the questions), `QUESTIONS` (`next_step` Choice + one Noul per trap: `customer_id_not_unique`, `join_fanout`, `wrong_grain`, `wrong_date_column`, `undelivered_as_sales`), `build_review_state(question, sql, result)` (at most `MAX_ROWS_TO_JEV = 20` rows, values through `json.dumps(default=str)`), `_client()` (one cached `TypeSafeClient`, SDK default model `jev-latest`) and `review(...) -> ReviewVerdict` (one `system_one` call; records the returned model, tokens and latency). Its `__main__` is the owner's manual check: `python -m src.questions.review eval/results/traps.json t01` reruns the agent's SQL for that question and prints Jev's verdict. The plan's `src/jev/client.py` was deleted: the SDK already never retries a 400 (`NOTES.md`, 2026-10-07).
- `src/policy.py`, pure code: `review_decision(result, verdict, attempt)` checks, in order, the attempt cap (`MAX_ATTEMPTS = 4` → `answer`), SQL error and zero rows (`retry` without Jev; `needs_jev()`), any trap at or above `PITFALL_MIN = 0.5` (`retry`, reasons from `TRAP_REASONS`, English text for the LLM), then `next_step`. One threshold for all traps instead of the plan's per-trap dict; `NEXT_STEP_MIN_CONFIDENCE` not implemented.
- `src/middleware/review.py`: `ReviewMiddleware`. `wrap_tool_call` runs `run_sql`, calls `review()` only when `needs_jev`, appends `Reviewer: <kind>. <reason>` to the `ToolMessage` and returns a `Command` updating `review_attempts` (reducer `add`) and `review_kind` (reducer "latest") in an extended `ReviewState`. `wrap_model_call`, after `answer` or `ask_user`, calls the model with `request.override(tool_choice="none")`. Hooks verified against the installed langchain 1.4.2 / langgraph 1.2.12 (`NOTES.md`, 2026-10-08). Two parallel `run_sql` calls share an attempt number (`ponytail:` comment).

Evaluation (Phase 2, reduced Phase 3):
- `eval/run_eval.py`: runs the agent over a questions file, grades the last successful query result, and writes traces (turns, SQL, returned model ID, tokens, latency). It grades against `reference_sql` only (`acceptable_sql` is not read yet) and doesn't record whether Jev was on or how many retries happened. `eval/grading.py`: result-set comparison (Phase 6 rules).
- `eval/questions_dev.jsonl`: 10 normal questions, reviewed by the owner on 2026-10-06. `d08` ("distinct perfumaria products sold") counts delivered orders only since that day.
- `eval/questions_traps.jsonl`: 10 questions, two per trap, with a `bait` field naming the trap (informative only).
- `eval/README.md`: how to run both files, the reference conventions, and the 5 traps with the numbers measured in psql on 2026-10-06. Those numbers live only there: the psql queries were one-off checks, nothing saved their output.
- `eval/results/pilot.json` (2026-09-28, generator only, 9/10 against the old `d08` reference) and `eval/results/traps.json` (2026-10-07, generator only, 4/10). Both predate Jev in the agent.

Observability and manual review:
- Langfuse Cloud, moved up from Phase 7 by the owner (2026-09-29): `build_agent()` attaches `langfuse.langchain.CallbackHandler` via `with_config` only when `LANGFUSE_PUBLIC_KEY` is set. No key means no callback and no network, which the tests rely on. CLI and eval scripts call `get_client().flush()` before exiting. The Jev call itself isn't traced (no LangChain callback goes through it); the decision shows up in the trace as the `Reviewer:` line of each `ToolMessage`.
- `cases/`: 22 questions the owner runs **by hand** with `src.main` and annotates in Langfuse (paraphrases of dev questions, unanswerable, ambiguous, direct prompt injection), each with a `watch` note; `cases/README.md` explains a round. **Not** an automated suite: one was built on 2026-09-29 and removed on 2026-10-01 at the owner's request. Don't reintroduce automated scoring without asking. Paraphrases come only from dev questions. Deferred by the owner on 2026-10-06, not dropped: a first round started (it produced the answer-in-English change) but wasn't finished.

### Reference conventions (owner's calls, in `eval/README.md`)
- Sales, items sold, revenue: only `order_status = 'delivered'` (2026-10-06). Questions about orders in general count every status.
- Revenue questions name their measure (item prices, prices plus freight, or payments); if not, the question is ambiguous (2026-10-07).
- A period with no event named means the purchase date. Customers are `customer_unique_id`. Counting reviews means distinct `review_id`.
- An error outside the 5 traps is `retry` with empty pitfalls; a new trap only if the error repeats (2026-10-07).
- Don't change the grading of a question after seeing a result without the owner's call.

### What the runs showed
- The generator (`gpt-5-nano-2025-08-07`) makes the same mistakes every time: `customer_id_not_unique` 4/4 in a removed 22-question run (2026-10-06, recoverable from commit `4db5522`) and 2/2 in `traps.json`; `undelivered_as_sales` when the question says "sales revenue"; counting review rows; never `join_fanout` or `wrong_date_column`. `t08` read "approved in January" as `order_status = 'approved'` (count 0), which no trap covers.
- Jev by hand on the 10 trap questions (2026-10-08, `jev-1.13.0`, ~1,300 input / 135 output tokens, 0.4–1 s per call): with "a trap at or above 0.5 beats `answer`", 9/10 right and no false positives. That took rewording `undelivered_as_sales` to judge the question's scope (commit `4453775`): it had flagged payment totals on `t03`/`t04` (0.82, 0.77 → 0.06, 0.04). Correct answers kept every trap below 0.2; caught errors scored 0.69–0.97. `t06` was caught only by its trap (`next_step` said `answer`); `t09` had `next_step` nearly tied (0.47/0.50). `t08` slips through. `customer_id_not_unique` and `wrong_grain` overlap on `t01`/`t02`, with no effect on the decision.

### Next steps
1. Owner: `uv run pytest` (the Phase 5 tests haven't run).
2. Owner: `uv run python -m src.main "How many customers are there?"` and read the trace: expect `Reviewer: retry` on `customer_id`, a rewrite with `customer_unique_id`, then a text answer. This also checks whether gpt-5-nano honors `tool_choice="none"` with tool calls in the history (unverified).
3. Owner: rerun the trap questions with Jev into a new file (`eval/results/traps_jev.json`) and compare with `traps.json`.
4. Phase 5 exit criterion (`plan.md`): every run ends in text, never more than `MAX_ATTEMPTS`, no tools after `answer`/`ask_user`, the retry reason reaches the model, tests pass. Then Phase 6.

Open decisions for the owner: fix the traps in `prompts/sql_agent.md` (fewer generator mistakes, less for Jev to catch) or leave them for Jev; whether `t08` becomes a sixth trap if it repeats. Open technical points (`NOTES.md`): Jev errors propagate (no unreviewed fallback).

### Learning material for the owner
- **Obsidian vault** at `C:\Users\pablo\Desktop\obsidian_notes\Bonfire`: 172 notes in Spanish, one per file, function, library and concept, plus 8 walkthroughs. Built on 2026-10-05 (commit `7c65abf`), synced on 2026-10-08 to `eb76ba8` (Phases 3–5). Start at `00 Empezá acá`. It doesn't update itself: when code changes, offer to update the affected notes and regenerate their code blocks from the real files.
- **Course** "Bonfire desde cero": https://claude.ai/artifact/JLRB69158cxeLH5vGSTZrh (27 modules, published 2026-09-30). Outdated since then: modules 20–21, M24 and M25 still describe the removed automated suite, and nothing covers Phases 3–5.
- Offered and not requested: a `--case ID --round NAME` option in `src/main.py` to tag Langfuse traces per round.

## Commands

Uses `uv` with Python 3.12 (`.python-version`).

```
uv sync                 # install deps from uv.lock
uv run python main.py   # SDK example (needs TYPESAFE_API_KEY in .env, see .env.example)

docker desktop start    # start the Docker engine (Windows, Docker Desktop CLI)
docker compose up -d --wait   # Postgres + Olist in the background; returns once healthy (after init.sql loads)
docker compose ps       # the db service should say "healthy"
docker compose down -v  # delete the database; next `up` reruns init.sql from scratch
docker compose exec db psql -U bonfire_admin -d olist   # psql as admin: no sqlcheck, no timeout; run SELECTs only

uv run pytest           # all tests, no network or database needed
uv run pytest tests/test_sqlcheck.py -k cartesian   # one file, filtered by name
uv run python -m src.agent.tools   # Phase 1 exit criterion against the real database
uv run python -m src.main "How many orders are there?"   # ask the agent, with Jev (needs OPENAI_API_KEY, TYPESAFE_API_KEY and the database)
uv run python -m eval.run_eval eval/questions_dev.jsonl eval/results/dev.json      # the 10 normal questions
uv run python -m eval.run_eval eval/questions_traps.jsonl eval/results/traps_jev.json   # the 10 trap questions (don't overwrite traps.json)
uv run python -m src.questions.review eval/results/traps.json t01   # Jev's verdict on the agent's SQL for one question
```

Imports are rooted at the repo (`from src.sqlcheck import check_sql`); `pyproject.toml` sets `pythonpath = ["."]` for pytest. DSNs use `127.0.0.1`, not `localhost` (on Windows `localhost` tries IPv6 first and takes 10s to connect). A `ConnectionTimeout` from `run_eval` or `src.main` means the database isn't up. If Docker Desktop hangs on start: kill the `com.docker.*` processes, run `wsl --shutdown`, then `docker desktop start`. The owner uses Git Bash: paste with Shift+Insert, and pasted text can carry invisible characters before the command.

The Olist CSVs live in `data/olist/` (git-ignored). Download: `curl -L -o olist.zip https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce` and unzip there. License: CC BY-NC-SA 4.0. `init.sql` runs only when the data volume is empty, so after changing it run `docker compose down -v`. Passwords and the host port (`BONFIRE_DB_PORT`, default 5432) come from `.env`, as do `OPENAI_API_KEY` (the generator), `TYPESAFE_API_KEY` (Jev) and the optional `BONFIRE_MODEL`.

Tests live in `tests/` and must run without network access: `test_sqlcheck.py`, `test_tools.py` (a fake psycopg connection), `test_agent.py` (a scripted fake chat model plus the fake connection; builds the agent with `review=False`), `test_grading.py`, `test_config.py` (`bonfire.toml` and prompt rendering), `test_review.py` (state building and verdict mapping, Jev replaced by a fake client via `monkeypatch` on `_client`), `test_policy.py` (every branch of `review_decision`, verdicts built by hand with `verdict(...)`) and `test_review_middleware.py` (`create_agent` with only `ReviewMiddleware`, `jev.review` monkeypatched, a `RecordingModel` that records each `tool_choice`). To test agent wiring, subclass `GenericFakeChatModel` with a no-op `bind_tools` and yield a new `AIMessage` per turn (LangGraph merges messages by id, so reusing one object collapses the turns). The fakes don't obey `tool_choice`: tests check that the middleware asks for `"none"`, not that a model obeys. No linter or build config.

## Working with the owner

- This is a study project: the owner wants to understand every piece. Explain in Spanish (rioplatense), with the why, and propose a design before coding; wait for approval.
- **Keep each step at the size asked.** On 2026-10-07 the owner rejected a Phase 3 build-out (22 harvest questions, 60 labeled Jev cases, a freeze script) as complexity. When `plan.md` asks for something big, propose the minimal version and ask before scaling up. Don't build tests or datasets for a component before it exists.
- When the owner is lost, explain from the beginning and say where things live (which file holds which result, what reads it). Don't stack follow-up questions; if a decision can be defaulted from what the owner already approved, default it and say so.
- The owner runs tests, the agent and the eval scripts, and pastes the output. Don't run them unless asked; say plainly what was not run. Reading result files in `eval/results/` and checking that code imports is fine.
- When implementing: separate, focused commits (the owner asks for as many as make sense), then push directly to `main`.
- Prefer manual, inspectable workflows over automation (see `cases/`). Ask before adding automated evaluation.

## Rules from the plan that apply every time

- **Fast-moving dependencies:** `langchain` v1 (`create_react_agent` is gone; legacy code lives in `langchain-classic`) and `typesafe-sdk`/Jev (released 2026-09-15). Before writing code against either, read the live docs linked in that phase of `plan.md` (Context7, https://docs.langchain.com/llms.txt, https://docs.typesafe.ai/llms.txt) and the installed package source. Don't write signatures from memory.
- If the docs contradict the plan, the docs win. Log the discrepancy with a date in `NOTES.md`.
- Pin exact versions in `uv.lock`. Don't upgrade in the middle of a phase.
- Record the **model version returned by the API** on every run. `jev-latest` is a moving alias; `ReviewVerdict.model_id` keeps the returned one. For the generator, `eval/run_eval.py` reads it from `AIMessage.response_metadata["model_name"]`.
- Read message text with `AIMessage.text`, not `.content`: newer OpenAI models return content as a list of blocks (Responses API).
- `gpt-5-nano` is a reasoning model: reasoning tokens are billed as output, so it spent ~11× the output tokens of `gpt-6-sol` on the pilot (still ~8× cheaper overall). When estimating cost, use measured tokens from `eval/results/`, not list prices alone. It also follows prompt instructions less reliably (it answered one English question in Portuguese).
- Model choice is the owner's call and cost-sensitive: don't switch the default generator to a pricier model without asking.
- Test cases for Jev get written now that Jev exists, small and by hand (owner, 2026-10-07). The plan's freeze-before-middleware gate (`eval-frozen`) and the 40/20/40 split are dropped.
- Phases marked 🚦 are hard gates. Don't move forward without meeting the exit criterion.
- **Security is deterministic, never Jev.** Postgres permissions, `sqlcheck`, and the timeout are the only safety layers. Jev judges whether an allowed read query correctly answers the question. Never frame Jev as a barrier, a defense, or "protecting the database".
- **Every `sqlcheck` rule has a test in both directions**: SQL it must reject and legitimate SQL it must let through. A false positive (a valid query rejected) makes the agent useless. When adding a rule, add both kinds of cases.
- **Parseable problems belong to `sqlcheck`, not Jev.** Explicit cartesian products, missing join predicates, and non-SELECT statements are rejected in `run_sql` and covered by `tests/test_sqlcheck.py`. Don't add Jev questions or thresholds for them. Jev's questions target SQL that runs fine but answers wrong.
- Don't write probes, notebooks, or benchmarks to check whether Jev or the TypeSafe API works. `main.py` already confirmed it. The `__main__` of `src/questions/review.py` is the owner-approved way to look at Jev's verdict on the agent's real SQL; inside the app, Jev's behavior is observed through Langfuse traces.
- **That rule does not cover unit tests of our own logic. Those are required.** `policy.py` and the review middleware have tests with mocked Jev responses and no network.
- Never add a comparison against an LLM judge, a baseline configuration, or "Jev vs X". The owner ruled it out on 2026-09-24.
- `policy.py` is pure code with no network calls. Thresholds live there, not in the middleware.
- Jev semantics that shape the code (API docs 2026-09-24, SDK 0.7.0 source and docs 2026-10-07): `Noul` has no `confidence` field (the probability is the answer; 0.5 means "doesn't know"); `Choice` returns `choice`, `probabilities` and `confidence`; `Score` can land between levels; each question is evaluated independently and can't see the others' answers. The SDK retries 408, 429 and 5xx, never a 400 (`max_tokens_exceeded` included); default timeout 10 s.
- Jev answers literally what the question says. When it gives a false positive, reword the question first (as with `undelivered_as_sales`), don't move the threshold. Each trap in `QUESTIONS` needs its reason in `TRAP_REASONS`; `test_policy.py` checks the keys match.
- Don't put secrets in tool arguments or agent state. They get sent to TypeSafe, along with the question, the SQL and up to `MAX_ROWS_TO_JEV` result rows.
- In eval results, false positives go first. A reviewer that sends correct results back for a retry makes the agent slow and expensive.
