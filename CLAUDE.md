# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bonfire: a SQL-analysis agent (LangChain v1 `create_agent` over a Postgres/Olist database) whose control plane runs on Jev (TypeSafe System One). Two middlewares make the decisions: a risk gate (`before_tool`: ALLOW / BLOCK / `interrupt()`) and a loop controller (`after_tool`: stop or take another turn). The goal is a measured comparison of three configurations: no middleware, LLM middleware, Jev middleware.

**`plan.md` is the source of truth** (in Spanish): phases 0–9, exit criteria, target file layout, and the official doc links for each phase. Read the section for the current phase before starting work.

## Current state

Early Phase 0 (probe). The only code is `main.py`, an SDK example that calls `TypeSafeClient().system_one(state=..., questions={...})` with the three primitives `Choice`, `Score`, `Noul`. The `src/`, `eval/`, `tests/` tree from `plan.md` exists as stubs: each file holds only a docstring naming its phase and job. `src/middleware/` is deliberately missing; it gets created only after Phase 3 is committed and hashed.

## Commands

Uses `uv` with Python 3.12 (`.python-version`).

```
uv sync                 # install deps from uv.lock
uv run python main.py   # run the Jev probe (needs TYPESAFE_API_KEY in .env, see .env.example)
```

No tests, linter, or build config yet. Per the plan, tests will live in `tests/` (`test_policy.py`, `test_sqlcheck.py`) and must run without network access.

## Rules from the plan that apply every time

- **Fast-moving dependencies:** `langchain` v1 (`create_react_agent` is gone; legacy code lives in `langchain-classic`), the experimental `langchain-typesafe` middleware, and `typesafe-sdk`/Jev (released 2026-09-15). Before writing code against any of them, read the live docs linked in that phase of `plan.md` (Context7 or https://docs.langchain.com/llms.txt). Don't write signatures from memory.
- If the docs contradict the plan, the docs win. Log the discrepancy with a date in `NOTES.md`.
- Pin exact versions in `uv.lock`. Don't upgrade in the middle of a phase.
- Record the **model version returned by the API** on every run. `jev-latest` is a moving alias.
- Order is strict: run the no-middleware baseline (Phase 2) and commit and hash the eval datasets (Phase 3) **before** any file exists in `src/middleware/`.
- Phases marked 🚦 are hard gates. Don't move forward without meeting the exit criterion.
- Jev is the second line of defense. The first is Postgres permissions: the `bonfire_agent` user has SELECT only. Never frame it as "Jev protects the database".
- `policy.py` is pure code with no network calls. Thresholds live there, not in the middleware.
- `sqlglot` runs **alongside** Jev, not instead of it. Always log disagreements between the two.
- Jev semantics that shape the policy code (confirm against the docs): `Noul` has no `confidence` field (the probability is the answer); `Score` can land between levels; each question is evaluated independently.
- Don't put secrets in tool arguments or agent state. They get sent to TypeSafe.
- In eval results, false positives go first. A paranoid gate makes the agent useless.
