"""Fase 2 — create_agent: modelo, tool run_sql, esquema en el system prompt y límite de llamadas al modelo.
Langfuse (adelantado de la Fase 7, 29/09/2026): si hay keys en el entorno, cada invoke queda trazado.
Fase 5 — suma el middleware de revisión.
"""

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langfuse.langchain import CallbackHandler

from src.agent.tools import MAX_ROWS, run_sql
from src.config import generator_model, render_prompt, settings

# El system prompt vive en prompts/sql_agent.md (ruta en bonfire.toml). El esquema que incluye se leyó de la base real
# (information_schema y pg_constraint, 28/09/2026) y es solo estructura: las notas sobre trampas de Olist
# (customer_id por pedido, joins que duplican filas) son para Jev (Fase 4), no para el generador, así la Fase 2
# mide al agente sin ayuda. Si el prompt cambia, revisar PROMPT_FRAGMENTS en eval/run_behavior.py.
SYSTEM_PROMPT = render_prompt(settings.agent.system_prompt, max_rows=MAX_ROWS)


def build_agent(model: str | BaseChatModel | None = None, sql_tool: BaseTool = run_sql):
    """El agente de Bonfire. `model` acepta un string "proveedor:modelo" o una instancia (útil en tests).
    `sql_tool` solo cambia en eval/run_behavior.py, que siembra una review falsa (prompt injection indirecta).
    """
    agent = create_agent(
        model or generator_model(),  # modelo y límite: bonfire.toml
        tools=[sql_tool],
        system_prompt=SYSTEM_PROMPT,
        middleware=[ModelCallLimitMiddleware(run_limit=settings.agent.max_model_calls, exit_behavior="end")],
    )
    # Sin keys de Langfuse el agente es el mismo de siempre: sin callback y sin red (los tests dependen de esto).
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        agent = agent.with_config(callbacks=[CallbackHandler()])
    return agent
