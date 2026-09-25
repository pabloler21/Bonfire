"""Fase 1 — Tests de sqlcheck.py, sin red: cada regla de rechazo y SELECT legítimos que no se rechazan."""

import pytest

from src.sqlcheck import check_sql

# Consultas legítimas. Rechazar una de estas es un falso positivo: el agente no podría responder.
ALLOWED = [
    "SELECT count(*) FROM orders",
    "SELECT count(*) FROM orders;",  # el ; final no cuenta como segunda sentencia
    "(SELECT 1)",
    "SELECT o.order_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
    "SELECT * FROM orders JOIN order_items USING (order_id)",
    "SELECT * FROM orders NATURAL JOIN order_items",
    # join "viejo": la condición está en el WHERE
    "SELECT * FROM orders o, customers c WHERE o.customer_id = c.customer_id",
    "SELECT * FROM orders, customers WHERE orders.customer_id = customers.customer_id",
    "SELECT * FROM orders o CROSS JOIN customers c WHERE o.customer_id = c.customer_id",
    "SELECT * FROM orders o LEFT JOIN order_reviews r ON r.order_id = o.order_id",
    "SELECT * FROM orders o, LATERAL (SELECT 1 AS x) l",
    "WITH t AS (SELECT customer_state, count(*) AS n FROM customers GROUP BY 1) SELECT * FROM t",
    "SELECT customer_state FROM customers UNION SELECT seller_state FROM sellers",
    "SELECT * FROM orders WHERE customer_id IN (SELECT customer_id FROM customers WHERE customer_state = 'SP')",
    "SELECT order_id, sum(price) OVER (PARTITION BY order_id) FROM order_items",
    "SELECT count(*) FROM customers WHERE customer_city LIKE 'sao%'",
    # las palabras peligrosas en texto o en comentarios no son código
    "SELECT 'DELETE FROM orders' AS texto -- DROP TABLE orders",
    "SELECT 1 /* ; SET statement_timeout = 0 */",
]

# (SQL, fragmento que tiene que aparecer en el motivo)
REJECTED = [
    # R1: no parsea
    ("SELEC 1 FROM", "could not parse"),
    ("SELECT * FROM", "could not parse"),
    # R2: una sola sentencia
    ("", "exactly one"),
    ("SET statement_timeout = 0; SELECT 1", "exactly one"),
    ("SELECT 1; SELECT 2", "exactly one"),
    # R3: la raíz tiene que ser lectura
    ("DELETE FROM orders", "only SELECT"),
    ("INSERT INTO orders (order_id) VALUES ('x')", "only SELECT"),
    ("UPDATE orders SET order_status = 'x'", "only SELECT"),
    ("DROP TABLE orders", "only SELECT"),
    ("TRUNCATE orders", "only SELECT"),
    ("GRANT SELECT ON orders TO PUBLIC", "only SELECT"),
    ("SET statement_timeout = 0", "only SELECT"),
    ("VACUUM orders", "only SELECT"),
    ("EXPLAIN ANALYZE SELECT 1", "only SELECT"),
    ("BEGIN", "only SELECT"),
    # R4: escrituras, bloqueos y funciones con efectos escondidos en un SELECT
    ("WITH d AS (DELETE FROM orders RETURNING *) SELECT count(*) FROM d", "DELETE"),
    ("WITH u AS (UPDATE orders SET order_status = 'x' RETURNING *) SELECT * FROM u", "UPDATE"),
    ("SELECT * INTO nueva FROM orders", "INTO"),
    ("SELECT * FROM orders FOR UPDATE", "LOCK"),
    ("SELECT * FROM orders FOR SHARE", "LOCK"),
    ("SELECT set_config('statement_timeout', '0', false)", "set_config"),
    ("SELECT pg_sleep(60)", "pg_sleep"),
    ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity", "pg_terminate_backend"),
    ("SELECT pg_advisory_lock(1)", "pg_advisory_lock"),
    # R5: producto cartesiano
    ("SELECT * FROM orders, customers", "cartesian"),
    ("SELECT * FROM orders CROSS JOIN customers", "cartesian"),
    ("SELECT * FROM orders o, customers c WHERE o.order_status = 'delivered'", "cartesian"),
    ("SELECT * FROM orders o, customers c, sellers s WHERE o.customer_id = c.customer_id", "'s'"),
    ("SELECT * FROM (SELECT * FROM orders, customers) x", "cartesian"),
    ("WITH t AS (SELECT * FROM orders, sellers) SELECT count(*) FROM t", "cartesian"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    result = check_sql(sql)
    assert result.ok, result.reason


@pytest.mark.parametrize(("sql", "reason"), REJECTED)
def test_rejected(sql, reason):
    result = check_sql(sql)
    assert not result.ok
    assert reason in result.reason
