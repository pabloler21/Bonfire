"""Tests de src/questions/review.py, sin red: Jev se reemplaza por una respuesta armada a mano."""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from src.models import SqlResult
from src.questions import review as rv

TRAPS = {"customer_id_not_unique", "join_fanout", "wrong_grain", "wrong_date_column", "undelivered_as_sales"}


def test_state_cuts_rows_and_turns_values_into_json():
    rows = [[Decimal("1.50"), datetime(2017, 1, 2)]] * (rv.MAX_ROWS_TO_JEV + 5)
    state = rv.build_review_state("q", "SELECT 1", SqlResult(columns=["a", "b"], rows=rows, row_count=len(rows)))
    assert len(state["result"]["rows"]) == rv.MAX_ROWS_TO_JEV
    assert state["result"]["rows_omitted"] is True
    assert state["result"]["rows"][0] == ["1.50", "2017-01-02 00:00:00"]


def test_small_result_goes_whole():
    state = rv.build_review_state("q", "SELECT 1", SqlResult(columns=["n"], rows=[[99441]], row_count=1))
    assert state["result"]["rows"] == [[99441]]
    assert state["result"]["rows_omitted"] is False


def test_review_builds_the_verdict_from_the_answers(monkeypatch):
    response = SimpleNamespace(
        model="jev-1.13.0",
        usage=SimpleNamespace(input_tokens=900, output_tokens=6),
        choices={"next_step": SimpleNamespace(choice="retry", confidence=0.8, probabilities={"answer": 0.1, "retry": 0.85, "ask_user": 0.05})},
        nouls={trap: SimpleNamespace(noul=0.9 if trap == "customer_id_not_unique" else 0.1) for trap in TRAPS},
    )
    sent = {}

    class FakeClient:
        def system_one(self, state, questions):
            sent.update(state=state, questions=questions)
            return response

    monkeypatch.setattr(rv, "_client", FakeClient)

    verdict = rv.review("How many customers are there?", "SELECT COUNT(*) FROM customers", SqlResult(rows=[[99441]], row_count=1))

    assert verdict.next_step == "retry"
    assert verdict.pitfalls["customer_id_not_unique"] == 0.9
    assert set(verdict.pitfalls) == TRAPS
    assert verdict.model_id == "jev-1.13.0"
    assert sent["questions"] is rv.QUESTIONS
    assert sent["state"]["sql"] == "SELECT COUNT(*) FROM customers"


def test_questions_cover_next_step_and_every_trap():
    assert set(rv.QUESTIONS) == {"next_step"} | TRAPS
