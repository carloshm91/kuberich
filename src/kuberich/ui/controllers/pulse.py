"""Project the native cluster overview through the shared guarded render pipeline."""

from collections.abc import Callable

from kuberich.domain.navigation import Viewport
from kuberich.domain.pulse import PulseRow
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.pulse import PulseTable


class PulseController:
    def __init__(
        self,
        table: PulseTable,
        actions: Callable[[RenderRequest], frozenset[str]],
    ) -> None:
        self.table, self.actions = table, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[PulseRow]:
        snapshot = request.observation.pulse
        return ProjectedRows(snapshot.rows if snapshot is not None else (), lambda: True)

    async def filter(
        self, rows: tuple[PulseRow, ...], request: RenderRequest
    ) -> FilterResult[PulseRow]:
        return await apply_filter(rows, request.query, "pulse")

    async def apply(self, rows: tuple[PulseRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(
            rows, request.observation.pulse, request.current, filtered=bool(request.query)
        )

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
