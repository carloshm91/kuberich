"""Local kubeconfig contexts are rows, not Kubernetes resources or modal choices."""

import asyncio
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from kuberich.domain.navigation import ContextRow
from kuberich.security.presentation import safe_text
from kuberich.ui.pods import Viewport

CONTEXT_COLUMNS = ("CURRENT", "NAME", "CLUSTER", "AUTHINFO", "NAMESPACE")


class ContextTable(DataTable[Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "First", show=False),
        Binding("G", "scroll_bottom", "Last", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(id="contexts", cursor_type="row", zebra_stripes=False)
        self._rows: dict[str, ContextRow] = {}
        self._restoration = 0

    def setup(self) -> None:
        for column in CONTEXT_COLUMNS:
            self.add_column(
                "*" if column == "CURRENT" else column,
                key=column,
                width=1 if column == "CURRENT" else None,
            )

    def capture_viewport(self) -> Viewport:
        selected = (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )
        top = (
            self.coordinate_to_cell_key(
                Coordinate(min(int(self.scroll_y), self.row_count - 1), 0)
            ).row_key.value
            if self.row_count
            else None
        )
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top)

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected in self._rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        restoration, selected = self._restoration, self.capture_viewport().selected

        def restore() -> None:
            if self._restoration == restoration and self.capture_viewport().selected == selected:
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    async def apply_rows(self, rows: tuple[ContextRow, ...], current: Callable[[], bool]) -> bool:
        if not current():
            return False
        initial = not self.row_count
        incoming = {row.name: row for row in rows}
        changes: list[tuple[str, ContextRow | None]] = [
            (name, None) for name in self._rows if name not in incoming
        ]
        changes += [(name, row) for name, row in incoming.items() if self._rows.get(name) != row]
        for start in range(0, len(changes), 128):
            if not current():
                return False
            viewport = self.capture_viewport()
            for name, row in changes[start : start + 128]:
                if row is None:
                    self.remove_row(name)
                    del self._rows[name]
                else:
                    cells = tuple(safe_text(cell) for cell in row.cells())
                    if name not in self._rows:
                        self.add_row(*cells, key=name)
                    else:
                        for column, cell in zip(CONTEXT_COLUMNS, cells, strict=True):
                            self.update_cell(name, column, cell, update_width=True)
                    self._rows[name] = row
            self.sort("NAME", key=lambda cell: cell.plain.casefold())
            self.restore_viewport(viewport)
            await asyncio.sleep(0)
        if not current():
            return False
        if initial:
            self.restore_viewport(Viewport(None, 0, 0, 0, None))
        return True
