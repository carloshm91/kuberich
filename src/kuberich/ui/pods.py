"""A UID keyed pod table: small patches, typed sorting and a stable viewport."""

import asyncio
from collections.abc import Callable
from typing import ClassVar

from textual import on
from textual.binding import BindingType
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from kuberich.domain.navigation import Viewport as Viewport
from kuberich.domain.pods import PodColumn, PodRow, order, sort_value, utc_now
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec, applicable_view
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable, TableCell

PodCell = TableCell


class PodTable(FrameTable[PodCell]):
    _row_repaint_enabled = True
    BINDING_PROFILE = "resources"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("resources")

    class SortChanged(Message):
        pass

    def __init__(self) -> None:
        self._interaction_revision = 0
        super().__init__(id="resources", cursor_type="row", zebra_stripes=True)
        self._rows: dict[str, PodRow] = {}
        self._revision = -1
        self._restoration = 0
        self.sort_column = PodColumn.NAME
        self.descending = False
        self._ordered_state: tuple[PodColumn, bool, int] | None = None
        self.view_spec: ViewSpec | None = None
        self._columns: tuple[tuple[PodColumn, ColumnSpec, int], ...] = ()
        self._pending_viewport: tuple[int, Viewport] | None = None

    @property
    def sort_summary(self) -> str:
        return f"Sort {self.sort_column.name} {'↓' if self.descending else '↑'} · {self.navigation_hint('sort')} column · {self.navigation_hint('reverse_sort')} reverse"

    @property
    def selected_uid(self) -> str | None:
        if not self.row_count:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value

    def setup(self) -> None:
        fields = tuple(PodColumn)
        specs = self.view_spec.columns if self.view_spec is not None else None
        self._columns = tuple(
            (PodColumn(spec.key), spec, fields.index(PodColumn(spec.key)))
            for spec in (
                specs if specs is not None else tuple(ColumnSpec(c.value) for c in fields[:6])
            )
        )
        for column, spec, _ in self._columns:
            self.add_column(column.name, key=column.value, width=spec.width)

    @property
    def visible_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(spec for _, spec, _ in self._columns)

    def configure_view(self, view: ViewSpec | None, *, force: bool = False) -> None:
        validated = (
            applicable_view(view, tuple(column.value for column in PodColumn))
            if view is not None
            else None
        )
        if self.view_spec == validated and not force:
            return
        viewport = self.capture_viewport()
        self.view_spec = validated
        self._rows.clear()
        self.clear(columns=True)
        self.setup()
        if validated is not None:
            self.sort_column, self.descending = PodColumn(validated.sort), validated.descending
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

    def reset(self, revision: int) -> None:
        if revision != self._revision:
            self._revision = revision
            self._rows.clear()
            self.clear()
            if self._pending_viewport is not None and self._pending_viewport[0] != revision:
                self._pending_viewport = None
            self.scroll_to(0, 0, animate=False, immediate=True)

    def _capture(self) -> Viewport:
        top = (
            self.coordinate_to_cell_key(
                Coordinate(min(int(self.scroll_y), self.row_count - 1), 0)
            ).row_key.value
            if self.row_count
            else None
        )
        return Viewport(self.selected_uid, self.cursor_row, self.scroll_x, self.scroll_y, top)

    def capture_viewport(self) -> Viewport:
        return self._capture()

    def restore_viewport(self, viewport: Viewport) -> None:
        self._restore(viewport)

    def restore_sort(self, column: PodColumn, descending: bool) -> None:
        self._interaction_revision += 1
        self.sort_column = column
        self.descending = descending
        self._sort()
        self.post_message(self.SortChanged())

    def _restore(self, viewport: Viewport) -> None:
        destination = (
            self.get_row_index(viewport.selected)
            if viewport.selected in self._rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=destination, scroll=False)
        # Textual's cursor watcher also scrolls, even with move_cursor(scroll=False).
        # Restore after dimensions and those queued callbacks have settled.
        revision = self._revision
        self._restoration += 1
        restoration = self._restoration
        selected = self.selected_uid
        layout, interaction = self._column_revision, self._interaction_revision

        def restore_scroll() -> None:
            if (
                self._revision == revision
                and self._restoration == restoration
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

        self.call_after_refresh(restore_scroll)

    def _sort(self) -> None:
        state = self.sort_column, self.descending, self._row_order_revision
        if state == self._ordered_state:
            return
        viewport = self._capture()
        sorted_rows = order(tuple(self._rows.values()), self.sort_column, self.descending)
        wanted = tuple(row.uid for row in sorted_rows)
        if wanted != tuple(row.key.value for row in self.ordered_rows):
            ranks = {uid: position for position, uid in enumerate(wanted)}
            self.sort(PodColumn.NAME.value, key=lambda cell: ranks[cell.uid])
            self._restore(viewport)
        self._ordered_state = self.sort_column, self.descending, self._row_order_revision

    async def apply_rows(
        self, rows: tuple[PodRow, ...], revision: int, is_current: Callable[[], bool]
    ) -> bool:
        """Patch at most 128 rows per event-loop turn; scope changes abort old patches."""
        if not is_current():
            return False
        self.reset(revision)
        layout = self._column_revision
        initial = not self.row_count
        interacted = False
        incoming = {row.uid: row for row in rows}
        removals = [(uid, None) for uid in self._rows if uid not in incoming]
        changes = [
            (uid, row)
            for uid, row in incoming.items()
            if (cached_row := self._rows.get(uid)) is not row and cached_row != row
        ]
        patches = removals + changes
        now = utc_now()
        for start in range(0, len(patches), 128):
            if not is_current() or layout != self._column_revision:
                return False
            viewport = self._capture()
            for uid, row in patches[start : start + 128]:
                if row is None:
                    self.remove_row(uid)
                    del self._rows[uid]
                    continue
                values = row.cells(now, wide=True)
                cells = tuple(
                    PodCell(
                        uid,
                        values[index],
                        column in {PodColumn.READY, PodColumn.RESTARTS, PodColumn.AGE},
                        spec.justify,
                    )
                    for column, spec, index in self._columns
                )
                if uid not in self._rows:
                    self.add_row(*cells, key=uid, label=" ")
                else:
                    old_row = self._rows[uid]
                    if (
                        old_row.namespace,
                        old_row.name,
                        old_row.uid,
                        sort_value(old_row, self.sort_column),
                    ) != (
                        row.namespace,
                        row.name,
                        row.uid,
                        sort_value(row, self.sort_column),
                    ):
                        self._ordered_state = None
                    for (column, _, _), cell, previous in zip(
                        self._columns, cells, self.get_row(uid), strict=True
                    ):
                        if cell != previous:
                            self.update_cell(uid, column.value, cell, update_width=True)
                self._rows[uid] = row
            self._restore(viewport)
            interaction = self._interaction_revision
            await asyncio.sleep(0)
            interacted |= interaction != self._interaction_revision
        if not is_current() or layout != self._column_revision:
            return False
        self._sort()
        if initial and not interacted:
            self._restore(
                self._pending_viewport[1]
                if self._pending_viewport is not None
                else Viewport(None, 0, 0, 0, None)
            )
        self._pending_viewport = None
        return True

    def refresh_ages(self) -> None:
        age_spec = next(
            (spec for column, spec, _ in self._columns if column is PodColumn.AGE), None
        )
        if age_spec is None:
            return
        now = utc_now()
        for uid, row in self._rows.items():
            cell = PodCell(uid, row.cells(now)[-1], True, age_spec.justify)
            if cell != self.get_cell(uid, PodColumn.AGE.value):
                self.update_cell(uid, PodColumn.AGE.value, cell, update_width=True)

    def set_sort(self, column: PodColumn) -> None:
        self._interaction_revision += 1
        self.descending = not self.descending if column is self.sort_column else False
        self.sort_column = column
        self._sort()
        self.post_message(self.SortChanged())

    def action_next_sort(self) -> None:
        columns = tuple(column for column, _, _ in self._columns)
        index = columns.index(self.sort_column) + 1 if self.sort_column in columns else 0
        self.set_sort(columns[index % len(columns)])

    def action_reverse_sort(self) -> None:
        self.set_sort(self.sort_column)

    @on(DataTable.HeaderSelected)
    def sort_header(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        if event.column_index < 0:
            return
        self.set_sort(PodColumn(event.column_key.value or PodColumn.NAME))
