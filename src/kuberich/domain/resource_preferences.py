"""Version-pinned display preferences independent of widgets and resource values."""

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Literal, cast

from kuberich.domain.resources import ServerColumn, api_segment
from kuberich.errors import AppError

type Alignment = Literal["auto", "left", "center", "right"]
type Justification = Literal["left", "center", "right"]
MAX_VIEW_COLUMNS = 67


def field_key(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is None:
        raise AppError("View fields must be documented lowercase field keys.")
    return value


def resource_key(value: object) -> str:
    if not isinstance(value, str) or len(value) > 775:
        raise AppError("Views use VERSION/RESOURCE or GROUP/VERSION/RESOURCE identifiers.")
    parts = value.removeprefix("server:").split("/")
    if len(parts) not in {2, 3} or (len(parts) == 3 and parts[0] == "core"):
        raise AppError(
            "Views use VERSION/RESOURCE or GROUP/VERSION/RESOURCE identifiers; omit core."
        )
    for part in parts:
        api_segment(part)
    return value


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    width: int | None = None
    alignment: Alignment = "auto"

    def __post_init__(self) -> None:
        field_key(self.key)
        if self.width is not None and (type(self.width) is not int or not 1 <= self.width <= 256):
            raise AppError("Column width must be null/auto or an integer from 1 to 256.")
        if not isinstance(self.alignment, str) or self.alignment not in {
            "auto",
            "left",
            "center",
            "right",
        }:
            raise AppError("Column alignment must be auto, left, center or right.")

    @property
    def justify(self) -> Justification | None:
        return None if self.alignment == "auto" else self.alignment

    def mapping(self) -> dict[str, object]:
        return {"key": self.key, "width": self.width, "alignment": self.alignment}


@dataclass(frozen=True)
class ViewSpec:
    columns: tuple[ColumnSpec, ...] | None = None
    sort: str = "name"
    descending: bool = False
    printer_signature: str | None = None

    def __post_init__(self) -> None:
        field_key(self.sort)
        if type(self.descending) is not bool:
            raise AppError("Sort descending must be true or false.")
        if self.columns is not None and (
            not 1 <= len(self.columns) <= MAX_VIEW_COLUMNS
            or len({column.key for column in self.columns}) != len(self.columns)
        ):
            raise AppError("Views require 1-67 unique visible columns; omit a field to hide it.")
        if self.printer_signature is not None and (
            not isinstance(self.printer_signature, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.printer_signature) is None
        ):
            raise AppError("printer_signature must be a SHA-256 recorded by :views.")

    def mapping(self) -> dict[str, object]:
        return {
            **(
                {"columns": [column.mapping() for column in self.columns]}
                if self.columns is not None
                else {}
            ),
            "sort": {"key": self.sort, "descending": self.descending},
            **(
                {"printer_signature": self.printer_signature}
                if self.printer_signature is not None
                else {}
            ),
        }


def parse_view(value: object, *, legacy: bool = False) -> ViewSpec:
    allowed = {"columns", "sort", "printer_signature"} | (
        {"widths", "descending"} if legacy else set()
    )
    if not isinstance(value, dict) or value.keys() - allowed:
        raise AppError("Unknown view preference fields; use columns, sort and printer_signature.")
    raw = value.get("columns")
    if legacy and raw is None and value.get("widths"):
        raise AppError("Legacy widths require listed columns.")
    columns = None
    if raw is not None:
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_VIEW_COLUMNS:
            raise AppError("columns must be a list of 1-67 field definitions.")
        parsed = []
        widths = value.get("widths", {})
        if legacy:
            if not all(isinstance(item, str) for item in raw) or not isinstance(widths, dict):
                raise AppError("Legacy widths must refer only to listed string columns.")
            if widths.keys() - set(raw):
                raise AppError("Legacy widths must refer only to listed string columns.")
        for item in raw:
            if legacy:
                parsed.append(
                    ColumnSpec(
                        field_key(item), cast(dict[str, int | None], widths).get(field_key(item))
                    )
                )
            else:
                if not isinstance(item, dict) or item.keys() - {"key", "width", "alignment"}:
                    raise AppError("Each column accepts key, width and alignment.")
                parsed.append(
                    ColumnSpec(
                        field_key(item.get("key")),
                        cast(int | None, item.get("width")),
                        cast(Alignment, item.get("alignment", "auto")),
                    )
                )
        columns = tuple(parsed)
    if legacy:
        sort, descending = value.get("sort", "name"), value.get("descending", False)
    else:
        order = value.get("sort", {})
        if not isinstance(order, dict) or order.keys() - {"key", "descending"}:
            raise AppError("sort accepts key and descending.")
        sort, descending = order.get("key", "name"), order.get("descending", False)
    return ViewSpec(
        columns,
        field_key(sort),
        cast(bool, descending),
        cast(str | None, value.get("printer_signature")),
    )


def printer_signature(headers: tuple[ServerColumn, ...]) -> str:
    raw = [(column.name, column.type, column.format, column.priority) for column in headers]
    return hashlib.sha256(
        json.dumps(raw, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def applicable_view(
    view: ViewSpec,
    fields: tuple[str, ...],
    *,
    all_namespaces: bool = False,
    signature: str | None = None,
) -> ViewSpec:
    columns = view.columns if view.columns is not None else tuple(ColumnSpec(key) for key in fields)
    selected = {column.key for column in columns}
    if "name" not in selected:
        raise AppError("The name column must remain visible for stable resource identity.")
    if selected - set(fields) or view.sort not in fields:
        raise AppError(
            "Saved fields are unavailable for this resource; open :views to choose current fields."
        )
    references = {column.key for column in view.columns} if view.columns is not None else set()
    custom = any(re.fullmatch(r"c[0-9]+", key) for key in references | {view.sort})
    if (view.printer_signature is not None and view.printer_signature != signature) or (
        custom and view.printer_signature is None
    ):
        raise AppError(
            "Printer columns changed or lack a saved signature; open :views to record the current schema."
        )
    if all_namespaces and "namespace" in fields and "namespace" not in selected:
        columns = (ColumnSpec("namespace"), *columns)
    return replace(view, columns=columns)


def parse_column_text(text: str) -> tuple[ColumnSpec, ...]:
    if len(text) > 8192:
        raise AppError("Column input exceeds 8192 characters.")
    columns = []
    for token in text.split():
        parts = token.split(":")
        if len(parts) > 3:
            raise AppError("Use key[:width][:alignment], separated by spaces.")
        width = None
        if len(parts) >= 2 and parts[1] not in {"", "auto"}:
            if re.fullmatch(r"[0-9]{1,3}", parts[1]) is None:
                raise AppError("Widths use ASCII integers from 1 to 256 or auto.")
            width = int(parts[1])
        columns.append(
            ColumnSpec(
                field_key(parts[0]), width, cast(Alignment, parts[2] if len(parts) == 3 else "auto")
            )
        )
    return ViewSpec(tuple(columns)).columns or ()


def column_text(columns: tuple[ColumnSpec, ...]) -> str:
    return " ".join(
        column.key
        + (
            f":{column.width}"
            if column.width is not None
            else ":"
            if column.alignment != "auto"
            else ""
        )
        + (":" + column.alignment if column.alignment != "auto" else "")
        for column in columns
    )
