"""Fase 1 — Allow-list determinista con sqlglot: una sola sentencia de lectura, sin escritura/DDL/DCL/locks,
sin funciones con efectos y sin joins sin condición (producto cartesiano explícito).

No se conecta a la base: analiza el árbol del SQL. Es la barrera contra lo que los permisos de Postgres
no frenan (varias sentencias, cambios de sesión, productos cartesianos).
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from src.models import SqlCheck

# Raíces permitidas. Todo lo demás se rechaza, incluido exp.Command: lo que sqlglot no modela
# (VACUUM, EXPLAIN ANALYZE...) cae ahí, así que "no lo conozco" también es "no".
READ_ROOTS = (exp.Select, exp.SetOperation)  # SetOperation = UNION / INTERSECT / EXCEPT

# Nodos que no pueden aparecer en ningún lugar del árbol, aunque la raíz sea un SELECT.
# Ejemplo: WITH d AS (DELETE ... RETURNING *) SELECT * FROM d tiene raíz Select.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,           # escritura (también dentro de CTEs)
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable,      # DDL
    exp.Grant, exp.Revoke,                                   # DCL
    exp.Into,                                                # SELECT ... INTO crea una tabla
    exp.Lock,                                                # FOR UPDATE / FOR SHARE
    exp.Set, exp.Command, exp.Copy,
    exp.Transaction, exp.Commit, exp.Rollback,
)

# Funciones que el rol puede llamar pero que tienen efectos sobre la sesión o el servidor.
# Probado contra Postgres 18.6 como bonfire_agent (25/09/2026): set_config deja la sesión sin timeout,
# pg_terminate_backend / pg_advisory_lock / pg_sleep están permitidas. Ninguna hace falta para analizar datos.
# ponytail: lista cerrada de prefijos; si aparece otra función con efectos, se agrega acá con su test.
FORBIDDEN_FUNCTION_PREFIXES = ("set_config", "pg_sleep", "pg_terminate_backend", "pg_cancel_backend", "pg_advisory")


def check_sql(sql: str) -> SqlCheck:
    """Decide si `sql` puede ejecutarse. Las reglas van de la más grave a la más fina; la primera que falla corta."""
    # R1: tiene que parsear.
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        return _reject(f"could not parse the SQL ({str(e).splitlines()[0]})")

    # R2: exactamente una sentencia. Frena "SET statement_timeout = 0; SELECT ...".
    if len(statements) != 1:
        return _reject(f"send exactly one SQL statement, got {len(statements)}")

    root = statements[0]
    while isinstance(root, exp.Subquery):  # "(SELECT ...)" entre paréntesis
        root = root.this

    # R3: la raíz tiene que ser una lectura (allow-list).
    if not isinstance(root, READ_ROOTS):
        return _reject(f"only SELECT queries are allowed, got {type(root).__name__.upper()}")

    # R4: nada que escriba, bloquee o cambie la sesión en ningún nodo del árbol.
    if node := root.find(*FORBIDDEN_NODES):
        return _reject(f"the query contains a forbidden {type(node).__name__.upper()} clause")
    for func in root.find_all(exp.Anonymous):  # sqlglot deja como Anonymous las funciones que no tipa
        if func.name.lower().startswith(FORBIDDEN_FUNCTION_PREFIXES):
            return _reject(f"the function {func.name}() is not allowed")

    # R5: ningún join sin condición, en ningún SELECT (incluidas subconsultas y CTEs).
    for select in root.find_all(exp.Select):
        if table := _unconditioned_join(select):
            return _reject(
                f"join without a condition on '{table}' (cartesian product). "
                "Add an ON or USING condition; for a one-row total, use a scalar subquery"
            )

    return SqlCheck(ok=True)


def _reject(reason: str) -> SqlCheck:
    return SqlCheck(ok=False, reason=reason)


def _unconditioned_join(select: exp.Select) -> str | None:
    """Devuelve el nombre de la primera tabla unida sin condición, o None si todos los joins tienen una."""
    where = select.args.get("where")
    for join in select.args.get("joins") or []:
        if join.args.get("on") or join.args.get("using"):
            continue
        if join.args.get("method") == "NATURAL" or isinstance(join.this, exp.Lateral):
            continue  # NATURAL une por columnas homónimas; LATERAL se correlaciona adentro
        table = join.this.alias_or_name
        # Join "viejo": FROM a, b WHERE a.x = b.x. Es correcto y no hay que rechazarlo.
        if where is None or not _where_links(where, table):
            return table
    return None


def _where_links(where: exp.Where, table: str) -> bool:
    """True si el WHERE tiene una igualdad entre una columna de `table` y una columna de otra tabla."""
    table = table.lower()
    for eq in where.find_all(exp.EQ):
        left, right = eq.this, eq.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            tables = {left.table.lower(), right.table.lower()}
            if table in tables and len(tables) == 2 and "" not in tables:
                return True
    return False
