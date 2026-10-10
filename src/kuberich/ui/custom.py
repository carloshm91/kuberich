"""Generic server columns inside the existing owned UID-keyed table behavior."""

from collections.abc import Callable

from kuberich.domain.custom import CustomLayout
from kuberich.domain.registry import ResourceRow
from kuberich.security.presentation import safe_text
from kuberich.ui.pods import Viewport
from kuberich.ui.standard import StandardTable


class CustomTable(StandardTable):
    def __init__(self) -> None:
        super().__init__(id="custom-resources")
        self.resource_layout: CustomLayout | None = None
        self._pending_viewport: tuple[int, Viewport] | None = None

    def setup(self) -> None:
        if self.resource_layout is not None:
            for column in self.definition.columns:
                self.add_column(safe_text(self.resource_layout.label(column.key)), key=column.key)

    def configure_layout(self, layout: CustomLayout, revision: int) -> None:
        if self.resource_layout == layout:
            return
        self._pending_viewport = (
            (revision, self.capture_viewport())
            if self.resource_layout is not None
            and self.resource_layout.resource == layout.resource
            and self._revision == revision
            else None
        )
        old_sort = self.sort_column
        compatible_sort = (
            self.resource_layout is not None
            and self.resource_layout.headers == layout.headers
            and old_sort in {column.key for column in layout.definition.columns}
        )
        self.resource_layout = layout
        self.definition = layout.definition
        self._rows.clear()
        self.clear(columns=True)
        self.setup()
        self.sort_column = old_sort if compatible_sort else "name"
        if not compatible_sort:
            self.descending = False

    @property
    def sort_summary(self) -> str:
        label = (
            self.resource_layout.label(self.sort_column)
            if self.resource_layout is not None
            else "NAME"
        )
        return f"Sort {label} {'↓' if self.descending else '↑'} · s column · Shift+S reverse"

    async def apply_rows(
        self, rows: tuple[ResourceRow, ...], revision: int, is_current: Callable[[], bool]
    ) -> bool:
        result = await super().apply_rows(rows, revision, is_current)
        if result:
            self._pending_viewport = None
        return result

    def _initial_viewport(self) -> Viewport:
        pending = self._pending_viewport
        return (
            pending[1]
            if pending is not None and pending[0] == self._revision
            else super()._initial_viewport()
        )
