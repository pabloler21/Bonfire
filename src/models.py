"""Modelos Pydantic compartidos. Fase 1 — SqlCheck y SqlResult. Fase 4 — suma ReviewVerdict y NextAction."""

from typing import Any

from pydantic import BaseModel


class SqlCheck(BaseModel):
    """Veredicto de sqlcheck: si el SQL puede ejecutarse y, si no, por qué."""

    ok: bool
    reason: str | None = None  # en inglés: lo lee el LLM para reescribir


class SqlResult(BaseModel):
    """Resultado estructurado de run_sql. Es el artefacto que usa el middleware de Jev (Fase 5)."""

    columns: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0  # filas devueltas (como máximo MAX_ROWS)
    truncated: bool = False  # True si la consulta tenía más de MAX_ROWS filas
    error: str | None = None  # rechazo de sqlcheck o error de Postgres
