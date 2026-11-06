"""Shared literal cells and typed sort keys for terminal resource tables."""

from dataclasses import dataclass
from decimal import Decimal

SortValue = str | int | float | Decimal | tuple[int, float]


@dataclass(frozen=True)
class Value:
    text: str
    sort: SortValue | None


@dataclass(frozen=True)
class Column:
    key: str
    numeric: bool = False
