"""Fase 2 — create_agent: modelo, tool run_sql, esquema en el system prompt y límite de llamadas al modelo.
Langfuse (adelantado de la Fase 7, 29/09/2026): si hay keys en el entorno, cada invoke queda trazado.
Fase 5 — el middleware de revisión: Jev después de cada run_sql (src/middleware/review.py).
"""

import os

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langfuse.langchain import CallbackHandler

from src.agent.tools import MAX_ROWS, run_sql
from src.config import generator_model, render_prompt, settings
from src.middleware.review import ReviewMiddleware

# El system prompt vive en prompts/sql_agent.md (ruta en bonfire.toml). El esquema que incluye se leyó de la base real
# (information_schema y pg_constraint, 28/09/2026) y es solo estructura: las notas sobre trampas de Olist
# (customer_id por pedido, joins que duplican filas) son para Jev (Fase 4), no para el generador, así la Fase 2
# mide al agente sin ayuda.
SYSTEM_PROMPT = render_prompt(settings.agent.system_prompt, max_rows=MAX_ROWS)


def build_agent(model: str | BaseChatModel | None = None, review: bool = True):
    """El agente de Bonfire. `model` acepta un string "proveedor:modelo" o una instancia (útil en tests).

    `review=False` arma el agente de la Fase 2, sin Jev: lo usan los tests del generador.
    """
    middleware = [ModelCallLimitMiddleware(run_limit=settings.agent.max_model_calls, exit_behavior="end")]
    if review:
        middleware.append(ReviewMiddleware())
    agent = create_agent(
        model or generator_model(),  # modelo y límite: bonfire.toml
        tools=[run_sql],
        system_prompt=SYSTEM_PROMPT,
        middleware=middleware,
    )
    # Sin keys de Langfuse el agente es el mismo de siempre: sin callback y sin red (los tests dependen de esto).
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        agent = agent.with_config(callbacks=[CallbackHandler()])
    return agent
