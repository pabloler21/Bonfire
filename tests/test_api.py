"""Fase 7 — Tests de src/api.py, sin red: el agente real con un LLM guionado, la base falsa y Jev reemplazado."""

import pytest
from fastapi.testclient import TestClient
from langchain.agents import create_agent
from langchain_core.messages import AIMessage

from src import api
from src.agent import tools
from src.middleware.review import ReviewMiddleware
from src.questions import review as jev
from tests.test_agent import sql_call
from tests.test_policy import verdict
from tests.test_review_middleware import RecordingModel
from tests.test_tools import FakeConnection


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("AGENT_DSN", "postgresql://fake")
    monkeypatch.setattr(tools.psycopg, "connect", lambda dsn, **kw: FakeConnection(rows=[(99441,)], columns=("count",)))
    monkeypatch.setattr(api, "load_dotenv", lambda: None)  # sin esto, el .env real metería las keys de Langfuse


def client_for(monkeypatch, *turns) -> TestClient:
    model = RecordingModel(messages=iter(turns))
    monkeypatch.setattr(api, "build_agent", lambda: create_agent(model, tools=[tools.run_sql], middleware=[ReviewMiddleware()]))
    return TestClient(api.app)


def test_ask_returns_the_answer_and_every_attempt(monkeypatch):
    monkeypatch.setattr(jev, "review", lambda q, sql, r: verdict("answer", customer_id_not_unique=0.9 if "COUNT(*)" in sql else 0.1))
    with client_for(monkeypatch,
                    sql_call("SELECT COUNT(*) FROM customers", "c1"),
                    sql_call("SELECT COUNT(DISTINCT customer_unique_id) FROM customers", "c2"),
                    AIMessage(content="There are 96,096 customers.")) as client:
        response = client.post("/ask", json={"question": "How many customers are there?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "There are 96,096 customers." and body["kind"] == "answer"
    assert [a["decision"] for a in body["attempts"]] == ["retry", "answer"]
    assert body["attempts"][0] == {"sql": "SELECT COUNT(*) FROM customers", "error": None, "row_count": 1,
                                   "decision": "retry", "reason": body["attempts"][0]["reason"]}
    assert "customer_unique_id" in body["attempts"][0]["reason"]


def test_ask_user_comes_back_as_a_clarification(monkeypatch):
    monkeypatch.setattr(jev, "review", lambda *args: verdict("ask_user"))
    with client_for(monkeypatch, sql_call("SELECT 1"), AIMessage(content="Do you mean revenue or items sold?")) as client:
        body = client.post("/ask", json={"question": "What were the sales?"}).json()

    assert body["kind"] == "clarification"
    assert body["answer"] == "Do you mean revenue or items sold?"


def test_an_empty_question_is_rejected(monkeypatch):
    with client_for(monkeypatch) as client:
        assert client.post("/ask", json={"question": ""}).status_code == 422
