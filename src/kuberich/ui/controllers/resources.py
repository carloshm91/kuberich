"""Typed resource table ports share one projection/filter/application adapter."""

from collections.abc import Callable
from typing import Protocol

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import Viewport
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import ResourceRow
from kuberich.domain.views import ViewObservation
from kuberich.services.filtering import FilterResult
from kuberich.services.pods import ResourceProjection
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter


class ResourceTable[T: PodRow | NamespaceRow | ResourceRow](Protocol):
    async def apply_rows(
        self, rows: tuple[T, ...], revision: int, current: Callable[[], bool], /
    ) -> bool: ...

    def capture_viewport(self) -> Viewport: ...

    def restore_viewport(self, viewport: Viewport) -> None: ...


class ResourceController[T: PodRow | NamespaceRow | ResourceRow]:
    def __init__(
        self,
        table: ResourceTable[T],
        projection: ResourceProjection[T],
        filtering: ResourceFilter,
        prepare: Callable[[ViewObservation], object],
        actions: Callable[[RenderRequest], frozenset[str]],
    ) -> None:
        self.table, self.projection, self.filtering = table, projection, filtering
        self.prepare, self.actions = prepare, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[T]:
        self.prepare(request.observation)
        return ProjectedRows(
            await self.projection.project(request.observation.snapshot), lambda: True
        )

    async def retire_projection(self) -> None:
        """Release decoded records when another resource view becomes active."""
        await self.projection.project(None)

    async def filter(self, rows: tuple[T, ...], request: RenderRequest) -> FilterResult[T]:
        return await self.filtering.apply(rows, request)

    async def apply(self, rows: tuple[T, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.observation.revision, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
