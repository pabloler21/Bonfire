# Fase 7 — Imagen de la API (src/api.py). La arma `docker compose up`; las keys llegan del .env al arrancar, no
# quedan adentro de la imagen. Basado en la guía de uv para Docker (docs.astral.sh/uv/guides/integration/docker).
FROM python:3.12-slim

# uv fijado en la misma versión que generó uv.lock
COPY --from=ghcr.io/astral-sh/uv:0.11.1 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Primero solo las dependencias: esta capa se reusa mientras uv.lock no cambie
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
