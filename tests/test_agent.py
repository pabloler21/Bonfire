"""Fase 2 — El agente armado de punta a punta, sin red: un LLM con respuestas guionadas y una base falsa."""

from itertools import count

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langfuse.langchain import CallbackHandler

from src.agent import build, tools
from src.models import SqlResult
from tests.test_tools import FakeConnection


class ScriptedModel(GenericFakeChatModel):
    """Devuelve los mensajes guionados en orden. bind_tools no hace nada: las tool calls ya vienen escritas."""

    def bind_tools(self, tools, **kwargs):
        return self


def sql_call(query: str, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": "run_sql", "args": {"query": query}, "id": call_id}])


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)  # sin keys: sin trazas, sin red
    monkeypatch.setenv("AGENT_DSN", "postgresql://fake")
    monkeypatch.setattr(tools.psycopg, "connect", lambda dsn, **kw: FakeConnection(rows=[(99441,)], columns=("count",)))


def test_agent_runs_the_tool_and_answers():
    model = ScriptedModel(messages=iter([sql_call("SELECT count(*) FROM orders"), AIMessage(content="There are 99441 orders.")]))
    result = build.build_agent(model).invoke({"messages": [{"role": "user", "content": "How many orders?"}]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content == "count\n99441\n(1 rows)"  # lo que lee el LLM
    assert isinstance(tool_message.artifact, SqlResult)  # lo que va a leer el middleware de Jev (Fase 5)
    assert tool_message.artifact.rows == [[99441]]
    assert result["messages"][-1].content == "There are 99441 orders."


def test_rejected_sql_goes_back_to_the_model_as_text():
    model = ScriptedModel(messages=iter([sql_call("DELETE FROM orders"), AIMessage(content="I can only read data.")]))
    result = build.build_agent(model).invoke({"messages": [{"role": "user", "content": "Delete all orders"}]})

    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("Rejected before running:")
    assert result["messages"][-1].content == "I can only read data."


def test_model_call_limit_stops_a_runaway_loop():
    # Un modelo que nunca deja de llamar a la tool: el límite tiene que cortar el loop sin excepción.
    # Un mensaje nuevo por vuelta: LangGraph combina los mensajes por id, y repetir el mismo objeto los pisaría.
    model = ScriptedModel(messages=(sql_call("SELECT 1", f"call_{i}") for i in count()))
    result = build.build_agent(model).invoke({"messages": [{"role": "user", "content": "loop"}]})

    model_calls = [m for m in result["messages"] if isinstance(m, AIMessage) and m.tool_calls]
    assert len(model_calls) == build.MAX_MODEL_CALLS


def test_no_langfuse_keys_means_no_callbacks():
    agent = build.build_agent(ScriptedModel(messages=iter([])))
    assert not (agent.config or {}).get("callbacks")


def test_langfuse_keys_attach_the_callback(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")  # el cliente usa un NoOpTracer: nada sale a la red
    agent = build.build_agent(ScriptedModel(messages=iter([])))
    assert [type(c) for c in agent.config["callbacks"]] == [CallbackHandler]
