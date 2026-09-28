"""Tests de eval/grading.py, sin red."""

from datetime import datetime
from decimal import Decimal

import pytest

from eval.grading import normalize, same_result


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (4.0864, Decimal("4.09")),  # redondeo a 2 decimales
        (99441, Decimal("99441")),  # int y Decimal son el mismo número
        (None, None),  # NULL es igual a NULL
        (datetime(2017, 10, 2, 10, 56, 33), datetime(2017, 10, 2, 10, 56, 33)),
    ],
)
def test_normalize_equal(a, b):
    assert normalize(a) == normalize(b)


def test_normalize_different():
    assert normalize(4.08) != normalize(4.09)
    assert normalize(None) != normalize("")


def test_column_names_and_order_are_ignored():
    assert same_result([["SP", 41746]], [[41746, "SP"]])


def test_rows_are_a_multiset_by_default():
    assert same_result([["SP", 1], ["RJ", 2]], [["RJ", 2], ["SP", 1]])
    assert not same_result([["SP", 1], ["SP", 1]], [["SP", 1]])  # las repeticiones cuentan


def test_ordered_questions_respect_row_order():
    assert same_result([["SP"], ["RJ"]], [["SP"], ["RJ"]], ordered=True)
    assert not same_result([["SP"], ["RJ"]], [["RJ"], ["SP"]], ordered=True)


def test_extra_or_missing_columns_fail():
    assert not same_result([["SP", 1]], [["SP", 1, 0.5]])
    assert not same_result([["SP", 1]], [["SP"]])


def test_empty_results():
    assert same_result([], [])
    assert not same_result([["x"]], [])
