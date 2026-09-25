"""Fase 1 — run_sql(query): corre sqlcheck (rechaza sin ejecutar), conecta como bonfire_agent en read-only,
statement_timeout de 10s, fetchmany(MAX_ROWS + 1) y errores de Postgres devueltos como texto.

Criterio de salida de la Fase 1, con la base levantada: uv run python -m src.agent.tools
"""

import os

import psycopg
from langchain.tools import tool

from src.models import SqlResult
from src.sqlcheck import check_sql

MAX_ROWS = 200  # placeholder: el valor final se fija sobre el split dev (plan.md, "Umbrales")
STATEMENT_TIMEOUT = "10s"


@tool(response_format="content_and_artifact")
def run_sql(query: str) -> tuple[str, SqlResult]:
    """Run ONE read-only PostgreSQL query against the Olist e-commerce database and return the rows.

    Only a single SELECT (or WITH ... SELECT, UNION) is allowed. Every join needs a condition.
    At most 200 rows come back; aggregate or filter when you need a summary.
    """
    # Capa 2: sqlcheck. Si rechaza, la base ni se entera.
    check = check_sql(query)
    if not check.ok:
        return _error(f"Rejected before running: {check.reason}")

    # Capa 3: una conexión nueva por llamada, así nada de lo que cambie una consulta en la sesión
    # sobrevive a la siguiente. Siempre como bonfire_agent (AGENT_DSN), nunca como admin.
    # Los errores de conexión no se capturan: son de infraestructura y el LLM no los puede arreglar.
    with psycopg.connect(
        os.environ["AGENT_DSN"],
        connect_timeout=5,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT}",  # además del default del rol
    ) as conn:
        conn.read_only = True  # además de los permisos del rol: defensa en profundidad
        try:
            cursor = conn.execute(query)
            rows = cursor.fetchmany(MAX_ROWS + 1)  # una de más para saber si hay más, sin contarlas
        except psycopg.Error as e:
            # Errores del SQL (columna inexistente, timeout...): el LLM los lee y reescribe.
            return _error(f"PostgreSQL error: {e}".strip())
        columns = [column.name for column in cursor.description]

    result = SqlResult(
        columns=columns,
        rows=[list(row) for row in rows[:MAX_ROWS]],
        row_count=min(len(rows), MAX_ROWS),
        truncated=len(rows) > MAX_ROWS,
    )
    return _as_text(result), result


def _error(message: str) -> tuple[str, SqlResult]:
    return message, SqlResult(error=message)


def _as_text(result: SqlResult) -> str:
    """Tabla legible para el LLM: columnas, filas y una línea final con la cantidad."""
    lines = [" | ".join(result.columns)]
    lines += [" | ".join("NULL" if value is None else str(value) for value in row) for row in result.rows]
    if result.truncated:
        lines.append(f"(first {MAX_ROWS} rows shown; the result has more. Aggregate or filter to see all of it.)")
    else:
        lines.append(f"({result.row_count} rows)")
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    for query in [
        # tienen que rechazarse sin ejecutar (criterio de salida de la Fase 1)
        "SET statement_timeout = 0; SELECT 1",
        "DELETE FROM orders",
        "SELECT * FROM orders, customers",
        # tienen que ejecutarse
        "SELECT customer_state, count(DISTINCT customer_unique_id) AS customers "
        "FROM customers GROUP BY 1 ORDER BY 2 DESC LIMIT 3",
        "SELECT no_such_column FROM orders",
        "SELECT order_id FROM orders",
    ]:
        text, result = run_sql.func(query)
        print(f"--- {query}\n{text[:300]}\n    artifact: row_count={result.row_count} truncated={result.truncated}\n")
