"""Batched live namespace rows, stable UID selection and owned viewport restoration."""

import asyncio
from collections.abc import Callable
from typing import ClassVar

from textual import on
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from kuberich.domain.namespaces import NamespaceRow, order_namespaces
from kuberich.domain.pods import utc_now
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec, applicable_view
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.pods import Viewport
from kuberich.ui.presentation import FrameTable, TableCell


class NamespaceTable(FrameTable[TableCell]):
    BINDING_PROFILE = "namespaces"
    BINDINGS: ClassVar[list[BindingType]] = [
        *table_bindings("namespaces"),
        Binding("0", "app.all_namespaces", "All namespaces"),
    ]

    class SortChanged(Message):
        pass

    def __init__(self) -> None:
        self._interaction_revision = 0
        super().__init__(id="namespaces", cursor_type="row", zebra_stripes=False)
        self._rows: dict[str, NamespaceRow] = {}
        self._revision = -1
        self._restoration = 0
        self.view_spec: ViewSpec | None = None
        self.sort_column, self.descending = "name", False
        self._columns: tuple[tuple[str, ColumnSpec, int], ...] = ()
        self._pending_viewport: tuple[int, Viewport] | None = None
        self._ordered_state: tuple[str, bool, int] | None = None

    @property
    def sort_summary(self) -> str:
        return f"Sort {self.sort_column.upper()} {'↓' if self.descending else '↑'} · {self.navigation_hint('sort')} column · {self.navigation_hint('reverse_sort')} reverse"

    def setup(self) -> None:
        fields = ("name", "status", "age")
        specs = self.view_spec.columns if self.view_spec is not None else None
        self._columns = tuple(
            (spec.key, spec, fields.index(spec.key))
            for spec in (specs if specs is not None else tuple(ColumnSpec(key) for key in fields))
        )
        for key, spec, _ in self._columns:
            self.add_column(key.upper(), key=key.upper(), width=spec.width)

    @property
    def visible_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(spec for _, spec, _ in self._columns)

    def configure_view(self, view: ViewSpec | None, *, force: bool = False) -> None:
        validated = applicable_view(view, ("name", "status", "age")) if view is not None else None
        if self.view_spec == validated and not force:
            return
        viewport = self.capture_viewport()
        self.view_spec = validated
        self._rows.clear()
        self.clear(columns=True)
        self.setup()
        if validated is not None:
            self.sort_column, self.descending = validated.sort, validated.descending
        self._ordered_state = None
        self._pending_viewport = self._revision, viewport

    def watch_cursor_coordinate(
        self, old_coordinate: Coordinate, new_coordinate: Coordinate
    ) -> None:
        self._interaction_revision += old_coordinate != new_coordinate
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        self._interaction_revision += old_value != new_value
        super().watch_scroll_x(old_value, new_value)

    @property
    def selected_uid(self) -> str | None:
        return (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )

    def reset(self, revision: int) -> None:
        if self._revision != revision:
            self._revision = revision
            self._rows.clear()
            self.clear()
            if self._pending_viewport is not None and self._pending_viewport[0] != revision:
                self._pending_viewport = None
            self.scroll_to(0, 0, animate=False, immediate=True)

    def capture_viewport(self) -> Viewport:
        top = (
            self.coordinate_to_cell_key(
                Coordinate(min(int(self.scroll_y), self.row_count - 1), 0)
            ).row_key.value
            if self.row_count
            else None
        )
        return Viewport(self.selected_uid, self.cursor_row, self.scroll_x, self.scroll_y, top)

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected in self._rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        restoration, revision = self._restoration, self._revision
        selected = self.selected_uid
        layout, interaction = self._column_revision, self._interaction_revision

        def restore() -> None:
            if (
                self._restoration == restoration
                and self._revision == revision
                and self.selected_uid == selected
                and self._column_revision == layout
                and self._interaction_revision == interaction
            ):
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    def _sort(self) -> None:
        state = self.sort_column, self.descending, self._row_order_revision
        if state == self._ordered_state:
            return
        ordered = order_namespaces(tuple(self._rows.values()), self.sort_column, self.descending)
        wanted = tuple(row.uid for row in ordered)
        if wanted != tuple(row.key.value for row in self.ordered_rows):
            viewport = self.capture_viewport()
            ranks = {uid: index for index, uid in enumerate(wanted)}
            self.sort("NAME", key=lambda cell: ranks[cell.uid])
            self.restore_viewport(viewport)
        self._ordered_state = self.sort_column, self.descending, self._row_order_revision

    def restore_sort(self, column: str, descending: bool) -> None:
        self._interaction_revision += 1
        self.sort_column = column if column in {"name", "status", "age"} else "name"
        self.descending = descending
        self._ordered_state = None
        self._sort()
        self.post_message(self.SortChanged())

    def action_next_sort(self) -> None:
        keys = tuple(key for key, _, _ in self._columns)
        index = keys.index(self.sort_column) + 1 if self.sort_column in keys else 0
        self.set_sort(keys[index % len(keys)])

    def action_reverse_sort(self) -> None:
        self.set_sort(self.sort_column)

    def set_sort(self, column: str) -> None:
        self.restore_sort(column, not self.descending if column == self.sort_column else False)

    @on(DataTable.HeaderSelected)
    def sort_header(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        if event.column_index < 0:
            return
        self.set_sort((event.column_key.value or "name").lower())

    async def apply_rows(
        self, rows: tuple[NamespaceRow, ...], revision: int, current: Callable[[], bool]
    ) -> bool:
        if not current():
            return False
        self.reset(revision)
        layout = self._column_revision
        initial = not self.row_count
        interacted = False
        incoming = {row.uid: row for row in rows}
        changes: list[tuple[str, NamespaceRow | None]] = [
            (uid, None) for uid in self._rows if uid not in incoming
        ]
        changes += [(uid, row) for uid, row in incoming.items() if self._rows.get(uid) != row]
        for start in range(0, len(changes), 128):
            if not current() or layout != self._column_revision:
                return False
            viewport = self.capture_viewport()
            for uid, row in changes[start : start + 128]:
                if row is None:
                    self.remove_row(uid)
                    del self._rows[uid]
                else:
                    values = row.cells(utc_now())
                    cells = tuple(
                        TableCell(uid, values[index], key == "age", spec.justify)
                        for key, spec, index in self._columns
                    )
                    if uid not in self._rows:
                        self.add_row(*cells, key=uid, label=" ")
                    else:
                        for (key, _, _), cell in zip(self._columns, cells, strict=True):
                            self.update_cell(uid, key.upper(), cell, update_width=True)
                    self._rows[uid] = row
                    self._ordered_state = None
            self._sort()
            self.restore_viewport(viewport)
            interaction = self._interaction_revision
            await asyncio.sleep(0)
            interacted |= interaction != self._interaction_revision
        if not current() or layout != self._column_revision:
            return False
        if initial and not interacted:
            self.restore_viewport(
                self._pending_viewport[1]
                if self._pending_viewport is not None
                else Viewport(None, 0, 0, 0, None)
            )
        self._pending_viewport = None
        return True

    def refresh_ages(self) -> None:
        spec = next((spec for key, spec, _ in self._columns if key == "age"), None)
        if spec is None:
            return
        now = utc_now()
        for uid, row in self._rows.items():
            self.update_cell(
                uid,
                "AGE",
                TableCell(uid, row.cells(now)[-1], True, spec.justify),
                update_width=True,
            )
