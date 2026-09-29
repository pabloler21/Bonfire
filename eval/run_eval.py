"""Corre el agente sobre un archivo de preguntas y guarda las trazas completas.

Fase 2 (piloto): uv run python -m eval.run_eval eval/questions_dev.jsonl eval/results/pilot.json
Fase 6 le suma k corridas, falsos positivos y las demás métricas.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, ToolMessage
from langfuse import get_client

from eval.grading import normalize, same_result
from src.agent.build import build_agent
from src.agent.tools import run_sql


def trace(messages: list) -> dict:
    """Vueltas del agente a partir de los mensajes: SQL, resultado y tokens de cada llamada al modelo."""
    tool_results = {m.tool_call_id: m.artifact for m in messages if isinstance(m, ToolMessage)}
    turns = []
    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        usage = m.usage_metadata or {}
        turn = {
            "model": m.response_metadata.get("model_name"),  # el ID que devolvió la API, no el alias pedido
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "sql": [],
        }
        for call in m.tool_calls:
            result = tool_results.get(call["id"])
            turn["sql"].append({
                "query": call["args"].get("query"),
                "error": result.error if result else "no tool result",
                "row_count": result.row_count if result else 0,
            })
        turns.append(turn)
    return {"turns": turns, "answer": messages[-1].text}


def last_successful_result(messages: list):
    """El resultado de la última query que corrió sin error: es lo que se califica, no la respuesta en prosa."""
    for m in reversed(messages):
        if isinstance(m, ToolMessage) and m.artifact is not None and m.artifact.error is None:
            return m.artifact
    return None


def run(questions_path: str, out_path: str) -> dict:
    agent = build_agent()
    records = []
    for line in Path(questions_path).read_text(encoding="utf-8").splitlines():
        question = json.loads(line)
        # Resultado de referencia calculado en vivo: los datos de Olist no cambian. Fase 3 lo congela para test.
        _, expected = run_sql.func(question["reference_sql"])

        start = time.perf_counter()
        messages = agent.invoke({"messages": [{"role": "user", "content": question["question"]}]})["messages"]
        latency = time.perf_counter() - start

        actual = last_successful_result(messages)
        correct = actual is not None and same_result(expected.rows, actual.rows, question["ordered"])
        records.append({
            "id": question["id"],
            "category": question["category"],
            "question": question["question"],
            "correct": correct,
            "expected": [[normalize(v) for v in row] for row in expected.rows],
            "actual": [[normalize(v) for v in row] for row in actual.rows] if actual else None,
            "latency_s": round(latency, 2),
            **trace(messages),
        })
        print(f"{question['id']} {'OK ' if correct else 'BAD'} {latency:5.1f}s  {question['question']}")

    models = sorted({t["model"] for r in records for t in r["turns"] if t["model"]})
    report = {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "questions_file": questions_path,
        "models_returned": models,
        "summary": {
            "correct": sum(r["correct"] for r in records),
            "total": len(records),
            "avg_turns": round(sum(len(r["turns"]) for r in records) / len(records), 2),
            "avg_latency_s": round(sum(r["latency_s"] for r in records) / len(records), 2),
            "input_tokens": sum(t["input_tokens"] or 0 for r in records for t in r["turns"]),
            "output_tokens": sum(t["output_tokens"] or 0 for r in records for t in r["turns"]),
        },
        "questions": records,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    load_dotenv()
    report = run(sys.argv[1], sys.argv[2])
    print(json.dumps(report["summary"], indent=2))
    get_client().flush()  # proceso corto: sin flush, las trazas en cola se pierden al salir
