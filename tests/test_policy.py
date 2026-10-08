"""Fase 5 — Tests de policy.py con veredictos de Jev simulados, sin red: todas las ramas de review_decision()."""

from src import policy
from src.models import ReviewVerdict, SqlResult
from src.questions.review import QUESTIONS

ROWS = SqlResult(columns=["n"], rows=[[99441]], row_count=1)


def verdict(next_step="answer", **traps) -> ReviewVerdict:
    """Un veredicto con todas las trampas bajas, salvo las que se pasen."""
    return ReviewVerdict(
        next_step=next_step,
        next_step_confidence=0.9,
        next_step_probabilities={"answer": 0.9, "retry": 0.05, "ask_user": 0.05},
        pitfalls={trap: 0.05 for trap in policy.TRAP_REASONS} | traps,
        model_id="jev-test",
        latency_s=0.1,
    )


def test_a_trap_beats_answer_and_becomes_the_reason():
    action = policy.review_decision(ROWS, verdict("answer", customer_id_not_unique=0.9), attempt=1)
    assert action.kind == "retry"
    assert action.reason == policy.TRAP_REASONS["customer_id_not_unique"]


def test_two_traps_give_both_reasons():
    action = policy.review_decision(ROWS, verdict("retry", customer_id_not_unique=0.9, wrong_grain=0.7), attempt=1)
    assert "customer_unique_id" in action.reason and "DISTINCT" in action.reason


def test_low_traps_and_answer_answer():
    assert policy.review_decision(ROWS, verdict("answer", join_fanout=0.2), attempt=1).kind == "answer"


def test_next_step_retry_without_a_trap_still_retries():
    assert policy.review_decision(ROWS, verdict("retry"), attempt=1).kind == "retry"


def test_ask_user_goes_through():
    assert policy.review_decision(ROWS, verdict("ask_user"), attempt=1).kind == "ask_user"


def test_sql_error_retries_without_a_verdict():
    failed = SqlResult(error="PostgreSQL error: column x does not exist")
    assert not policy.needs_jev(failed)
    assert policy.review_decision(failed, None, attempt=1).kind == "retry"


def test_zero_rows_retry_without_a_verdict():
    empty = SqlResult(columns=["n"], rows=[], row_count=0)
    assert not policy.needs_jev(empty)
    assert policy.review_decision(empty, None, attempt=1).kind == "retry"


def test_attempt_cap_answers_even_with_a_trap():
    action = policy.review_decision(ROWS, verdict("retry", customer_id_not_unique=0.99), attempt=policy.MAX_ATTEMPTS)
    assert action.kind == "answer"


def test_every_trap_question_has_a_reason():
    assert set(policy.TRAP_REASONS) == set(QUESTIONS) - {"next_step"}
