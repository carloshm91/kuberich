"""Generic server columns inside the existing owned UID-keyed table behavior."""

from collections.abc import Callable

from rich.text import Text

from kuberich.domain.custom import CustomLayout
from kuberich.domain.registry import ResourceRow
from kuberich.domain.resource_preferences import printer_signature
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
            super().setup()

    def column_label(self, key: str) -> str | Text:
        return (
            safe_text(self.resource_layout.label(key))
            if self.resource_layout is not None
            else key.upper()
        )

    @property
    def schema_signature(self) -> str | None:
        return (
            printer_signature(self.resource_layout.headers)
            if self.resource_layout is not None
            else None
        )

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
        self.view_spec = None
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
        return f"Sort {label} {'↓' if self.descending else '↑'} · {self.navigation_hint('sort')} column · {self.navigation_hint('reverse_sort')} reverse"

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
