"""Tests de eval/run_eval.py, sin red: cómo se arma el detalle de intentos a partir de los mensajes del agente."""

from langchain_core.messages import AIMessage, ToolMessage

from eval.run_eval import attempts, correct, review
from src.models import SqlResult


def sql_turn(query: str, call_id: str, result: SqlResult, reviewer: str) -> list:
    """Un intento como lo deja el agente: el AIMessage que pide run_sql y el ToolMessage con la línea del middleware."""
    return [
        AIMessage(content="", tool_calls=[{"name": "run_sql", "args": {"query": query}, "id": call_id}]),
        ToolMessage(content=f"rows...\n\nReviewer: {reviewer}", tool_call_id=call_id, artifact=result),
    ]


MESSAGES = [
    *sql_turn("SELECT COUNT(*) FROM customers", "c1", SqlResult(columns=["n"], rows=[[99441]], row_count=1),
              "retry. customer_id is created once per order."),
    *sql_turn("SELECT COUNT(*) FROM nope", "c2", SqlResult(error="PostgreSQL error: relation does not exist"),
              "retry. The query failed. Fix it and run it again."),
    *sql_turn("SELECT COUNT(DISTINCT customer_unique_id) FROM customers", "c3",
              SqlResult(columns=["n"], rows=[[96096]], row_count=1), "answer. The result answers the question."),
    AIMessage(content="There are 96,096 customers."),
]


def test_attempts_pair_each_query_with_its_rows_and_decision():
    first, failed, last = attempts(MESSAGES)

    assert first == {
        "sql": "SELECT COUNT(*) FROM customers",
        "error": None,
        "rows": [["99441.00"]],
        "reviewed": True,
        "decision": "retry",
        "reason": "customer_id is created once per order.",
    }
    assert failed["reviewed"] is False and failed["decision"] == "retry"  # un error lo resuelve el código, sin Jev
    assert last["decision"] == "answer" and last["rows"] == [["96096.00"]]


def test_evaluators_read_the_task_output():
    output = {"rows": [["96096.00"]], "attempts": attempts(MESSAGES)}
    expected, metadata = [["96096.00"]], {"ordered": False}

    assert correct(output=output, expected_output=expected, metadata=metadata).value == 1.0
    scores = {e.name: e.value for e in review(output=output, expected_output=expected, metadata=metadata)}
    assert scores == {"attempts": 3.0, "false_positives": 0.0}  # el retry del primero fue una captura, no un FP
