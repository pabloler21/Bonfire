"""Modelos Pydantic compartidos. Fase 1 — SqlCheck y SqlResult. Fase 4 — ReviewVerdict. Fase 5 — NextAction."""

from typing import Any, Literal

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


class ReviewVerdict(BaseModel):
    """Lo que dijo Jev sobre un resultado (src/questions/review.py). Lo consume policy.py en la Fase 5."""

    next_step: Literal["answer", "retry", "ask_user"]
    next_step_confidence: float
    next_step_probabilities: dict[str, float]
    pitfalls: dict[str, float]  # Noul: probabilidad de "sí", por trampa
    model_id: str  # la versión que devolvió la API, no el alias pedido (jev-latest)
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float


class NextAction(BaseModel):
    """Qué hace el agente con un resultado (policy.review_decision). `reason` lo lee el LLM: va en inglés."""

    kind: Literal["answer", "retry", "ask_user"]
    reason: str
