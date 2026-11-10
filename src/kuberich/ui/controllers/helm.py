"""Project release metadata through the common guarded rendering pipeline."""

from collections.abc import Callable

from kuberich.domain.helm import HelmRelease
from kuberich.domain.navigation import Viewport
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.helm import HelmReleaseTable


class HelmController:
    def __init__(
        self, table: HelmReleaseTable, actions: Callable[[RenderRequest], frozenset[str]]
    ) -> None:
        self.table, self.actions = table, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[HelmRelease]:
        snapshot = request.observation.helm
        rows = (
            snapshot.listing.releases
            if snapshot is not None and snapshot.listing is not None
            else ()
        )
        return ProjectedRows(rows, lambda: True)

    async def filter(
        self, rows: tuple[HelmRelease, ...], request: RenderRequest
    ) -> FilterResult[HelmRelease]:
        return await apply_filter(rows, request.query, "Helm releases")

    async def apply(self, rows: tuple[HelmRelease, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.observation.helm, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
