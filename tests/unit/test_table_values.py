"""Shared values preserve the existing public registry and sort behavior."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from kuberich.domain import registry
from kuberich.domain.table_values import Column, Value


def test_registry_reexports_shared_immutable_cells_and_columns():
    assert registry.Value is Value and registry.Column is Column
    value = Value("literal [not markup]", Decimal("2"))
    column = Column("priority", True)
    with pytest.raises(FrozenInstanceError):
        value.text = "changed"
    with pytest.raises(FrozenInstanceError):
        column.numeric = False
    assert value.text == "literal [not markup]" and value.sort == Decimal("2")


@pytest.mark.parametrize(
    "descending,expected", [(False, ("a", "b", "c", "unknown")), (True, ("c", "a", "b", "unknown"))]
)
def test_extracted_numeric_values_keep_stable_ties_and_unknowns_last(descending, expected):
    def row(name, value):
        return registry.ResourceRow(
            name,
            "team",
            name,
            (Value(name, name), Value(str(value), value), Value("—", None)),
            None,
        )

    rows = (row("unknown", None), row("c", 10), row("b", 2), row("a", Decimal("2")))
    assert tuple(r.name for r in registry.order_resources(rows, 1, descending)) == expected
