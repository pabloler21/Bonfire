"""Fase 5 — Tests del middleware de revisión con Jev reemplazado por una función, sin red: retry agrega el motivo,
answer/ask_user fuerzan texto, error y cero filas no llaman a Jev, tope de intentos."""

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import Field

from src import policy
from src.agent import tools
from src.middleware.review import ReviewMiddleware
from src.questions import review as jev
from tests.test_agent import ScriptedModel, sql_call
from tests.test_policy import verdict
from tests.test_tools import FakeConnection

QUESTION = "How many customers are there?"


class RecordingModel(ScriptedModel):
    """Además anota el tool_choice de cada llamada: así se ve cuándo el middleware obliga a responder en texto."""

    tool_choices: list = Field(default_factory=list)

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        self.tool_choices.append(tool_choice)
        return self


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    monkeypatch.setenv("AGENT_DSN", "postgresql://fake")
    monkeypatch.setattr(tools.psycopg, "connect", lambda dsn, **kw: FakeConnection(rows=[(99441,)], columns=("count",)))


def run(model) -> list[ToolMessage]:
    agent = create_agent(model, tools=[tools.run_sql], middleware=[ReviewMiddleware()])
    result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def no_jev(*args):
    pytest.fail("Jev must not be called")


def test_retry_adds_the_reason_and_answer_forces_text(monkeypatch):
    def fake_review(question, sql, result):
        assert question == QUESTION
        return verdict("answer", customer_id_not_unique=0.9) if "COUNT(*)" in sql else verdict("answer")

    monkeypatch.setattr(jev, "review", fake_review)
    model = RecordingModel(messages=iter([
        sql_call("SELECT COUNT(*) FROM customers", "c1"),
        sql_call("SELECT COUNT(DISTINCT customer_unique_id) FROM customers", "c2"),
        AIMessage(content="There are 96096 customers."),
    ]))

    first, second = run(model)

    assert first.content.endswith(f"Reviewer: retry. {policy.TRAP_REASONS['customer_id_not_unique']}")
    assert "Reviewer: answer." in second.content
    assert model.tool_choices == [None, None, "none"]  # la llamada después de `answer` no puede pedir tools


def test_ask_user_forces_a_clarifying_question_in_text(monkeypatch):
    monkeypatch.setattr(jev, "review", lambda *args: verdict("ask_user"))
    model = RecordingModel(messages=iter([sql_call("SELECT 1"), AIMessage(content="Do you mean revenue or items sold?")]))

    (message,) = run(model)

    assert "Reviewer: ask_user." in message.content
    assert model.tool_choices == [None, "none"]


def test_sql_error_skips_jev_and_retries(monkeypatch):
    monkeypatch.setattr(jev, "review", no_jev)
    model = RecordingModel(messages=iter([sql_call("DELETE FROM orders"), AIMessage(content="I can only read data.")]))

    (message,) = run(model)

    assert "Reviewer: retry. The query failed." in message.content


def test_zero_rows_skip_jev_and_retry(monkeypatch):
    monkeypatch.setattr(tools.psycopg, "connect", lambda dsn, **kw: FakeConnection(rows=[], columns=("count",)))
    monkeypatch.setattr(jev, "review", no_jev)
    model = RecordingModel(messages=iter([sql_call("SELECT 1"), AIMessage(content="No data.")]))

    (message,) = run(model)

    assert "Reviewer: retry. The query returned no rows." in message.content


def test_attempt_cap_stops_the_retries(monkeypatch):
    monkeypatch.setattr(jev, "review", lambda *args: verdict("retry", join_fanout=0.9))
    calls = [sql_call(f"SELECT {i}", f"c{i}") for i in range(policy.MAX_ATTEMPTS)]
    model = RecordingModel(messages=iter([*calls, AIMessage(content="Best effort: 99441, it may be wrong.")]))

    messages = run(model)

    assert len(messages) == policy.MAX_ATTEMPTS
    assert all("Reviewer: retry." in m.content for m in messages[:-1])
    assert "Reviewer: answer. Attempt limit reached." in messages[-1].content
    assert model.tool_choices[-1] == "none"
