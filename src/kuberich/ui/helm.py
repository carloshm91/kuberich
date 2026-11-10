"""Native Helm release table with namespace/name keys and literal cells."""

from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.binding import BindingType
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from kuberich.domain.helm import HelmRelease, HelmReleaseKey, HelmRequest, HelmSnapshot
from kuberich.domain.navigation import Viewport
from kuberich.security.presentation import safe_text
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable

_COLUMNS = ("namespace", "name", "revision", "status", "chart", "app_version", "updated")
_SORTABLE = _COLUMNS[:-1]  # Helm's literal date formats are not chronologically sortable.


def release_key(key: HelmReleaseKey) -> str:
    return key.namespace + "/" + key.name


class HelmReleaseTable(FrameTable[Text]):
    """A row is a release, never a Kubernetes object or invented UID."""

    BINDING_PROFILE = "resources"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("resources")
    DEFAULT_CSS = "HelmReleaseTable { height: 1fr; min-height: 2; background: $background; }"

    class SortChanged(Message):
        pass

    def __init__(self) -> None:
        self._interaction_revision = 0
        super().__init__(id="helm-releases", cursor_type="row", zebra_stripes=True)
        self._rows: dict[str, HelmRelease] = {}
        self.request: HelmRequest | None = None
        self.sort_column = "name"
        self.descending = False
        self._restoration = 0

    def setup(self) -> None:
        for column in _COLUMNS:
            self.add_column(column.replace("_", " ").upper(), key=column)

    def reset(self, revision: int) -> None:
        self._restoration += 1
        self.clear()
        self._rows.clear()
        self.request = None

    @property
    def sort_summary(self) -> str:
        return f"Sort {self.sort_column.upper()} {'↓' if self.descending else '↑'} · s column · S reverse"

    def selected_release(self) -> HelmRelease | None:
        return self._rows.get(self.capture_viewport().selected or "")

    def capture_viewport(self) -> Viewport:
        keys = tuple(row.key.value for row in self.ordered_rows)
        selected = keys[self.cursor_row] if 0 <= self.cursor_row < len(keys) else None
        top = keys[min(int(self.scroll_y), len(keys) - 1)] if keys else None
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top)

    def watch_cursor_coordinate(
        self, old_coordinate: Coordinate, new_coordinate: Coordinate
    ) -> None:
        self._interaction_revision += old_coordinate != new_coordinate
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        self._interaction_revision += old_value != new_value
        super().watch_scroll_x(old_value, new_value)

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected in self._rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        restoration, interaction = self._restoration, self._interaction_revision
        selected = self.capture_viewport().selected

        def restore() -> None:
            if (
                restoration == self._restoration
                and interaction == self._interaction_revision
                and selected == self.capture_viewport().selected
            ):
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    def _sort(self) -> None:
        viewport = self.capture_viewport()
        rows = sorted(self._rows.values(), key=lambda row: (row.key.namespace, row.key.name))
        rows.sort(
            key=lambda row: (
                row.key.namespace
                if self.sort_column == "namespace"
                else row.key.name
                if self.sort_column == "name"
                else getattr(row, self.sort_column)
            ),
            reverse=self.descending,
        )
        ranks = {release_key(row.key): index for index, row in enumerate(rows)}
        self.sort(
            "namespace", "name", key=lambda cells: ranks[cells[0].plain + "/" + cells[1].plain]
        )
        self.restore_viewport(viewport)

    def restore_sort(self, column: str, descending: bool) -> None:
        self.sort_column = column if column in _SORTABLE else "name"
        self.descending = descending
        self._sort()
        self.post_message(self.SortChanged())

    def action_next_sort(self) -> None:
        self.restore_sort(
            _SORTABLE[(_SORTABLE.index(self.sort_column) + 1) % len(_SORTABLE)], False
        )

    def action_reverse_sort(self) -> None:
        self.restore_sort(self.sort_column, not self.descending)

    @on(DataTable.HeaderSelected)
    def header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.column_key.value in _SORTABLE:
            column = event.column_key.value
            assert column is not None
            self.restore_sort(column, not self.descending if column == self.sort_column else False)

    async def apply_rows(
        self,
        rows: tuple[HelmRelease, ...],
        snapshot: HelmSnapshot | None,
        current: Callable[[], bool],
    ) -> bool:
        if not current():
            return False
        request = snapshot.request if snapshot is not None else None
        if (
            request is not None
            and self.request is not None
            and request.scope.session == self.request.scope.session
            and request.generation < self.request.generation
        ):
            return False
        viewport = self.capture_viewport()
        incoming = {release_key(row.key): row for row in rows}
        for key in tuple(self._rows):
            if key not in incoming:
                self.remove_row(key)
        for row in rows:
            key = release_key(row.key)
            cells = tuple(
                safe_text(str(value))
                for value in (
                    row.key.namespace,
                    row.key.name,
                    row.revision,
                    row.status,
                    row.chart,
                    row.app_version,
                    row.updated,
                )
            )
            if key not in self._rows:
                self.add_row(*cells, key=key)
            elif row != self._rows[key]:
                for column, cell in zip(_COLUMNS, cells, strict=True):
                    self.update_cell(key, column, cell, update_width=True)
        self._rows, self.request = incoming, request
        self._sort()
        self.restore_viewport(viewport)
        return True
