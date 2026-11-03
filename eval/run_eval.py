"""Corre el agente sobre un archivo de preguntas como un experimento de Langfuse.

uv run python -m eval.run_eval eval/questions_traps.jsonl traps_k1

Langfuse recorre las preguntas, deja una traza por pregunta (SQL, tokens, modelo, latencia, la llamada a Jev) y le
pone los scores `correct`, `attempts` y `false_positives`. La salida de cada pregunta guarda además cada intento
(SQL, filas, decisión de la revisión): de ahí sale la tabla de la Fase 6 (`eval/report.py`). El resultado se ve en
Langfuse → Experiments; la consola imprime un resumen.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langfuse import Evaluation, get_client

from eval.grading import label_attempt, normalize, same_result
from src import policy
from src.agent.build import SYSTEM_PROMPT, build_agent
from src.agent.tools import run_sql
from src.config import generator_model, prompt_sha, settings
from src.models import SqlResult


def last_successful_result(messages: list):
    """El resultado de la última query que corrió sin error: es lo que se califica, no la respuesta en prosa."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.artifact is not None and m.artifact.error is None:
            return m.artifact
    return None


def comparable(rows: list) -> list[list[str]]:
    # Langfuse muestra un Decimal como "<Decimal>": se manda normalizado. normalize() de un texto lo deja igual.
    return [[normalize(v) for v in row] for row in rows]


def attempts(messages: list) -> list[dict]:
    """Cada run_sql del agente: el SQL, sus filas, si lo vio Jev y qué decidió la revisión (la línea `Reviewer:`)."""
    queries = {c["id"]: c["args"].get("query") for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
    found = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.artifact, SqlResult):
            decision, _, reason = m.text.rpartition("Reviewer: ")[2].partition(". ")
            found.append({
                "sql": queries.get(m.tool_call_id),
                "error": m.artifact.error,
                "rows": comparable(m.artifact.rows),
                # la misma cuenta que el middleware: el intento número n se revisa si needs_jev(result, n)
                "reviewed": policy.needs_jev(m.artifact, len(found) + 1),
                "decision": decision,
                "reason": reason,
            })
    return found


def load_items(questions_path: str) -> list[dict]:
    """Cada pregunta del .jsonl como item de Langfuse. La referencia se calcula en vivo: Olist no cambia."""
    items = []
    for line in Path(questions_path).read_text(encoding="utf-8").splitlines():
        q = json.loads(line)
        _, expected = run_sql.func(q["reference_sql"])
        items.append({
            "input": q["question"],
            "expected_output": comparable(expected.rows),
            "metadata": {"id": q["id"], "category": q["category"], "ordered": q["ordered"]},
        })
    return items


def correct(*, output, expected_output, metadata, **kwargs) -> Evaluation:
    """Evaluator de Langfuse: 1 si las filas del agente son las de la referencia (reglas en grading.py)."""
    ok = output["rows"] is not None and same_result(expected_output, output["rows"], metadata["ordered"])
    return Evaluation(name="correct", value=1.0 if ok else 0.0)


def review(*, output, expected_output, metadata, **kwargs) -> list[Evaluation]:
    """Evaluator de Langfuse: cuántos intentos hubo y cuántos resultados correctos mandó a reintentar la revisión."""
    labels = [label_attempt(a, expected_output, metadata["ordered"]) for a in output["attempts"]]
    return [
        Evaluation(name="attempts", value=float(len(labels))),
        Evaluation(name="false_positives", value=float(labels.count("false_positive"))),
    ]


if __name__ == "__main__":
    load_dotenv()
    questions_path, run_name = sys.argv[1], sys.argv[2]
    agent = build_agent()

    def task(*, item, **kwargs):
        messages = agent.invoke({"messages": [{"role": "user", "content": item["input"]}]})["messages"]
        result = last_successful_result(messages)
        return {"rows": comparable(result.rows) if result else None, "attempts": attempts(messages)}

    result = get_client().run_experiment(
        name=run_name,
        data=load_items(questions_path),
        task=task,
        evaluators=[correct, review],
        max_concurrency=1,  # una pregunta a la vez: latencias comparables y sin saturar OpenAI ni Postgres
        metadata={
            "questions_file": questions_path,
            "model_requested": generator_model(),
            "max_model_calls": str(settings.agent.max_model_calls),
            "max_attempts": str(policy.MAX_ATTEMPTS),
            "pitfall_min": str(policy.PITFALL_MIN),
            "prompt_sha": prompt_sha(SYSTEM_PROMPT),
        },
    )
    print(result.format(include_item_results=True))
    get_client().flush()  # proceso corto: sin flush, las trazas en cola se pierden al salir
