"""Safe generic Table projection and transient column selection, without widgets."""

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Self

from kuberich.domain.inspection import REDACTED, redacted
from kuberich.domain.pods import utc_now
from kuberich.domain.registry import Column, ResourceDefinition, ResourceRow, Value
from kuberich.domain.resources import ApiResource, ResourceRecord, ServerCell, ServerColumn
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text

_DURATION = re.compile(r"(?:\d+(?:\.\d+)?[ywdhms])+")
_PART = re.compile(r"(\d+(?:\.\d+)?)([ywdhms])")
_SECONDS = {"y": 31536000, "w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def _date(value: str, now: datetime) -> float | None:
    if _DURATION.fullmatch(value):
        # Kubernetes printers emit elapsed durations; larger durations are older.
        result = sum(float(amount) * _SECONDS[unit] for amount, unit in _PART.findall(value))
        return result if math.isfinite(result) else None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - stamp).total_seconds() if stamp.tzinfo is not None else None


def _value(column: ServerColumn, cell: ServerCell, *, opaque: bool, now: datetime) -> Value:
    # Metadata alone cannot establish that an opaque payload is safe to show.
    if opaque or redacted(cell, key=column.name.casefold()) == REDACTED:
        return Value(REDACTED, None)
    if cell is None:
        return Value("—", None)
    if column.type == "boolean" and type(cell) is bool:
        return Value("true" if cell else "false", int(cell))
    if column.type in {"integer", "number"} and type(cell) is int and -(2**63) <= cell < 2**63:
        return Value(str(cell), cell)
    if column.type == "number" and type(cell) is float and math.isfinite(cell):
        return Value(str(cell), cell)
    if column.type in {"string", "date"} and isinstance(cell, str):
        literal = safe_text(cell).plain
        return Value(literal, _date(cell, now) if column.type == "date" else literal.casefold())
    return Value("—", None)


@dataclass(frozen=True)
class CustomLayout:
    resource: ApiResource
    headers: tuple[ServerColumn, ...] = ()
    visible: tuple[int, ...] = ()

    @classmethod
    def build(cls, resource: ApiResource, headers: tuple[ServerColumn, ...]) -> Self:
        # Namespace/name/age always come from verified metadata. A server's name
        # or age cell cannot replace the identity used for selection/inspection.
        visible = tuple(
            index
            for index, column in enumerate(headers)
            if column.format != "name" and column.name.casefold() != "age" and column.priority == 0
        )
        return cls(resource, headers, visible)

    @property
    def definition(self) -> ResourceDefinition:
        return ResourceDefinition(
            self.resource.name,
            self.resource.group,
            self.resource.namespaced,
            (),
            tuple(
                Column(f"c{index + 1}", self.headers[index].type != "string")
                for index in self.visible
            ),
        )

    def label(self, key: str) -> str:
        labels = {
            f"c{index + 1}": safe_text(self.headers[index].name).plain for index in self.visible
        }
        return labels.get(key, key.upper())

    def configure(self, keys: tuple[str, ...]) -> Self:
        available = {
            f"c{index + 1}": index
            for index, column in enumerate(self.headers)
            if column.format != "name" and column.name.casefold() != "age"
        }
        if (
            len(keys) > 64
            or len(set(keys)) != len(keys)
            or any(key not in available for key in keys)
        ):
            raise AppError("Invalid custom columns; the current view is retained.")
        return replace(self, visible=tuple(available[key] for key in keys))

    def row(self, record: ResourceRecord, *, now: datetime | None = None) -> ResourceRow:
        if record.uid is None:
            raise AppError("Live custom-resource rows require an API object UID.")
        server = record.server
        # A renewed schema must not reinterpret retained old positional cells.
        compatible = (
            server is not None
            and server.columns == self.headers
            and len(server.cells) == len(self.headers)
        )
        opaque = self.resource.kind in {"Secret", "ConfigMap"}
        moment = now or utc_now()
        fields = {
            "namespace": Value(record.namespace or "—", record.namespace or ""),
            "name": Value(record.name, record.name.casefold()),
            "age": Value("—", -record.created_at.timestamp() if record.created_at else None),
        }
        for index in self.visible:
            fields[f"c{index + 1}"] = (
                _value(self.headers[index], server.cells[index], opaque=opaque, now=moment)
                if compatible and server is not None
                else Value("—", None)
            )
        return ResourceRow(
            record.uid,
            record.namespace or "—",
            record.name,
            tuple(fields[column.key] for column in self.definition.columns),
            record.created_at,
        )
