# Bonfire — Plan review: errors and fixes

**Review date:** 2026-09-22
**Applies to:** `plan.md`, revision of 2026-09-19
**Audience:** Claude Code, before writing or changing any code.

> **Superseded in part (2026-09-24).** The owner changed the design after this review: there is no Jev gate before execution, no human-approval pause, and no checkpointer. Jev makes one decision after `run_sql` runs. Items about the risk gate, `interrupt()`, `bonfire_state`, `EXPLAIN`/`COST_MAX` and the LLM-judge comparison (B2, B4, B5 in part, C1, C2, D1, M5, M6, O1) no longer apply as written. `plan.md` is the source of truth.

---

## How to read this document

Each item has an ID, a severity, the place in `plan.md` it affects, the problem, the fix, and a verification status.

| Severity | Meaning |
|---|---|
| BLOCKER | Breaks the implementation or invalidates the results. Fix before any code. |
| CONTRADICTION | Two parts of the plan say incompatible things. |
| METHOD | The evaluation would produce numbers that can't be trusted. |
| DESIGN | Works, but a piece is forced, missing or unsafe. |
| MINOR | Wording, placement or small omissions. |
| OPEN DECISION | Not an error. The owner decides. Do not apply. |

Verification status:

- **Verified**: checked against the linked source on 2026-09-22.
- **To verify**: reasoned from general knowledge or a secondary source. Check the live docs before relying on it.

The plan's own rule still applies: if the live documentation contradicts a fix in this document, the documentation wins. Log the discrepancy in `NOTES.md` with the date, the item ID and the link.

---

## Summary

| ID | Severity | Where in plan.md | Problem in one line |
|---|---|---|---|
| B1 | BLOCKER | Fase 5, Fase 6, file tree | `before_tool` / `after_tool` hooks don't exist in LangChain v1 |
| B2 | BLOCKER | Fase 5, `policy.py` | `gate()` ignores the `stmt_type` value, has no `privileged` branch, never uses `sqlcheck` |
| B3 | BLOCKER | Fase 4 `risk.py`, Fase 3 labels | `stmt_type` Choice mixes non-exclusive axes (effect and cost) |
| B4 | BLOCKER | Fase 5, Fase 9 | On resume, the hook re-runs and calls Jev again before `interrupt()` |
| B5 | BLOCKER | Fase 1, Fase 2 | The Postgres checkpointer needs a write role the plan doesn't define |
| C1 | CONTRADICTION | Fase 6 exit, "Riesgos conocidos" | Fase 6 gate requires beating an LLM; the risks section says that's not acceptance; it depends on Fase 7 |
| C2 | CONTRADICTION | Fase 4 `loop.py`, Fase 6 | Loop policy uses confidence on Noul questions, which have none; "finish" is undefined |
| M1 | METHOD | Fases 2–5 | Frozen datasets are still used for tuning: no dev/test split |
| M2 | METHOD | Fase 3, Fase 8 | Labels don't support per-question Brier; ECE on 60 samples is noise |
| M3 | METHOD | Fase 8 | False positives measured on an adversarial set, not on real agent traffic |
| M4 | METHOD | Fase 3, Fase 8 | Accuracy has no grading procedure; ambiguous and unanswerable questions have no expected behavior |
| M5 | METHOD | Fase 0, Fase 8 | One run per configuration; the cost estimate counts Jev and ignores the generator LLM |
| M6 | METHOD | Fase 7 | "Same thresholds" isn't fair for an LLM judge; the rules-only baseline is missing |
| D1 | DESIGN | Fase 4 `full_scan`, Fase 5 | Jev can't judge table size from SQL text; use `EXPLAIN` |
| D2 | DESIGN | Fase 1 `run_sql`, README | No stated threat model; `run_sql` can be bypassed with multiple statements |
| D3 | DESIGN | Fase 6, README | Result rows are sent to TypeSafe and this isn't documented |
| m1–m5 | MINOR | various | Token budget, misplaced exit criterion, `bonfire_admin` purpose, Fase 10 wording, file tree |
| O1 | OPEN DECISION | Fases 7–8 | Scope: benchmark or demonstration |

**Order.** B1–B5, C1, C2 and M1 must be resolved in `plan.md` before any file exists under `src/middleware/`. M1 must be resolved before the Fase 3 datasets are frozen. The rest can be applied when the corresponding phase starts.

---

## Blockers

### B1 — `before_tool` and `after_tool` don't exist

**Where:** Fase 5 (`risk_gate.py`: `before_tool`), Fase 6 (`loop_control.py`: `after_tool`, and the source line "Hooks `after_tool` / `wrap_tool_call`"), file tree comments.

**Problem.** LangChain v1 middleware has four node-style hooks (`before_agent`, `before_model`, `after_model`, `after_agent`) and two wrap-style hooks (`wrap_model_call`, `wrap_tool_call`). There is no `before_tool` and no `after_tool`. Code written against those names won't run, and an agent reading the plan will invent signatures for them.

**Fix.**

| Decision | Hook | Why |
|---|---|---|
| Risk gate | `after_model` | Runs after the model responds and before tools execute. Sees every tool call of the turn at once. LangChain points to this hook for human-in-the-loop. |
| Loop control, evaluate | `before_model` | Runs before every model call. When the last message is a `ToolMessage` from `run_sql`, evaluate that result. The TypeSafe integration docs suggest `before_model` to reclassify after each tool result. |
| Loop control, enforce "finish" | `wrap_model_call` | The only hook that can change the model request (tools, tool choice). See C2. |

`wrap_tool_call` is a valid alternative for the risk gate (it's the hook `AutoModeMiddleware` uses), but it sees one call at a time and makes the classify/pause split in B4 harder. Prefer `after_model`.

Update in `plan.md`: Fase 5 tasks, Fase 6 tasks and sources, file tree comments.

**Verify:** Verified.

- https://docs.langchain.com/oss/python/langchain/middleware/custom
- https://docs.langchain.com/oss/python/integrations/providers/typesafe

---

### B2 — `policy.gate` has logic holes

**Where:** Fase 5, `src/policy.py`.

**Problem.** The current function:

1. Uses `stmt_type_confidence` but never the value of `stmt_type`. A statement classified `destructive` with 0.95 confidence and `modifies_data = 0.4` returns `ALLOW`.
2. Has no branch for `privileged`. `GRANT` or `CREATE USER` don't "modify data", so they can return `ALLOW`.
3. Doesn't take the `sqlcheck` result as input. `sqlglot` "runs in parallel" but never affects the decision; it only logs.
4. Computes `touches_pii`, never uses it, and has no label for it in `statements.jsonl`, so it can't be evaluated. Olist IDs are hashed; there is almost no real PII to detect.

**Fix.** Two layers. The parser decides first and fails closed. Jev covers the semantic gray zone. A disagreement between them pauses instead of passing.

```python
# src/models.py
class SqlCheck(BaseModel):
    parsed: bool
    n_statements: int
    read_only_root: bool        # root is SELECT or a set operation, optionally wrapped in WITH
    has_write: bool             # INSERT / UPDATE / DELETE / MERGE anywhere, CTEs included
    has_ddl: bool               # CREATE / ALTER / DROP / TRUNCATE
    has_dcl: bool               # GRANT / REVOKE / role management
    has_lock: bool              # FOR UPDATE / FOR SHARE
    unconditioned_join: bool
    est_cost: float | None      # from EXPLAIN, see D1
    est_rows: float | None      # from EXPLAIN, see D1


class Decision(BaseModel):
    action: Action              # ALLOW | INTERRUPT | BLOCK
    reason: str
    discrepancy: bool = False
```

```python
# src/policy.py  (pure code, no network)
EFFECT_MIN_CONFIDENCE = 0.70    # placeholder, set on the dev split (M1)
CARTESIAN_MAX = 0.60            # placeholder, set on the dev split (M1)
COST_MAX: float = ...           # placeholder, set from EXPLAIN on Olist (D1)


def gate(check: SqlCheck, verdict: RiskVerdict) -> Decision:
    # Layer 1: deterministic, fail closed.
    if not check.parsed or check.n_statements != 1 or not check.read_only_root:
        return Decision(action=Action.BLOCK, reason="not a single read-only statement")
    if check.has_write or check.has_ddl or check.has_dcl or check.has_lock:
        return Decision(action=Action.BLOCK, reason="write, DDL, DCL or lock detected")

    # Layer 2: semantic gray zone.
    if verdict.effect != "read":
        return Decision(
            action=Action.INTERRUPT,
            reason="parser says read-only, Jev disagrees",
            discrepancy=True,
        )
    if verdict.effect_confidence < EFFECT_MIN_CONFIDENCE:
        return Decision(action=Action.INTERRUPT, reason="low confidence on effect")

    jev_cartesian = verdict.cartesian > CARTESIAN_MAX
    if check.unconditioned_join or jev_cartesian:
        return Decision(
            action=Action.INTERRUPT,
            reason="possible cartesian product",
            discrepancy=check.unconditioned_join != jev_cartesian,
        )
    if check.est_cost is not None and check.est_cost > COST_MAX:
        return Decision(action=Action.INTERRUPT, reason="estimated cost above limit")

    return Decision(action=Action.ALLOW, reason="read-only, no risk signals")
```

Notes:

- Layer 1 is an allow-list (the root must be a read), not a deny-list of dangerous nodes. Statements `sqlglot` doesn't model come back as an opaque command node; treat them as not read-only.
- `gate()` only decides. Log discrepancies outside it: compute both the parser result and the Jev verdict for every statement and record every disagreement, including the ones where layer 1 already decided.
- Drop `touches_pii` from the rubric. If PII detection is added later, add its dataset label and its policy branch at the same time.
- State in the README what this means: Jev is the second opinion in the risk gate, not the primary decider. That matches the plan's own rule ("Jev es la segunda línea, nunca la única").
- `tests/test_policy.py` covers every branch, including three inputs that return `ALLOW` in the current version: `destructive` with high confidence and low `modifies_data`; a `GRANT`; a `DELETE` that Jev misses.

**Verify:** To verify. `sqlglot` node types for DML, DDL, DCL and locking clauses, and how it represents statements it doesn't model (`exp.Command`). Source: `tobymao/sqlglot` on GitHub, expression tree primer.

---

### B3 — `stmt_type` mixes axes that aren't mutually exclusive

**Where:** Fase 4 (`src/questions/risk.py`), Fase 3 (labels in `statements.jsonl`), Fase 8 (confusion matrix by label).

**Problem.** A `Choice` returns one distribution over mutually exclusive options. `readonly | destructive | privileged | expensive` mixes two axes: what the statement does (effect) and how much it costs. A cartesian `SELECT` is both `readonly` and `expensive`. On exactly the interesting cases the probability splits between options, confidence drops by construction, and the `< 0.70 → INTERRUPT` rule fires for the wrong reason. The labels in `statements.jsonl` have the same ambiguity: the plan doesn't say whether they are single-label or multi-label.

**Fix.** One axis per question:

```
effect     Choice   read | write | privileged | other
cartesian  Noul     the query joins tables without a join condition
```

- Remove `expensive` from the Choice. Cost is decided by `EXPLAIN` (D1).
- Remove `modifies_data` (covered by `effect` and by the parser) and `full_scan` (D1).
- Keep `other` in the Choice, as the plan already suggests.
- Write a one-line description for each Choice option; Jev reads them as criteria.
- Update `RiskVerdict`:

```python
class RiskVerdict(BaseModel):
    effect: Literal["read", "write", "privileged", "other"]
    effect_confidence: float
    effect_probabilities: dict[str, float]
    cartesian: float            # Noul: probability of "yes"
    model_id: str               # versioned model ID returned by the API
```

If an ordinal cost judgment by Jev is ever added back, it must be a `Score`, not a `Noul`. The docs state that a Noul of 0.5 means an even split between yes and no, not "medium".

**Verify:**

- Score vs Noul for a spectrum: Verified, https://docs.langchain.com/oss/python/integrations/providers/typesafe
- Choice option limits and descriptions: To verify, https://docs.typesafe.ai/primitives/choice

---

### B4 — On resume, the hook re-runs and calls Jev again before `interrupt()`

**Where:** Fase 5 (`risk_gate.py`), Fase 9 ("Trampa documentada").

**Problem.** When a graph resumes from `interrupt()`, the node that paused runs again from the start. If the Jev call and the `interrupt()` live in the same hook:

- Jev is called twice for the same tool call.
- If the second verdict differs (for example `ALLOW`), the code never reaches `interrupt()`, the resume value is ignored, and the human's decision is lost. A rejected query runs anyway.

The plan mentions this trap in Fase 9, but it's a Fase 5 design constraint.

**Fix.** Split classifying from pausing into two middlewares, each with its own `after_model` hook:

1. `RiskClassifyMiddleware.after_model`: for each tool call in the last `AIMessage`, runs `sqlcheck` and Jev, applies `policy.gate`, and writes the result to state as `risk_decisions: dict[str, Decision]`, keyed by `tool_call_id`. Skips IDs already in state.
2. `RiskGateMiddleware.after_model`: reads `risk_decisions`. `INTERRUPT` calls `interrupt()` with the SQL and the reason. `BLOCK`, and `INTERRUPT` rejected by the human, prevent the tool from running and return an error message to the model. `ALLOW`, and `INTERRUPT` approved by the human, let the tool run.

For how to prevent a tool call from running and return an error to the model, follow the rejection pattern of the built-in `HumanInTheLoopMiddleware`. Read its source; don't guess.

Each hook is its own graph node, so the state written by (1) is checkpointed before (2) runs. On resume only (2) re-executes, and it reads the stored decision instead of calling Jev.

Ordering: `after_*` hooks run in reverse order of the middleware list, so `RiskClassifyMiddleware` goes after `RiskGateMiddleware` in the list.

Fallback, if the split doesn't behave as described with the installed version: cache decisions by `tool_call_id` in the `bonfire_state` database (B5) and read the cache before calling Jev.

Resume payload:

```python
class Approval(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = None
```

A rejection reaches the model as an error, so it can try another query. Editing the SQL from `/approve` is out of scope for v1.

Add to the Fase 5 exit criterion, as `tests/test_resume.py`: with Jev mocked to return `INTERRUPT` on the first call and `ALLOW` on any later call, a rejected query must not run, and Jev must be called exactly once per `tool_call_id`.

**Verify:** To verify.

- Each middleware hook is a separate graph node, and its state update is checkpointed before the next node: https://docs.langchain.com/oss/python/langchain/middleware/custom
- Execution order of `after_model` hooks across middlewares: same page.
- Node re-execution on resume: https://docs.langchain.com/oss/python/langgraph/interrupts
- Rejection pattern: `HumanInTheLoopMiddleware` source and https://docs.langchain.com/oss/python/langchain/guardrails

---

### B5 — The checkpointer needs a role the plan doesn't have

**Where:** Fase 1 (`init.sql`, two users), Fase 2 (Postgres checkpointer), file tree (`init.sql` comment).

**Problem.** The plan defines `bonfire_agent` (read-only) and `bonfire_admin`. The checkpointer writes, so it can't use `bonfire_agent`. Using `bonfire_admin` hands admin credentials to the app process. And if the checkpoint tables live somewhere `bonfire_agent` can read, the agent can `SELECT` other threads' conversations and pending approvals.

**Fix.** Three roles and two databases on the same Postgres server:

| Role | Database | Privileges | Used by |
|---|---|---|---|
| `bonfire_agent` | `olist` | `CONNECT`; `USAGE` on the data schema; `SELECT` on its tables. Nothing else. | `run_sql` and `EXPLAIN` only |
| `bonfire_app` | `bonfire_state` | Owner of the checkpointer tables | Checkpointer, decision cache (B4) |
| `bonfire_admin` | both | Setup and migrations | `init.sql`, permission tests. Never loaded by the app. |

```sql
REVOKE CONNECT ON DATABASE bonfire_state FROM PUBLIC;
GRANT CONNECT ON DATABASE bonfire_state TO bonfire_app;
REVOKE CONNECT ON DATABASE olist FROM PUBLIC;
GRANT CONNECT ON DATABASE olist TO bonfire_agent;
```

Three DSNs in `.env.example`: `AGENT_DSN`, `STATE_DSN`, `ADMIN_DSN`. The app process loads only the first two. `ADMIN_DSN` is used only by setup scripts and tests.

Add to the Fase 1 exit criterion: connecting to `bonfire_state` as `bonfire_agent` must fail.

**Verify:** To verify.

- `GRANT` / `REVOKE` on databases: Postgres docs for the version in `docker-compose.yml`.
- Checkpointer package name and whether `setup()` must run once: https://docs.langchain.com/oss/python/langgraph/checkpointers

---

## Contradictions

### C1 — The Fase 6 gate contradicts "Riesgos conocidos" and depends on Fase 7

**Where:** Fase 6 exit criterion, "Riesgos conocidos", Fase 7.

**Problem.**

1. Fase 6 (🚦) requires at least an order of magnitude against a decision made by an LLM. "Riesgos conocidos" says winning or losing against the LLM baseline is not an acceptance criterion. Both can't hold.
2. The LLM-decision baseline only exists after Fase 7, so the Fase 6 gate can't be evaluated when Fase 6 ends.
3. Against baseline A the per-turn comparison is ill-defined. In A there is no separate stop decision: the model decides to continue or stop inside the call it has to make anyway (it emits a tool call or it doesn't). Loop control adds one Jev call per turn. It can only save cost by removing turns.

**Fix.**

- Replace the Fase 6 exit criterion with a functional one, measured on the dev questions (M1):
  - every run ends with a final text answer;
  - no run exceeds the turn cap;
  - when loop control decides `finish`, the next model call can't call tools (C2);
  - when it decides `continue`, a feedback message is present before the next model call.
- Remove "al menos un orden de magnitud".
- Move the comparison to Fase 8 as a reported result, per question, not per turn: turns per question, total cost per question, total latency per question.
- Keep "Riesgos conocidos" as it is.

**Verify:** Not applicable (internal consistency).

---

### C2 — Loop control uses a confidence that doesn't exist and never defines "finish"

**Where:** Fase 4 (`src/questions/loop.py`), Fase 6 (policy).

**Problem.**

1. The Fase 6 policy says "confianza alta + `answers_question` alto → termina". The three loop questions are `Noul`, and `Noul` has no confidence field: the probability is the answer. The plan says so itself in Fase 4.
2. `is_empty` is deterministic (`row_count == 0`). A model call for it adds latency and a chance of error.
3. `needs_more` is close to the complement of `answers_question`. Correlated questions add little information.
4. "Termina" and "otra vuelta" aren't mechanisms. Something has to produce the final answer, and nothing says what happens if loop control says finish and the model emits another tool call anyway.
5. TypeSafe lists first-party limitations of Jev 1.13 on arithmetic, dates, distractors and adversarial state. Judging whether numeric results answer a time-window question falls inside that zone.

**Fix.**

Rubric:

```
answers_question  Noul  the result answers the original question at the right grain
looks_wrong       Noul  the values look wrong for the question (impossible values, wrong grain, all NULL)
```

Deterministic checks run first, without Jev. Pure policy in `policy.py`:

```python
MAX_TURNS = 5              # placeholder
ANSWERS_MIN = 0.80         # placeholder, set on the dev split (M1)
LOOKS_WRONG_MAX = 0.50     # placeholder, set on the dev split (M1)


def loop_decision(result: SqlResult, verdict: LoopVerdict | None, turn: int) -> LoopAction:
    if turn >= MAX_TURNS:
        return LoopAction(kind="finish", reason="turn cap reached")
    if result.error:
        return LoopAction(kind="continue", feedback=f"The query failed: {result.error}")
    if result.row_count == 0:
        return LoopAction(kind="continue", feedback="The query returned no rows.")

    assert verdict is not None  # Jev is only called when there is no error and at least one row
    if verdict.answers_question >= ANSWERS_MIN and verdict.looks_wrong <= LOOKS_WRONG_MAX:
        return LoopAction(kind="finish", reason="result answers the question")
    return LoopAction(kind="continue", feedback="The result doesn't answer the question yet.")
```

Mechanics:

- `before_model`: when the last message is a `ToolMessage` from `run_sql`, compute `loop_decision`, write it to state, and on `continue` append the feedback as a message.
- `wrap_model_call`: when the stored decision is `finish`, call the model with tool use disabled (tool choice set to none if the provider supports it; otherwise remove the tools from the request), so the model must answer in text.

Precedence, stated explicitly in `plan.md`:

- `finish` is binding. Jev and the turn cap can end the loop.
- `continue` is advisory. The model sees the feedback and may still answer.

Record the Jev limitation (point 5) in "Riesgos conocidos" and in the README limitations section.

**Verify:**

- Noul has no confidence field: Verified, https://docs.langchain.com/oss/python/integrations/providers/typesafe
- Changing tools or tool choice on the request inside `wrap_model_call`: To verify, https://reference.langchain.com/python/langchain/agents/middleware/types/AgentMiddleware
- Removing tools from a request whose history already contains tool calls: To verify against the chosen generator provider.
- Jev 1.13 limitations page: To verify, linked from https://docs.typesafe.ai/introduction

---

## Methodology

### M1 — Frozen isn't the same as uncontaminated: add a dev/test split

**Where:** Fase 2 (10 pilot questions), Fase 3 (datasets), Fase 4 (rubrics run on `statements.jsonl`), Fase 5 (thresholds).

**Problem.** Fase 4 runs the rubrics on `statements.jsonl` and Fase 5 sets thresholds. If rubric wording or thresholds are adjusted while looking at those 60 statements, they are fitted to the test set. The hash stops edits to the file; it doesn't stop overfitting. The same applies to the Fase 2 pilot: its exit criterion sends you to tune the schema prompt, so those 10 questions can't overlap with the questions used for the final numbers.

**Fix.**

| File | Size | Used for |
|---|---|---|
| `eval/questions_dev.jsonl` | 10 | Fase 2 pilot, prompt tuning, Fase 6 functional checks |
| `eval/questions_test.jsonl` | 40 | Fase 8 only |
| `eval/statements_dev.jsonl` | 20 | Rubric wording, thresholds, `COST_MAX` |
| `eval/statements_test.jsonl` | 40 | Fase 8 only |

- Stratify both splits by category or label. The mandatory edge cases of Fase 3 go in the test split; the dev split gets variants of them, not copies.
- Commit and hash all four files before any file exists under `src/middleware/` (the current rule, extended). Tag the commit `eval-frozen`.
- Rubric wording, thresholds and prompts are tuned on dev only. The test split runs once per configuration, in Fase 8.
- Anything changed after the first test run is a new version: report both versions, don't overwrite.

Update the Fase 3 tables and the file tree.

**Verify:** Not applicable (method).

---

### M2 — Labels don't support the calibration metrics

**Where:** Fase 3 (`statements.jsonl` labels), Fase 8 (Brier and ECE).

**Problem.** Brier score and ECE need binary ground truth per question (is it cartesian?). `statements.jsonl` only has one type label out of four. And with 60 statements, ECE with 10 bins leaves about 6 statements per bin, which is noise.

**Fix.** Statement record:

```json
{"id": "s017", "sql": "...", "effect": "read", "cartesian": false, "expensive": true, "note": "..."}
```

- `effect`: single label, same options as the Choice (B3).
- `cartesian`: boolean, ground truth for the `cartesian` Noul.
- `expensive`: boolean hand label, used to evaluate the `EXPLAIN` threshold (D1).

Reporting:

- Brier score per Noul with a 95% bootstrap interval, plus a reliability diagram with 5 bins.
- Accuracy and confusion matrix for `effect`.
- ECE only with the sample-size caveat, or not at all. Write the caveat in the README.

Update `eval/README.md` (labeling criteria) and the Fase 8 metrics.

**Verify:** Not applicable (method). Metric functions: https://scikit-learn.org/stable/modules/calibration.html

---

### M3 — False positives are measured on the wrong data

**Where:** Fase 8 (metrics table, exit criterion), "Riesgos conocidos".

**Problem.** The labeled statements are deliberately skewed toward dangerous SQL. In real use almost every statement the agent emits is a legitimate read. "A gate that blocks 5% of legitimate queries" has to be measured on the SQL the agent actually emits. The current Fase 8 exit criterion ("los falsos positivos encabezan la tabla") is about column order, not about quality.

**Fix.**

- Log every statement the agent emits during the Fase 8 test runs, with the gate decision.
- Review by hand every statement that got `BLOCK` or `INTERRUPT`, and mark it `true_catch` or `false_positive` in `eval/results/flag_review.csv`.
- Report two numbers: FP rate on `statements_test.jsonl`, and FP rate on real agent traffic.
- New Fase 8 exit criterion: FP rate on real agent traffic at or below 5%, or a README section listing the statements that caused it and why.

**Verify:** Not applicable (method).

---

### M4 — Accuracy has no grading procedure

**Where:** Fase 3 (`questions.jsonl`), Fase 8 ("Acierto").

**Problem.** Execution accuracy requires comparing result sets, and the plan doesn't say how (column names, row order, float rounding, NULLs). The 5 ambiguous and 5 unanswerable questions have no expected behavior.

**Fix.** `eval/grading.py`:

- Grade the result of the agent's last successful query against the reference result, not the prose answer.
- Compare rows as multisets. Ignore column names and column order; compare values.
- Round floats to 2 decimals. `NULL` equals `NULL`.
- Respect row order only when the record has `"ordered": true` (rankings, top-N).

Question record:

```json
{"id": "q12", "category": "join", "question": "...", "reference_sql": "...", "acceptable_sql": [], "ordered": false}
```

Expected behavior per category:

| Category | Pass if |
|---|---|
| Single table, join, time window | Result matches the reference |
| Ambiguous | Result matches `reference_sql` or one of `acceptable_sql`, and the answer states which reading it used (checked by hand) |
| Unanswerable | No numeric answer, and the answer says the schema can't answer it (checked by hand) |

- Store the reference result computed at freeze time, hashed with the file.
- Asking the user a clarifying question is out of scope for v1: `/ask` is single-turn.

**Verify:** Not applicable (method).

---

### M5 — One run per configuration; the cost estimate counts the wrong model

**Where:** Fase 0 (cost estimate), Fase 8 (latency p95, cost per query).

**Problem.**

- Agent trajectories are stochastic. With one run of 40 questions, p95 latency is roughly the second-worst value.
- The Fase 0 estimate counts Jev decisions only. At the published price, Jev input costs $0.042 per million tokens and output is free, so Jev is a rounding error. The cost that matters is the generator LLM and, in Fase 7, the LLM judge.

**Fix.**

- Run each configuration k = 3 times with a fixed temperature. Report mean and min–max, or a bootstrap interval, for every metric. Compute p95 over all k × 40 queries.
- Fase 0 estimate: generator tokens per turn × turns × 40 questions × k × configurations, plus LLM-judge tokens × decisions × k, plus Jev. Use token counts measured in the Fase 2 pilot.
- Record for every run: date, generator model ID, Jev model ID returned by the API, temperature, k.

**Verify:** To verify. Jev pricing on the launch post, https://typesafe.ai/blog/introducing-system-one-models-and-jev (the figure above comes from a secondary source).

---

### M6 — Baseline B isn't a fair comparison, and the rules-only baseline is missing

**Where:** Fase 7, Fase 8 table, `eval/baselines.py`.

**Problem.**

- "Mismas rúbricas, mismos umbrales, misma política" isn't equivalent. A probability an LLM writes into a structured output is a verbalized number, not a distribution over options. The same threshold means different things for each system.
- The natural competitor of the risk gate is missing: deterministic rules alone (sqlglot plus `EXPLAIN`). Without it, the results can't show whether Jev adds anything over a parser.

**Fix.**

- Same questions, same datasets, same policy structure. Thresholds tuned on the dev split separately for each system.
- LLM judge: fixed model ID, temperature 0, structured output with the same question IDs. If the provider exposes token log-probabilities, derive probabilities from them; otherwise use the verbalized numbers and say so in the README.
- Configurations in `eval/baselines.py`:

| Flag | Risk gate | Loop control |
|---|---|---|
| `none` | None | Native (the model decides) |
| `rules` | Layer 1 of B2 plus `EXPLAIN`, no Jev | Native |
| `llm` | Layers 1 and 2, layer 2 decided by an LLM judge | LLM judge |
| `jev` | Layers 1 and 2, layer 2 decided by Jev | Jev |

Subject to O1.

**Verify:** To verify. Structured output limitations in LangChain v1: https://docs.langchain.com/oss/python/langchain/agents

---

## Design and security

### D1 — `full_scan` is a forced piece: use `EXPLAIN`

**Where:** Fase 4 (`full_scan` Noul), Fase 5 (policy), Fase 3 (`expensive` label).

**Problem.** Jev sees the SQL text, not table sizes, statistics or indexes. "Scans a large table without a selective filter" can't be judged from text alone, and Postgres already has a deterministic, free tool for it. In Olist most tables are around 100k rows and the largest (geolocation) is around 1M, so a full scan is cheap. The expensive case in this dataset is essentially the cartesian product, which `statement_timeout` already stops.

**Fix.**

- `sqlcheck.estimate(sql)` runs `EXPLAIN (FORMAT JSON)`, without `ANALYZE` so nothing executes, as `bonfire_agent`, only after layer 1 passes. It fills `SqlCheck.est_cost` and `SqlCheck.est_rows`.
- Set `COST_MAX` by running `EXPLAIN` on the dev statements and on the reference SQL of the dev questions.
- Remove `full_scan` from the Jev rubric (B3).
- State in the README that the cost dimension is weak in Olist.

**Verify:** To verify. Postgres `EXPLAIN` docs for the version in `docker-compose.yml`; Olist table sizes on Kaggle.

---

### D2 — No stated threat model; `run_sql` can be bypassed

**Where:** Fase 1 (`run_sql`), Fase 10 (README), "Riesgos conocidos".

**Problem.**

- With a read-only role, destructive and privileged statements can't succeed anyway. The plan never says what the gate protects, so the project can read as security theater.
- A session-level `statement_timeout` can be overridden by the agent in the same call: `SET statement_timeout = 0; SELECT ...`.
- Truncating results by wrapping the query in `SELECT * FROM (...) LIMIT n` breaks on valid SQL and can change its meaning.

**Fix.**

README section "Threat model":

- The gate protects against expensive queries, and gives the model early and specific feedback instead of a raw database error. It's also a second line if database permissions are misconfigured.
- It doesn't protect against reading any data `bonfire_agent` can read, prompt injection carried inside data values, or attack families not present in the dataset (list them).

`run_sql`:

- Calls `sqlcheck` itself and rejects anything that isn't a single read statement, even if the middleware is misconfigured.
- Opens the connection in read-only mode.
- Role-level settings in `init.sql`:
  ```sql
  ALTER ROLE bonfire_agent SET default_transaction_read_only = on;
  ALTER ROLE bonfire_agent SET statement_timeout = '10s';
  ```
- Truncates with `cursor.fetchmany(MAX_ROWS + 1)` and tells the model when the result was truncated.

`SELECT ... FOR UPDATE` requires `UPDATE` privilege in Postgres, so it already fails for `bonfire_agent`. Keep it in the dataset as a labeling case, not as a live risk.

**Verify:** To verify. Postgres `ALTER ROLE ... SET` and the privileges required by locking clauses; the psycopg read-only connection attribute.

---

### D3 — Result rows are sent to TypeSafe

**Where:** Fase 6, README.

**Problem.** Loop control sends the question, the SQL and result rows to TypeSafe. The integration docs warn not to put secrets in tool arguments or conversation state unless sending them to TypeSafe is acceptable. The same applies to query results.

**Fix.**

- Send Jev at most `MAX_ROWS_TO_JEV` rows, plus the column names and the total row count.
- State in the README what leaves the system and to whom. With Olist (public data) this is acceptable; say so explicitly.

**Verify:** Verified. https://docs.langchain.com/oss/python/integrations/providers/typesafe

---

## Minor

**m1 — Token budget.** Fase 0 mentions a budget of about 32,000 tokens. There are two limits: state plus all questions share about 64,000 tokens, and state plus the longest single question must fit in about 32,000. Size `MAX_ROWS_TO_JEV` against the second. To verify on https://docs.typesafe.ai (figures from a secondary source).

**m2 — Fase 4 exit criterion is in the wrong phase.** Measuring latency with 3 and with 5 questions checks a property of the API. Move it to Fase 0. New Fase 4 exit criterion: per-question accuracy of the rubric on `statements_dev.jsonl`.

**m3 — `bonfire_admin` purpose.** Fase 1 says it's for "las pruebas de seguridad de la Fase 3", but Fase 3 has no security tests. Its real purpose: `init.sql`, migrations and permission tests. Eval statements are classified, never executed.

**m4 — Fase 10 wording.** "Los 7 criterios de aceptación" are never defined; the 7 items are README sections. Either write an explicit acceptance list or rename them. "Cómo reproducir todo con un comando" reproduces the pipeline, not the numbers, because model versions move: say so and point to the model IDs recorded per run.

**m5 — File tree.** Changed or new entries only:

```
bonfire/
├── init.sql                      # olist + bonfire_state databases, three roles, role-level settings
├── .env.example                  # AGENT_DSN, STATE_DSN, ADMIN_DSN
│
├── src/
│   ├── models.py                 # SqlCheck, RiskVerdict, LoopVerdict, Decision, LoopAction, Approval
│   ├── policy.py                 # gate(), loop_decision(); pure code
│   ├── sqlcheck.py               # sqlglot allow-list + EXPLAIN estimate
│   ├── agent/
│   │   └── tools.py              # run_sql: re-checks, read-only connection, fetchmany
│   ├── questions/
│   │   ├── risk.py               # effect (Choice), cartesian (Noul)
│   │   └── loop.py               # answers_question, looks_wrong (Noul)
│   └── middleware/
│       ├── risk_classify.py      # after_model: sqlcheck + Jev + policy -> state
│       ├── risk_gate.py          # after_model: block / interrupt() from stored decisions
│       └── loop_control.py       # before_model (evaluate) + wrap_model_call (enforce finish)
│
├── eval/
│   ├── questions_dev.jsonl       # 10
│   ├── questions_test.jsonl      # 40
│   ├── statements_dev.jsonl      # 20
│   ├── statements_test.jsonl     # 40
│   ├── grading.py                # result-set comparator
│   ├── baselines.py              # none / rules / llm / jev
│   └── results/
│       └── flag_review.csv       # hand review of flagged real traffic
│
└── tests/
    ├── test_policy.py            # every branch of gate() and loop_decision()
    ├── test_sqlcheck.py
    └── test_resume.py            # B4: Jev mocked, called once per tool_call_id
```

---

## Open decision (not an error)

### O1 — Scope: benchmark or demonstration

Fases 7 and 8 exist to compare Jev against an LLM judge. If the goal of the project is to show Jev as the decision layer of an agent rather than to benchmark it, the owner may:

- drop Fase 7 and the `llm` configuration;
- reduce Fase 8 to functional metrics: FP rate on real traffic, accuracy, turns per question, cost per question;
- move Langfuse and SSE streaming to a v2.

**Decided 2026-09-24 by the owner: demonstration, not benchmark.** Fase 7 and the LLM judge were removed from `plan.md`; the old Fase 8 is now Fase 7 (Validación), with one configuration. Items M6 and the comparison parts of C1 and M5 no longer apply. Langfuse and SSE stay in the plan (Fase 8).
