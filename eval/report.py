"""Fase 6 — La tabla de resultados, armada desde Langfuse con las corridas de run_eval.

uv run python -m eval.report dev_k traps_k

Cada argumento es el comienzo del nombre de las corridas que van juntas (dev_k toma dev_k1, dev_k2 y dev_k3). Lee de
Langfuse cada pregunta (su salida con los intentos, el score `correct`, la latencia) y el costo de su traza, y
escribe en eval/results/:
- phase6.json: los datos crudos, una fila por pregunta y corrida;
- flag_review.csv: cada intento que la revisión mandó a reintentar o a preguntar, marcado `true_catch` o
  `false_positive` contra la referencia (label_attempt);
- phase6.md: la tabla, con los falsos positivos primero.

Langfuse tarda un poco en procesar lo que llega: correrlo unos minutos después de la última corrida.
"""

import csv
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from langfuse import get_client

from eval.grading import label_attempt

RESULTS = Path("eval/results")
SINCE = timedelta(days=30)  # la API pide una fecha de inicio; las corridas de la Fase 6 caben de sobra
JEV_USD_PER_TOKEN = 0.042 / 1_000_000  # jev-1.13.0 y jev-1.14.0, typesafe.ai/pricing (02/11/2026)


def pages(fetch, **kwargs) -> list:
    """Todas las páginas de un endpoint de Langfuse con cursor."""
    found, cursor = [], None
    while True:
        response = fetch(cursor=cursor, **kwargs)
        found += response.data
        cursor = response.meta.cursor
        if not cursor:
            return found


def parsed(value):
    """La API devuelve input, output y expected_output como texto JSON; una task que falló deja "Error: ..."."""
    try:
        return json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError:
        return value


def trace_cost(api, trace_id: str) -> dict:
    """Costo del generador (lo calcula Langfuse), tokens de Jev y los modelos que contestaron, desde la traza."""
    observations = pages(api.observations.get_many, trace_id=trace_id, fields="core,basic,io,usage,model", limit=100)
    generator_usd, jev_tokens, models = 0.0, 0, set()
    for o in observations:
        if o.type == "GENERATION":
            generator_usd += o.total_cost or 0.0
            models.add(o.model)
        elif o.name == "TypeSafeClient":  # el span del instrumentor de Jev
            answer = parsed(o.output)
            jev_tokens += answer["usage"]["input_tokens"] + answer["usage"]["output_tokens"]
            models.add(answer["model"])
    return {"generator_usd": generator_usd, "jev_tokens": jev_tokens, "models": sorted(m for m in models if m)}


def collect(api, prefix: str) -> list[dict]:
    """Una fila por pregunta de cada corrida cuyo nombre empieza con `prefix`."""
    since = datetime.now(timezone.utc) - SINCE
    runs = [e for e in pages(api.experiments.list, from_start_time=since, limit=100) if e.name.startswith(prefix)]
    rows = []
    for run in sorted(runs, key=lambda e: e.name):
        items = pages(api.experiments.list_items, from_start_time=since, experiment_id=run.id,
                      fields="core,io,itemMetadata,scores", limit=100)
        # Si la task falla (una key vencida, Jev caído), la salida es el texto "Error: ..." en vez del dict.
        if all(not isinstance(parsed(i.output), dict) for i in items):
            print(f"Se saltea {run.name}: fallaron todas sus preguntas ({str(parsed(items[0].output))[:80]})")
            continue
        for item in items:
            meta = item.experiment_item_metadata  # Langfuse guarda los valores como texto: "false", no False
            output, expected = parsed(item.output), parsed(item.expected_output)
            row = {"group": prefix, "run": run.name, "id": meta["id"], "error": None}
            if not isinstance(output, dict):
                rows.append(row | {"error": str(output)})  # cuenta como error, no entra en las métricas
                continue
            rows.append(row | {
                "correct": next(s.value for s in item.scores if s.name == "correct"),
                "attempts": output["attempts"],
                "labels": [label_attempt(a, expected, meta["ordered"] == "true") for a in output["attempts"]],
                "latency_s": (item.end_time - item.start_time).total_seconds(),
                **trace_cost(api, item.trace_id),
            })
    return rows


def summary(rows: list[dict]) -> dict:
    """Las métricas de la Fase 6 para un grupo de filas. Latencia, costo e intentos van por pregunta."""
    errors = sum(1 for r in rows if r.get("error"))
    rows = [r for r in rows if not r.get("error")]
    labels = Counter(label for r in rows for label in r["labels"])
    per_run = {}
    for r in rows:
        per_run.setdefault(r["run"], []).append(r["correct"])
    accuracy = [sum(v) / len(v) for v in per_run.values()]
    latencies = [r["latency_s"] for r in rows]
    costs = [r["generator_usd"] + r["jev_tokens"] * JEV_USD_PER_TOKEN for r in rows]
    return {
        "runs": len(per_run),
        "questions": len(rows),
        "errors": errors,
        "false_positives": labels["false_positive"],
        "correct_reviewed": labels["false_positive"] + labels["pass"],
        "true_catches": labels["true_catch"],
        "wrong_reviewed": labels["true_catch"] + labels["missed"],
        "accuracy_mean": statistics.mean(accuracy),
        "accuracy_min": min(accuracy),
        "accuracy_max": max(accuracy),
        "latency_p95_s": statistics.quantiles(latencies, n=20, method="inclusive")[-1],
        "cost_usd_mean": statistics.mean(costs),
        "attempts_mean": statistics.mean(len(r["attempts"]) for r in rows),
        "attempts_max": max(len(r["attempts"]) for r in rows),
        "models": sorted({m for r in rows for m in r["models"]}),
    }


def table(summaries: dict[str, dict]) -> str:
    def pct(a, b):
        return f"{a}/{b} ({a / b:.0%})" if b else "—"

    lines = [
        "| Grupo | FP en tráfico real | Errores detectados | Acierto (media, mín–máx) | Latencia p95 | Costo / pregunta | Intentos / pregunta (media, máx) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in summaries.items():
        lines.append(
            f"| {name} ({s['runs']} corridas, {s['questions']} preguntas, {s['errors']} con error) "
            f"| {pct(s['false_positives'], s['correct_reviewed'])} "
            f"| {pct(s['true_catches'], s['wrong_reviewed'])} "
            f"| {s['accuracy_mean']:.2f} ({s['accuracy_min']:.1f}–{s['accuracy_max']:.1f}) "
            f"| {s['latency_p95_s']:.1f} s "
            f"| US$ {s['cost_usd_mean']:.5f} "
            f"| {s['attempts_mean']:.2f}, {s['attempts_max']} |"
        )
    models = sorted({m for s in summaries.values() for m in s["models"]})
    return "\n".join(lines) + f"\n\nModelos que contestaron: {', '.join(models)}.\n"


if __name__ == "__main__":
    load_dotenv()
    api = get_client().api
    rows = [row for prefix in sys.argv[1:] for row in collect(api, prefix)]
    if not any(not r["error"] for r in rows):
        sys.exit("No hay ninguna pregunta que haya corrido bien en esas corridas: no hay nada que resumir.")
    groups = [p for p in sys.argv[1:] if any(r["group"] == p and not r["error"] for r in rows)]
    summaries = {prefix: summary([r for r in rows if r["group"] == prefix]) for prefix in groups}
    summaries["total"] = summary(rows)

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "phase6.json").write_text(
        json.dumps({"summaries": summaries, "questions": rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with open(RESULTS / "flag_review.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["run", "id", "attempt", "decision", "label", "sql", "reason"])
        for r in (r for r in rows if not r["error"]):
            for n, (attempt, label) in enumerate(zip(r["attempts"], r["labels"]), start=1):
                if attempt["reviewed"] and attempt["decision"] != "answer":
                    writer.writerow([r["run"], r["id"], n, attempt["decision"], label, attempt["sql"], attempt["reason"]])
    markdown = table(summaries)
    (RESULTS / "phase6.md").write_text(markdown, encoding="utf-8")
    print(markdown)
