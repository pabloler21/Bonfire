"""Fase 5 — Jev después de cada run_sql, y respuesta en texto cuando ya no hay que reintentar.

- wrap_tool_call: corre run_sql, le pregunta a Jev (salvo error, cero filas o último intento), decide con policy.review_decision()
  y le agrega la decisión al ToolMessage que lee el LLM. Con `retry`, el motivo es lo que usa para reescribir.
- wrap_model_call: si la última decisión fue `answer` o `ask_user`, llama al modelo con tool_choice="none", así
  responde en texto. Con `ask_user`, ese texto es la pregunta aclaratoria.

Hooks verificados contra langchain 1.4.2 instalado (07/10/2026): no hay after_tool; "después de la tool" es
wrap_tool_call alrededor de handler(request). Un Command con un ToolMessage del mismo tool_call_id cierra la llamada.
"""

from operator import add
from typing import Annotated, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from src import policy
from src.models import SqlResult
from src.questions import review as jev


def _latest(_old: str, new: str) -> str:
    return new


class ReviewState(AgentState):
    # Con reducers, porque dos run_sql en paralelo escriben las dos claves en el mismo paso.
    review_attempts: NotRequired[Annotated[int, add]]  # consultas revisadas en esta pregunta
    review_kind: NotRequired[Annotated[str, _latest]]  # la última decisión: answer | retry | ask_user


class ReviewMiddleware(AgentMiddleware):
    state_schema = ReviewState

    def wrap_tool_call(self, request, handler):
        message = handler(request)
        if not isinstance(getattr(message, "artifact", None), SqlResult):
            return message  # otra tool, o un error antes de correr el SQL (argumentos inválidos): pasa tal cual

        # ponytail: dos run_sql en paralelo leen el mismo contador y comparten número de intento; el tope se
        # corre a lo sumo uno. Contar por llamada si el modelo empieza a pedir consultas en paralelo.
        attempt = request.state.get("review_attempts", 0) + 1
        result = message.artifact
        verdict = None
        if policy.needs_jev(result, attempt):
            verdict = jev.review(_question(request.state), request.tool_call["args"]["query"], result)
        action = policy.review_decision(result, verdict, attempt)

        reviewed = message.model_copy(update={"content": f"{message.content}\n\nReviewer: {action.kind}. {action.reason}"})
        return Command(update={"messages": [reviewed], "review_attempts": 1, "review_kind": action.kind})

    def wrap_model_call(self, request, handler):
        if request.state.get("review_kind") in ("answer", "ask_user"):
            request = request.override(tool_choice="none")
        return handler(request)


def _question(state) -> str:
    """La pregunta del usuario: el primer mensaje humano (el agente es de un solo turno)."""
    return next(m.text for m in state["messages"] if isinstance(m, HumanMessage))


def attempts(messages: list) -> list[dict]:
    """Cada run_sql de una corrida, leído de los mensajes: el SQL, su resultado, si lo vio Jev y qué decidió la
    revisión. La decisión sale de la línea `Reviewer:` que escribe wrap_tool_call. Lo usan la API y run_eval."""
    queries = {c["id"]: c["args"].get("query") for m in messages if isinstance(m, AIMessage) for c in m.tool_calls}
    found = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.artifact, SqlResult):
            decision, _, reason = m.text.rpartition("Reviewer: ")[2].partition(". ")
            found.append({
                "sql": queries.get(m.tool_call_id),
                "result": m.artifact,
                # la misma cuenta que wrap_tool_call: el intento número n se revisa si needs_jev(result, n)
                "reviewed": policy.needs_jev(m.artifact, len(found) + 1),
                "decision": decision,
                "reason": reason,
            })
    return found
