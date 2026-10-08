"""Fase 5 — Política pura, sin red: review_decision(result, verdict, attempt) -> NextAction (answer / retry con motivo /
ask_user). Los umbrales y MAX_ATTEMPTS viven acá; el middleware solo los aplica.

Orden de las reglas: tope de intentos, error de SQL, cero filas (estos tres sin Jev), trampa detectada, next_step.
"""

from src.models import NextAction, ReviewVerdict, SqlResult

MAX_ATTEMPTS = 4  # placeholder (plan.md, "Umbrales"): consultas revisadas por pregunta, la última se responde igual

# ponytail: un umbral para todas las trampas. Sobre las 10 de traps.json (NOTES.md, 08/10/2026) las respuestas
# correctas quedaron por debajo de 0,2 y los errores entre 0,69 y 0,97. Un dict por trampa si alguna lo pide.
PITFALL_MIN = 0.5

# El motivo que lee el LLM para reescribir, uno por trampa de src/questions/review.py.
TRAP_REASONS = {
    "customer_id_not_unique": "customer_id is created once per order, so it does not identify a person. "
    "Count or group people by customer_unique_id.",
    "join_fanout": "A join repeats rows before the sum or count, so some values are counted more than once. "
    "Aggregate each table on its own, or pick the rows with EXISTS or IN.",
    "wrong_grain": "The rows you count are not the entity the question asks about. "
    "Count DISTINCT the entity's key (for example order_id or review_id).",
    "wrong_date_column": "The query filters by a different date than the event in the question. "
    "Use the column for that event; with no event named, use order_purchase_timestamp.",
    "undelivered_as_sales": "Sales, items sold and revenue count only orders with order_status = 'delivered'.",
}


def needs_jev(result: SqlResult) -> bool:
    """Un error de SQL o cero filas los resuelve el código: no hace falta preguntarle a Jev."""
    return result.error is None and result.row_count > 0


def review_decision(result: SqlResult, verdict: ReviewVerdict | None, attempt: int) -> NextAction:
    """Qué hace el agente con el resultado de su intento número `attempt` (empieza en 1)."""
    if attempt >= MAX_ATTEMPTS:
        return NextAction(kind="answer", reason="Attempt limit reached. Answer with the best result so far and say it may be wrong.")
    if result.error:
        return NextAction(kind="retry", reason="The query failed. Fix it and run it again.")
    if result.row_count == 0:
        return NextAction(kind="retry", reason="The query returned no rows. Check the filters and the values they compare against.")

    assert verdict is not None, "Jev is only skipped when needs_jev() is False"
    # Una trampa detectada gana sobre next_step = answer: el motivo concreto sirve más para reescribir.
    flagged = [trap for trap, probability in verdict.pitfalls.items() if probability >= PITFALL_MIN]
    if flagged:
        return NextAction(kind="retry", reason=" ".join(TRAP_REASONS[trap] for trap in flagged))
    if verdict.next_step == "retry":
        return NextAction(kind="retry", reason="The result does not seem to answer the question as asked. Check what the query measures and how it filters.")
    if verdict.next_step == "ask_user":
        return NextAction(kind="ask_user", reason="The question is ambiguous or this database cannot answer it. Ask the user a clarifying question instead of answering.")
    return NextAction(kind="answer", reason="The result answers the question. Reply to the user now.")
