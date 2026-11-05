"""Native diagnostic findings and source limits in the existing workspace frame."""

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual import on
from textual.coordinate import Coordinate
from textual.geometry import Offset, Region
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from kuberich.domain.cluster_diagnostics import DiagnosticRequest, DiagnosticSnapshot
from kuberich.domain.diagnostic_rows import DiagnosticRow
from kuberich.domain.navigation import Viewport
from kuberich.security.presentation import safe_text
from kuberich.ui.presentation import FrameTable

_COLUMNS = ("SEVERITY", "CATEGORY", "NAMESPACE / RESOURCE", "CONTAINER", "SUMMARY", "SOURCE", "AGE")
_WIDTHS = (9, 14, 36, 18, 64, 12, 22)


class ClusterDiagnosticsTable(FrameTable[Text]):
    """Findings and source rows remain evidence; explicit actions validate identity separately."""

    DEFAULT_CSS = "ClusterDiagnosticsTable { height: 1fr; min-height: 2; background: $background; }"

    def __init__(self) -> None:
        self._interaction_revision = 0
        self._geometry_scroll = False
        super().__init__(id="cluster-diagnostics", cursor_type="row", zebra_stripes=False)
        self._restoration = 0
        self._pending_viewport: tuple[int, Viewport] | None = None
        self._rows: dict[str, DiagnosticRow] = {}
        self.request: DiagnosticRequest | None = None
        self.snapshot: DiagnosticSnapshot | None = None
        self.sort_column = "severity"
        self.descending = True

    def setup(self) -> None:
        for column, width in zip(_COLUMNS, _WIDTHS, strict=True):
            self.add_column(column, key=column, width=width)

    def _ordered(self, rows: tuple[DiagnosticRow, ...]) -> tuple[DiagnosticRow, ...]:
        ranks = {"ok": 0, "info": 1, "warning": 2, "error": 3}
        findings = tuple(row for row in rows if row.finding is not None)
        ordered = sorted(
            findings,
            key=lambda row: (
                (ranks[row.severity], row.source, row.key)
                if self.sort_column == "severity"
                else (row.source, ranks[row.severity], row.key)
            ),
            reverse=self.descending,
        )
        return (*tuple(row for row in rows if row.finding is None), *ordered)

    def set_sort(self, column: str, descending: bool) -> None:
        if column not in {"severity", "source"}:
            raise ValueError("Diagnostics sort must be severity or source.")
        viewport = self.capture_viewport()
        self.sort_column, self.descending = column, descending
        self._sort_rows(self._ordered(tuple(self._rows.values())))
        self.restore_viewport(viewport)

    @on(DataTable.HeaderSelected)
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        column = (event.column_key.value or "").lower()
        if column in {"severity", "source"}:
            self.set_sort(column, not self.descending if column == self.sort_column else False)

    def _sort_rows(self, rows: tuple[DiagnosticRow, ...]) -> None:
        order = {id(self.get_cell(row.key, _COLUMNS[0])): index for index, row in enumerate(rows)}
        self.sort(key=lambda cells: order[id(cells[0])])

    def reset(self, revision: int) -> None:
        self._restoration += 1
        self._pending_viewport = None
        self.clear()
        self._rows.clear()
        self.request = None
        self.snapshot = None

    def selected_key(self) -> str | None:
        return (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )

    def row_at(self, key: str | None) -> DiagnosticRow | None:
        return self._rows.get(key or "")

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
        self._interaction_revision += old_value != new_value
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
        rows: tuple[DiagnosticRow, ...],
        snapshot: DiagnosticSnapshot | None,
        current: Callable[[], bool],
    ) -> bool:
        if not current():
            return False
        rows = self._ordered(rows)
        request = snapshot.request if snapshot is not None else None
        if (
            request is not None
            and self.request is not None
            and request.scope.session == self.request.scope.session
            and request.revision < self.request.revision
        ):
            return False
        pending = self._pending_viewport
        viewport = (
            pending[1]
            if pending is not None and pending[0] == self._interaction_revision
            else self.capture_viewport()
        )
        incoming = {row.key: row for row in rows}
        for key in tuple(self._rows):
            if key not in incoming:
                self.remove_row(key)
        for row in rows:
            details = "\n".join(safe_text(line).plain for line in row.details[:4])
            if len(details) > 2048 or len(row.details) > 4:
                details = details[:2048] + "\n… [truncated]"
            cells = tuple(
                safe_text(value, multiline=True)
                for value in (
                    safe_text(row.severity).plain,
                    safe_text(row.category).plain,
                    safe_text(row.resource).plain,
                    safe_text(row.container).plain,
                    safe_text(row.summary).plain + ("\n" + details if details else ""),
                    safe_text(row.source).plain,
                    safe_text(row.age).plain,
                )
            )
            height = max(1, *(len(cell.plain.splitlines()) for cell in cells))
            if row.key not in self._rows or self.get_row_height(RowKey(row.key)) != height:
                if row.key in self._rows:
                    self.remove_row(row.key)
                self.add_row(*cells, key=row.key, height=height)
            elif row != self._rows[row.key]:
                for column, cell in zip(_COLUMNS, cells, strict=True):
                    self.update_cell(row.key, column, cell, update_width=True)
        self._sort_rows(rows)
        self._rows = incoming
        self.request = request
        self.snapshot = snapshot
        self.restore_viewport(viewport)
        return True
