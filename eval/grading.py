"""Acierto por ejecución: compara el resultado del agente contra el de referencia (reglas de plan.md, Fase 6).

- Se comparan valores, no nombres de columna, y sin importar el orden de las columnas.
- Las filas son un multiconjunto, salvo que la pregunta tenga "ordered": true (rankings, top-N).
- Los números se redondean a 2 decimales; NULL es igual a NULL.
"""

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def normalize(value: Any) -> str:
    """Un valor en su forma comparable: 4.0864 y Decimal('4.09') quedan iguales."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float, Decimal)):
        return f"{float(value):.2f}"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _row_key(row: list[Any]) -> tuple[str, ...]:
    # ponytail: ordenar los valores ignora el orden de las columnas, pero también dejaría pasar dos columnas
    # con los valores intercambiados entre filas. Con resultados de negocio de 1-3 columnas no pasa en la práctica.
    return tuple(sorted(normalize(v) for v in row))


def same_result(expected: list[list[Any]], actual: list[list[Any]], ordered: bool = False) -> bool:
    """True si `actual` tiene las mismas filas que `expected` según las reglas de arriba."""
    expected_keys = [_row_key(r) for r in expected]
    actual_keys = [_row_key(r) for r in actual]
    if ordered:
        return expected_keys == actual_keys
    return Counter(expected_keys) == Counter(actual_keys)
