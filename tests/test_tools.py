"""Fase 1 — Tests de run_sql sin red: la conexión a Postgres se reemplaza por una falsa."""

from types import SimpleNamespace

import psycopg
import pytest

from src.agent import tools


class FakeConnection:
    """Imita lo que run_sql usa de psycopg: context manager, read_only, execute(), fetchmany() y description."""

    def __init__(self, rows=(), columns=("n",), error=None):
        self.rows, self.columns, self.error = list(rows), columns, error
        self.read_only = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query):
        self.executed.append(query)
        if self.error:
            raise self.error
        return SimpleNamespace(
            fetchmany=lambda size: self.rows[:size],
            description=[SimpleNamespace(name=c) for c in self.columns],
        )


@pytest.fixture
def connect(monkeypatch):
    """Reemplaza psycopg.connect dentro de tools; devuelve una función para elegir qué conexión falsa usar."""
    monkeypatch.setenv("AGENT_DSN", "postgresql://fake")
    calls = []

    def use(conn):
        def fake_connect(dsn, **kwargs):
            calls.append((dsn, kwargs))
            return conn
        monkeypatch.setattr(tools.psycopg, "connect", fake_connect)
        return calls

    return use


@pytest.mark.parametrize(
    "query",
    ["SET statement_timeout = 0; SELECT 1", "DELETE FROM orders", "SELECT * FROM orders, customers"],
)
def test_rejected_queries_never_connect(connect, query):
    calls = connect(FakeConnection())
    text, result = tools.run_sql.func(query)
    assert text.startswith("Rejected before running:")
    assert result.error == text
    assert calls == []  # sqlcheck rechazó: la base ni se entera


def test_connects_as_agent_read_only_with_timeout(connect):
    conn = FakeConnection(rows=[(1,)])
    calls = connect(conn)
    tools.run_sql.func("SELECT 1 AS n")
    (dsn, kwargs), = calls
    assert dsn == "postgresql://fake"  # AGENT_DSN
    assert "statement_timeout=10s" in kwargs["options"]
    assert conn.read_only is True
    assert conn.executed == ["SELECT 1 AS n"]  # el SQL del LLM se ejecuta tal cual, sin LIMIT agregado


def test_rows_come_back_as_text_and_artifact(connect):
    connect(FakeConnection(rows=[("SP", 3), ("RJ", None)], columns=("state", "n")))
    text, result = tools.run_sql.func("SELECT state, n FROM t")
    assert text == "state | n\nSP | 3\nRJ | NULL\n(2 rows)"
    assert result.columns == ["state", "n"]
    assert result.rows == [["SP", 3], ["RJ", None]]
    assert (result.row_count, result.truncated, result.error) == (2, False, None)


def test_more_than_max_rows_is_truncated(connect):
    connect(FakeConnection(rows=[(i,) for i in range(tools.MAX_ROWS + 50)]))
    text, result = tools.run_sql.func("SELECT n FROM t")
    assert result.row_count == tools.MAX_ROWS
    assert len(result.rows) == tools.MAX_ROWS
    assert result.truncated
    assert f"first {tools.MAX_ROWS} rows shown" in text


def test_exactly_max_rows_is_not_truncated(connect):
    connect(FakeConnection(rows=[(i,) for i in range(tools.MAX_ROWS)]))
    _, result = tools.run_sql.func("SELECT n FROM t")
    assert (result.row_count, result.truncated) == (tools.MAX_ROWS, False)


def test_postgres_errors_come_back_as_text(connect):
    connect(FakeConnection(error=psycopg.errors.UndefinedColumn('column "x" does not exist')))
    text, result = tools.run_sql.func("SELECT x FROM orders")
    assert text == 'PostgreSQL error: column "x" does not exist'
    assert result.error == text
    assert result.rows == []
