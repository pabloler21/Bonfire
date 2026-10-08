"""Fase 4 — La rúbrica de revisión: lo que ve Jev (build_review_state), lo que se le pregunta (QUESTIONS) y la
llamada (review). Una request a Jev por intento; la usa el middleware de la Fase 5.

Probar a mano con lo que escribió el agente, con la base levantada:
    uv run python -m src.questions.review eval/results/traps.json t01
"""

import json
import sys
import time
from functools import cache
from pathlib import Path

from typesafe_sdk import Choice, Noul, TypeSafeClient

from src.models import ReviewVerdict, SqlResult

MAX_ROWS_TO_JEV = 20  # placeholder (plan.md, "Umbrales"): con menos contexto irrelevante, Jev responde mejor

# Hechos del esquema que Jev necesita para juzgar. Los hechos van en el state, el criterio en las preguntas
# (docs.typesafe.ai/concepts/state). Medidos sobre la base el 06/10/2026 (eval/README.md).
SCHEMA_NOTES = [
    "customers.customer_id is created once per order, so a person who ordered three times has three "
    "customer_id values; customer_unique_id identifies the person.",
    "order_items has one row per unit sold, so an order can have several rows.",
    "order_payments has one row per payment, so an order can have several rows.",
    "order_reviews can hold the same review_id for several orders.",
    "geolocation has many rows per zip code prefix (about 53 on average), one per coordinate.",
    "Sales, items sold and revenue count only orders with order_status = 'delivered'. "
    "Questions about orders in general count every status.",
    "order_status is the order's current status, not its history: an order approved in January can be "
    "'delivered' today.",
    "Order dates: order_purchase_timestamp (purchase), order_approved_at (payment approved), "
    "order_delivered_carrier_date (handed to the carrier), order_delivered_customer_date (delivered to the "
    "customer). A question that names no event means the purchase date.",
]

# Jev responde literal lo que se le pregunta (docs.typesafe.ai/model-jaggedness/jev-1.13): cada pregunta dice
# exactamente qué condición mira. Los IDs no se le mandan al modelo, son para el código.
QUESTIONS = {
    "next_step": Choice(
        instructions="What should the SQL agent do with this `result`, given the user's `question`, the `sql` "
        "it ran and the facts in `schema_notes`?",
        criteria={
            "answer": "The result answers the question as asked and can be reported to the user.",
            "retry": "The SQL or the result has a problem that a different query could fix: it measures something "
            "other than what was asked, counts or sums the wrong rows, uses the wrong column or filter, or returns "
            "an implausible value such as 0 for something the data clearly contains.",
            "ask_user": "The question allows several reasonable readings and the SQL picked one, or the question "
            "cannot be answered with this database; a person has to clarify.",
        },
    ),
    "customer_id_not_unique": Noul(
        instructions="The `sql` counts or groups customers as people using customer_id instead of "
        "customer_unique_id.",
        criteria={
            "true": "For example COUNT(*) FROM customers, COUNT(DISTINCT customer_id), or GROUP BY customer_id to "
            "count people or the orders of each person.",
            "false": "The SQL uses customer_unique_id for people, uses customer_id only as a join key, or does not "
            "count or group customers.",
        },
    ),
    "join_fanout": Noul(
        instructions="The `sql` sums, averages or counts a value after a join that repeats that value once per "
        "matching row of another table.",
        criteria={
            "true": "For example summing order_payments.payment_value after joining order_items, or aggregating "
            "after joining geolocation on a zip code prefix.",
            "false": "Every join matches at most one row per aggregated row, the rows are picked with EXISTS or IN "
            "before aggregating, or the count uses DISTINCT on the right key.",
        },
    ),
    "wrong_grain": Noul(
        instructions="The `sql` counts or averages the rows of one table to answer about a different entity, "
        "without DISTINCT on that entity's key.",
        criteria={
            "true": "For example counting order_items rows as orders, averaging order_payments rows as orders, or "
            "counting order_reviews rows as reviews.",
            "false": "Each counted or averaged row is one of the entities the question asks about, or the SQL uses "
            "DISTINCT on that entity's key.",
        },
    ),
    "wrong_date_column": Noul(
        instructions="The `sql` filters or groups by a different date column than the event the `question` asks "
        "about.",
        criteria={
            "true": "For example filtering by order_delivered_customer_date when the question asks when orders were "
            "placed, or by the purchase date when it asks when they were delivered.",
            "false": "The date column matches the event in the question, the question names no event and the SQL "
            "uses the purchase date, or the question involves no dates.",
        },
    ),
    # Mira también la `question`: sin eso, Jev tomaba una suma de pagos como "ingresos" aunque la pregunta pidiera
    # todos los estados (t03, t04 de eval/results/traps.json, 08/10/2026).
    "undelivered_as_sales": Noul(
        instructions="The `question` asks about sales, items sold or revenue, and the `sql` includes orders whose "
        "order_status is not 'delivered'.",
        criteria={
            "true": "For example summing item prices for 'sales revenue' or counting 'items sold' over orders of "
            "every status.",
            "false": "The SQL filters order_status = 'delivered'; or the question asks about payments, freight or "
            "orders in general, or says to include every order status.",
        },
    ),
}


def build_review_state(question: str, sql: str, result: SqlResult) -> dict:
    """Lo que ve Jev. Las mismas reglas para el middleware (Fase 5) y para probar a mano."""
    return {
        "question": question,
        "sql": sql,
        "result": {
            "columns": result.columns,
            "row_count": result.row_count,
            # default=str: Decimal y datetime no son JSON; Jev los lee igual como texto
            "rows": json.loads(json.dumps(result.rows[:MAX_ROWS_TO_JEV], default=str)),
            "rows_omitted": result.truncated or result.row_count > MAX_ROWS_TO_JEV,
        },
        "schema_notes": SCHEMA_NOTES,
    }


@cache
def _client() -> TypeSafeClient:
    # TYPESAFE_API_KEY sale del .env. Modelo: el default del SDK (jev-latest); se registra la versión que contestó.
    return TypeSafeClient()


def review(question: str, sql: str, result: SqlResult) -> ReviewVerdict:
    """Una request a Jev. Los errores de la API se propagan: el SDK reintenta 429 y 5xx, nunca un 400."""
    start = time.perf_counter()
    response = _client().system_one(state=build_review_state(question, sql, result), questions=QUESTIONS)
    next_step = response.choices["next_step"]
    return ReviewVerdict(
        next_step=next_step.choice,
        next_step_confidence=next_step.confidence,
        next_step_probabilities=next_step.probabilities,
        pitfalls={name: answer.noul for name, answer in response.nouls.items()},
        model_id=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        latency_s=round(time.perf_counter() - start, 2),
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    from src.agent.tools import run_sql

    load_dotenv()
    results_path, question_id = sys.argv[1], sys.argv[2]
    record = next(q for q in json.loads(Path(results_path).read_text(encoding="utf-8"))["questions"] if q["id"] == question_id)
    sql = [s for t in record["turns"] for s in t["sql"] if s["error"] is None][-1]["query"]  # la que se calificó
    _, result = run_sql.func(sql)
    print(f"{question_id} (agente: {'OK' if record['correct'] else 'BAD'}) {record['question']}\n{sql}\n")
    print(review(record["question"], sql, result).model_dump_json(indent=2))
