"""Bounded server Table metadata, independent of transport and terminal widgets."""

import json
import math
from dataclasses import asdict, replace
from typing import Any, cast

from kuberich.domain.resources import (
    MAX_RESOURCE_ITEMS,
    ApiResource,
    ResourceRecord,
    ServerCell,
    ServerColumn,
    ServerRow,
    resource_object,
    resource_record,
    resource_text,
)
from kuberich.domain.watches import EventType, WatchEvent, watch_event
from kuberich.errors import AppError

TABLE_ACCEPT = "application/json;as=Table;g=meta.k8s.io;v=v1,application/json"
MAX_COLUMNS = 64
MAX_TABLE_METADATA_BYTES = 256 * 1024
MAX_CELL_CHARACTERS = 65536
_TYPES = frozenset({"string", "integer", "number", "boolean", "date"})


class TableUnavailable(AppError):
    def __init__(self) -> None:
        super().__init__("Server Table metadata is unavailable; ordinary JSON is required.")


def is_table(value: dict[str, Any]) -> bool:
    version = value.get("apiVersion")
    return (
        value.get("kind") == "Table"
        and isinstance(version, str)
        and version.startswith("meta.k8s.io/")
    )


def _text(value: Any, maximum: int, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value):
        raise TableUnavailable()
    return value


def _columns(value: Any) -> tuple[ServerColumn, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_COLUMNS:
        raise TableUnavailable()
    columns = []
    for item in value:
        if not isinstance(item, dict):
            raise TableUnavailable()
        kind = item.get("type")
        priority = item.get("priority", 0)
        if (
            not isinstance(kind, str)
            or kind not in _TYPES
            or type(priority) is not int
            or not 0 <= priority < 2**31
        ):
            raise TableUnavailable()
        columns.append(
            ServerColumn(
                _text(item.get("name"), 128, empty=False),
                kind,
                _text(item.get("format", ""), 64),
                _text(item.get("description", ""), 4096),
                priority,
            )
        )
    return tuple(columns)


def _cell(value: Any, kind: str) -> ServerCell:
    if value is None:
        return None
    valid = (
        kind in {"string", "date"} and isinstance(value, str) and len(value) <= MAX_CELL_CHARACTERS
    ) or (kind == "boolean" and type(value) is bool)
    valid = valid or (
        kind in {"integer", "number"} and type(value) is int and -(2**63) <= value < 2**63
    )
    valid = valid or (kind == "number" and type(value) is float and math.isfinite(value))
    if not valid:
        raise TableUnavailable()
    return cast(ServerCell, value)


def _size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except UnicodeError:
        raise TableUnavailable() from None


class TableDecoder:
    """Own headers within one paged LIST or opened watch, never across streams."""

    def __init__(self, resource: ApiResource, namespace: str | None) -> None:
        self.resource, self.namespace = resource, namespace
        self.columns: tuple[ServerColumn, ...] | None = None
        self._column_bytes = 0

    def _rows(self, value: dict[str, Any], *, single: bool) -> list[Any]:
        if value.get("apiVersion") != "meta.k8s.io/v1" or value.get("kind") != "Table":
            raise TableUnavailable()
        headers = value.get("columnDefinitions")
        if headers:
            columns = _columns(headers)
            if self.columns is not None and columns != self.columns:
                raise TableUnavailable()
            size = _size([asdict(column) for column in columns])
            if size > MAX_TABLE_METADATA_BYTES:
                raise TableUnavailable()
            self.columns, self._column_bytes = columns, size
        elif headers not in (None, []) or self.columns is None:
            raise TableUnavailable()
        rows = value.get("rows")
        if (
            not isinstance(rows, list)
            or len(rows) > MAX_RESOURCE_ITEMS
            or (single and len(rows) != 1)
        ):
            raise TableUnavailable()
        return rows

    def _object(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict) or not isinstance(row.get("object"), dict):
            raise TableUnavailable()
        return resource_object(row["object"])

    def _record(self, row: Any) -> ResourceRecord:
        obj = self._object(row)
        if obj.get("apiVersion") is None or obj.get("kind") in (None, "PartialObjectMetadata"):
            raise TableUnavailable()
        assert self.columns is not None
        raw_cells = row.get("cells")
        if not isinstance(raw_cells, list) or len(raw_cells) != len(self.columns):
            raise TableUnavailable()
        cells = tuple(
            _cell(value, column.type) for value, column in zip(raw_cells, self.columns, strict=True)
        )
        size = self._column_bytes + _size(cells)
        record = resource_record(self.resource, obj, self.namespace)
        return replace(record, server=ServerRow(self.columns, cells, size))

    def records(self, value: dict[str, Any], *, single: bool = False) -> tuple[ResourceRecord, ...]:
        return tuple(self._record(row) for row in self._rows(value, single=single))

    def event(self, value: Any) -> WatchEvent:
        payload = resource_object(value)
        obj = resource_object(payload.get("object"))
        if not is_table(obj):
            return watch_event(self.resource, payload, self.namespace)
        rows = self._rows(obj, single=True)
        if payload.get("type") == "BOOKMARK":
            # A bookmark has a checkpoint, not a concrete resource name/UID.
            metadata = resource_object(self._object(rows[0]).get("metadata"))
            return WatchEvent(EventType.BOOKMARK, resource_text(metadata.get("resourceVersion")))
        record = self._record(rows[0])
        event = watch_event(
            self.resource, {"type": payload.get("type"), "object": record.manifest}, self.namespace
        )
        return replace(event, record=record)
