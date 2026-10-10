"""A UID keyed pod table: small patches, typed sorting and a stable viewport."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from kuberich.domain.pods import PodColumn, PodRow, order, utc_now
from kuberich.security.presentation import safe_text
from kuberich.ui.presentation import FrameTable


@dataclass(frozen=True)
class PodCell:
    uid: str
    text: str
    numeric: bool = False

    def __rich__(self) -> Text:
        value = safe_text(self.text)
        value.truncate(256, overflow="ellipsis")
        value.justify = "right" if self.numeric else "left"
        return value

    def __str__(self) -> str:
        return self.__rich__().plain


@dataclass(frozen=True)
class Viewport:
    selected: str | None
    index: int
    x: float
    y: float
    top: str | None


class PodTable(FrameTable[PodCell]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "next_sort", "Sort"),
        Binding("S", "reverse_sort", "Reverse sort", show=False),
    ]

    class SortChanged(Message):
        pass

    def __init__(self) -> None:
        super().__init__(id="resources", cursor_type="row", zebra_stripes=True)
        self._rows: dict[str, PodRow] = {}
        self._revision = -1
        self._restoration = 0
        self.sort_column = PodColumn.NAME
        self.descending = False

    @property
    def sort_summary(self) -> str:
        return f"Sort {self.sort_column.name} {'↓' if self.descending else '↑'} · s column · Shift+S reverse"

    @property
    def selected_uid(self) -> str | None:
        if not self.row_count:
            return None
        return self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value

    def setup(self) -> None:
        for column in PodColumn:
            self.add_column(column.name, key=column.value)

    def reset(self, revision: int) -> None:
        if revision != self._revision:
            self._revision = revision
            self._rows.clear()
            self.clear()
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

        def restore_scroll() -> None:
            if (
                self._revision == revision
                and self._restoration == restoration
                and self.selected_uid == selected
            ):
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore_scroll)

    def _sort(self) -> None:
        viewport = self._capture()
        sorted_rows = order(tuple(self._rows.values()), self.sort_column, self.descending)
        wanted = tuple(row.uid for row in sorted_rows)
        if wanted != tuple(row.key.value for row in self.ordered_rows):
            ranks = {uid: position for position, uid in enumerate(wanted)}
            self.sort(PodColumn.NAME.value, key=lambda cell: ranks[cell.uid])
            self._restore(viewport)

    async def apply_rows(
        self, rows: tuple[PodRow, ...], revision: int, is_current: Callable[[], bool]
    ) -> bool:
        """Patch at most 128 rows per event-loop turn; scope changes abort old patches."""
        if not is_current():
            return False
        self.reset(revision)
        initial = not self.row_count
        incoming = {row.uid: row for row in rows}
        removals = [(uid, None) for uid in self._rows if uid not in incoming]
        changes = [(uid, row) for uid, row in incoming.items() if self._rows.get(uid) != row]
        patches = removals + changes
        now = utc_now()
        for start in range(0, len(patches), 128):
            if not is_current():
                return False
            viewport = self._capture()
            for uid, row in patches[start : start + 128]:
                if row is None:
                    self.remove_row(uid)
                    del self._rows[uid]
                    continue
                cells = tuple(
                    PodCell(
                        uid, value, column in {PodColumn.READY, PodColumn.RESTARTS, PodColumn.AGE}
                    )
                    for column, value in zip(PodColumn, row.cells(now), strict=True)
                )
                if uid not in self._rows:
                    self.add_row(*cells, key=uid)
                else:
                    for column, cell, previous in zip(
                        PodColumn, cells, self.get_row(uid), strict=True
                    ):
                        if cell != previous:
                            self.update_cell(uid, column.value, cell, update_width=True)
                self._rows[uid] = row
            self._restore(viewport)
            await asyncio.sleep(0)
        if not is_current():
            return False
        self._sort()
        if initial:
            self._restore(Viewport(None, 0, 0, 0, None))
        return True

    def refresh_ages(self) -> None:
        now = utc_now()
        for uid, row in self._rows.items():
            cell = PodCell(uid, row.cells(now)[-1], True)
            if cell != self.get_cell(uid, PodColumn.AGE.value):
                self.update_cell(uid, PodColumn.AGE.value, cell, update_width=True)

    def set_sort(self, column: PodColumn) -> None:
        self.descending = not self.descending if column is self.sort_column else False
        self.sort_column = column
        self._sort()
        self.post_message(self.SortChanged())

    def action_next_sort(self) -> None:
        columns = tuple(PodColumn)
        self.set_sort(columns[(columns.index(self.sort_column) + 1) % len(columns)])

    def action_reverse_sort(self) -> None:
        self.set_sort(self.sort_column)

    @on(DataTable.HeaderSelected)
    def sort_header(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        self.set_sort(PodColumn(event.column_key.value or PodColumn.NAME))
