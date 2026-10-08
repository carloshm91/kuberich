"""Batched live namespace rows, stable UID selection and owned viewport restoration."""

import asyncio
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import utc_now
from kuberich.security.presentation import safe_text
from kuberich.ui.pods import Viewport


class NamespaceTable(DataTable[Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "First", show=False),
        Binding("G", "scroll_bottom", "Last", show=False),
        Binding("0", "app.all_namespaces", "All namespaces"),
    ]

    def __init__(self) -> None:
        super().__init__(id="namespaces", cursor_type="row", zebra_stripes=False)
        self._rows: dict[str, NamespaceRow] = {}
        self._revision = -1
        self._restoration = 0

    def setup(self) -> None:
        for column in ("NAME", "STATUS", "AGE"):
            self.add_column(column, key=column)

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

        def restore() -> None:
            if (
                self._restoration == restoration
                and self._revision == revision
                and self.selected_uid == selected
            ):
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    async def apply_rows(
        self, rows: tuple[NamespaceRow, ...], revision: int, current: Callable[[], bool]
    ) -> bool:
        if not current():
            return False
        self.reset(revision)
        initial = not self.row_count
        incoming = {row.uid: row for row in rows}
        changes: list[tuple[str, NamespaceRow | None]] = [
            (uid, None) for uid in self._rows if uid not in incoming
        ]
        changes += [(uid, row) for uid, row in incoming.items() if self._rows.get(uid) != row]
        for start in range(0, len(changes), 128):
            if not current():
                return False
            viewport = self.capture_viewport()
            for uid, row in changes[start : start + 128]:
                if row is None:
                    self.remove_row(uid)
                    del self._rows[uid]
                else:
                    cells = tuple(safe_text(cell) for cell in row.cells(utc_now()))
                    if uid not in self._rows:
                        self.add_row(*cells, key=uid)
                    else:
                        for column, cell in zip(("NAME", "STATUS", "AGE"), cells, strict=True):
                            self.update_cell(uid, column, cell, update_width=True)
                    self._rows[uid] = row
            self.sort("NAME", key=lambda cell: cell.plain.casefold())
            self.restore_viewport(viewport)
            await asyncio.sleep(0)
        if not current():
            return False
        if initial:
            self.restore_viewport(Viewport(None, 0, 0, 0, None))
        return True

    def refresh_ages(self) -> None:
        now = utc_now()
        for uid, row in self._rows.items():
            self.update_cell(uid, "AGE", safe_text(row.cells(now)[-1]), update_width=True)
