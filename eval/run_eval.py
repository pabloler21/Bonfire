"""Corre el agente sobre un archivo de preguntas como un experimento de Langfuse.

uv run python -m eval.run_eval eval/questions_traps.jsonl traps_jev

Langfuse recorre las preguntas, deja una traza por pregunta (SQL, tokens, modelo, latencia, la línea `Reviewer:`
de Jev) y le pone el score `correct`. El resultado se ve en Langfuse → Experiments; la consola imprime un resumen.
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langfuse import Evaluation, get_client

from eval.grading import normalize, same_result
from src.agent.build import SYSTEM_PROMPT, build_agent
from src.agent.tools import run_sql
from src.config import generator_model, prompt_sha, settings


def last_successful_result(messages: list):
    """El resultado de la última query que corrió sin error: es lo que se califica, no la respuesta en prosa."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.artifact is not None and m.artifact.error is None:
            return m.artifact
    return None


def comparable(rows: list) -> list[list[str]]:
    # Langfuse muestra un Decimal como "<Decimal>": se manda normalizado. normalize() de un texto lo deja igual.
    return [[normalize(v) for v in row] for row in rows]


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
    ok = output is not None and same_result(expected_output, output, metadata["ordered"])
    return Evaluation(name="correct", value=1.0 if ok else 0.0)


if __name__ == "__main__":
    load_dotenv()
    questions_path, run_name = sys.argv[1], sys.argv[2]
    agent = build_agent()

    def task(*, item, **kwargs):
        messages = agent.invoke({"messages": [{"role": "user", "content": item["input"]}]})["messages"]
        result = last_successful_result(messages)
        return comparable(result.rows) if result else None

    result = get_client().run_experiment(
        name=run_name,
        data=load_items(questions_path),
        task=task,
        evaluators=[correct],
        max_concurrency=1,  # una pregunta a la vez: latencias comparables y sin saturar OpenAI ni Postgres
        metadata={
            "questions_file": questions_path,
            "model_requested": generator_model(),
            "max_model_calls": str(settings.agent.max_model_calls),
            "prompt_sha": prompt_sha(SYSTEM_PROMPT),
        },
    )
    print(result.format(include_item_results=True))
    get_client().flush()  # proceso corto: sin flush, las trazas en cola se pierden al salir
