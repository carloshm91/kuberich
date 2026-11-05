"""A native expandable relationship view with literal evidence and stable path keys."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from typing import Any, ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.geometry import Offset, Region
from textual.message import Message
from textual.widgets.data_table import RowKey

from kuberich.domain.navigation import Viewport
from kuberich.domain.relationships import (
    RelationshipPath,
    RelationshipRequest,
    RelationshipRow,
    RelationshipSnapshot,
    RelationshipStatus,
    relationship_path_key,
)
from kuberich.security.presentation import safe_text
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable

_COLUMNS = ("RESOURCE", "STATUS", "RELATION / EVIDENCE", "DETAIL / OBSERVATION")
_MAX_DETAIL_LINES = 8
_MAX_DETAIL_CHARACTERS = 2048


@dataclass(frozen=True)
class _DisplayRow:
    key: str
    cells: tuple[str, str, str, str]


def _details(lines: tuple[str, ...]) -> str:
    # Each remote field stays on its own line; embedded newlines cannot create
    # extra rows or move identity/status evidence offscreen.
    bounded = tuple(safe_text(line).plain for line in lines[:_MAX_DETAIL_LINES])
    content = "\n".join(bounded)
    truncated = len(lines) > _MAX_DETAIL_LINES or len(content) > _MAX_DETAIL_CHARACTERS
    return content[:_MAX_DETAIL_CHARACTERS] + ("\n… [truncated]" if truncated else "")


def _display(
    row: RelationshipRow, request: RelationshipRequest | None, observation: str
) -> _DisplayRow:
    indent = "  " * min(len(row.path), 8)
    marker = (
        ("▾" if request is not None and row.path in request.expanded else "▸")
        if row.expandable
        else "·"
    )
    scope = (
        f"ns: {safe_text(row.ref.namespace).plain}"
        if row.ref.namespace is not None
        else "cluster scope"
    )
    target = f"{safe_text(row.ref.kind).plain}/{safe_text(row.ref.name).plain}"
    api_version = safe_text(row.ref.api_version).plain
    relation = str(row.relation).replace("_", " ") if row.relation is not None else "root"
    direction = f" · {row.direction}" if row.direction is not None else ""
    evidence = str(row.evidence) if row.evidence is not None else "captured identity"
    descriptor = (
        f"API resource: {row.ref.resource.name} · {row.ref.resource.api_version}"
        if row.ref.resource is not None
        else "API resource: unresolved GVK"
    )
    return _DisplayRow(
        relationship_path_key(row.path),
        (
            f"{indent}{marker} {target}\n{indent}  {scope} · {api_version}",
            str(row.status),
            f"{relation}{direction}\n{evidence}",
            _details(
                (
                    f"expected UID: {row.ref.uid or 'unspecified'}",
                    f"observed UID: {row.observed_uid or 'unverified'}",
                    descriptor,
                    *((observation,) if not row.path else ()),
                    *row.details,
                )
            ),
        ),
    )


class RelationshipTable(FrameTable[Text]):
    """Expand with arrows/Enter; opening a resource is an explicit external command.

    Shift+Left/Right scroll horizontally. Aggregate source/explanation rows have
    no path and cannot be mistaken for captured Kubernetes resources.
    """

    DEFAULT_CSS = "RelationshipTable { height: 1fr; min-height: 2; background: $background; }"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("right", "expand", "Expand relationship", show=False, priority=True),
        Binding("left", "collapse", "Collapse relationship", show=False, priority=True),
        Binding("shift+right", "scroll_right", "Scroll right", show=False, priority=True),
        Binding("shift+left", "scroll_left", "Scroll left", show=False, priority=True),
        *table_bindings("table"),
    ]

    class ExpansionRequested(Message):
        """Request a new graph revision; the workspace owns all collection work."""

        def __init__(
            self, table: RelationshipTable, path: RelationshipPath, expanded: bool
        ) -> None:
            super().__init__()
            self.table, self.path, self.expanded = table, path, expanded

        @property
        def control(self) -> RelationshipTable:
            return self.table

    def __init__(self) -> None:
        self._interaction_revision = 0
        self._geometry_scroll = False
        super().__init__(id="relationships", cursor_type="row", zebra_stripes=False)
        self._rows: dict[str, RelationshipRow] = {}
        self._display_rows: dict[str, _DisplayRow] = {}
        self._restoration = 0
        self._pending_viewport: tuple[int, Viewport] | None = None
        self.request: RelationshipRequest | None = None

    def setup(self) -> None:
        for column in _COLUMNS:
            self.add_column(column, key=column)

    def reset(self, revision: int) -> None:
        self._restoration += 1
        self._pending_viewport = None
        self.clear()
        self._rows.clear()
        self._display_rows.clear()
        self.request = None

    def selected_path(self) -> RelationshipPath | None:
        if not self.row_count:
            return None
        key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
        row = self._rows.get(key or "")
        return row.path if row is not None else None

    def row_at(self, path: RelationshipPath) -> RelationshipRow | None:
        return self._rows.get(relationship_path_key(path))

    def action_expand(self) -> None:
        path = self.selected_path()
        row = self.row_at(path) if path is not None else None
        if path is None or row is None or not row.expandable or self.request is None:
            return
        if path not in self.request.expanded:
            self.post_message(self.ExpansionRequested(self, path, True))
            return
        child = next(
            (item for item in self._rows.values() if item.path[:-1] == path and item.path), None
        )
        if child is not None:
            self.move_cursor(row=self.get_row_index(relationship_path_key(child.path)))

    def action_collapse(self) -> None:
        path = self.selected_path()
        if path is None or self.request is None:
            return
        if path in self.request.expanded:
            self.post_message(self.ExpansionRequested(self, path, False))
        elif path and self.row_at(path[:-1]) is not None:
            self.move_cursor(row=self.get_row_index(relationship_path_key(path[:-1])))

    def capture_viewport(self) -> Viewport:
        selected = (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )
        top, offset, position = None, 0.0, 0.0
        for row in self.ordered_rows:
            height = self.get_row_height(row.key)
            if position + height > self.scroll_y:
                top, offset = row.key.value, self.scroll_y - position
                break
            position += height
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top, offset)

    def _row_top(self, key: str | None) -> float | None:
        position = 0.0
        for row in self.ordered_rows:
            if row.key.value == key:
                return position
            position += self.get_row_height(row.key)
        return None

    def watch_cursor_coordinate(
        self, old_coordinate: Coordinate, new_coordinate: Coordinate
    ) -> None:
        self._interaction_revision += old_coordinate != new_coordinate
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        self._interaction_revision += old_value != new_value and not self._geometry_scroll
        super().watch_scroll_x(old_value, new_value)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        self._interaction_revision += old_value != new_value and not self._geometry_scroll
        super().watch_scroll_y(old_value, new_value)

    def scroll_to_region(self, region: Region, **kwargs: Any) -> Offset:
        # DataTable already defers cursor reveal until dimensions settle. Keep
        # that geometry adjustment synchronous so later manual scrolls remain
        # distinguishable from the row reveal that precedes viewport restoration.
        previous = self._geometry_scroll
        self._geometry_scroll = True
        try:
            return super().scroll_to_region(region, **{**kwargs, "immediate": True})
        finally:
            self._geometry_scroll = previous

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected is not None and viewport.selected in self.rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        revision, selected = self._restoration, self.capture_viewport().selected
        interaction = self._interaction_revision
        self._pending_viewport = interaction, viewport

        def restore() -> None:
            if revision == self._restoration:
                self._pending_viewport = None
                if (
                    selected == self.capture_viewport().selected
                    and interaction == self._interaction_revision
                ):
                    top = self._row_top(viewport.top)
                    y = top + viewport.top_offset if top is not None else viewport.y
                    self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    async def apply_rows(
        self,
        rows: tuple[RelationshipRow, ...],
        snapshot: RelationshipSnapshot | None,
        current: Callable[[], bool],
        *,
        filtered: bool = False,
    ) -> bool:
        if not current():
            return False
        request = snapshot.request if snapshot is not None else None
        if (
            request is not None
            and self.request is not None
            and request.scope == self.request.scope
            and request.revision < self.request.revision
        ):
            return False
        observed = (
            snapshot.observed_at.astimezone(UTC).isoformat(timespec="seconds")
            if snapshot is not None and snapshot.observed_at is not None
            else "never"
        )
        observation = f"observed: {observed}"
        if snapshot is not None:
            observation += f" · requests: {snapshot.requests_used}"
        display = [_display(row, request, observation) for row in rows]
        if snapshot is not None:
            for source in snapshot.sources:
                source_observed = (
                    source.observed_at.astimezone(UTC).isoformat(timespec="seconds")
                    if source.observed_at is not None
                    else "unavailable"
                )
                collection = source.collection
                if collection is None:
                    evidence = (
                        "observed exact resource · collection N/A"
                        if source.status is RelationshipStatus.READY
                        else "resource observation · INCOMPLETE"
                    )
                else:
                    evidence = "scan source · " + (
                        "complete"
                        if source.status is RelationshipStatus.READY and collection.complete
                        else "INCOMPLETE"
                    )
                display.append(
                    _DisplayRow(
                        "source:" + relationship_path_key((source.family, source.namespace or "")),
                        (
                            f"Source {safe_text(source.family).plain}\n"
                            + safe_text(source.namespace or "cluster / all namespaces").plain,
                            str(source.status),
                            evidence,
                            _details(
                                (
                                    f"observed: {source_observed} · requests: {snapshot.requests_used}",
                                    f"resource version: {source.resource_version or 'unavailable'}",
                                    source.detail,
                                )
                            ),
                        ),
                    )
                )
        if not display and not filtered:
            display.append(
                _DisplayRow(
                    "summary",
                    (
                        "Relationships",
                        "loading" if snapshot is None else "empty",
                        "No observations yet" if snapshot is None else "No visible relationships",
                        "" if snapshot is None else "Source coverage determines completeness.",
                    ),
                )
            )
        pending = self._pending_viewport
        # A coalesced render may arrive before the previous refresh callback.
        # Carry its intended viewport instead of overwriting it with an old x/y.
        viewport = (
            pending[1]
            if pending is not None and pending[0] == self._interaction_revision
            else self.capture_viewport()
        )
        incoming = {row.key: row for row in display}
        for key in tuple(self._display_rows):
            if key not in incoming:
                self.remove_row(key)
        for item in display:
            cells = tuple(safe_text(value, multiline=True) for value in item.cells)
            height = max(1, *(len(value.plain.splitlines()) for value in cells))
            if (
                item.key not in self._display_rows
                or self.get_row_height(RowKey(item.key)) != height
            ):
                if item.key in self._display_rows:
                    self.remove_row(item.key)
                self.add_row(*cells, key=item.key, height=height)
            elif item != self._display_rows[item.key]:
                for column, value in zip(_COLUMNS, cells, strict=True):
                    self.update_cell(item.key, column, value, update_width=True)
        # Distinct paths may have identical rendered cells. Use native cell
        # identity instead of cell text to retain the collector's tree order.
        order = {
            id(self.get_cell(item.key, _COLUMNS[0])): index for index, item in enumerate(display)
        }
        self.sort(key=lambda cells: order[id(cells[0])])
        self._display_rows = incoming
        self._rows = {relationship_path_key(row.path): row for row in rows}
        self.request = request
        self.restore_viewport(viewport)
        return True
