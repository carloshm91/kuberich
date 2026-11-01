"""Adapt the real local context table to the common rendering pipeline."""

from __future__ import annotations

from collections.abc import Callable

from kuberich.config.catalog import KubeCatalog
from kuberich.domain.navigation import ContextRow, Viewport
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.ui.contexts import ContextTable, context_rows
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest


class ContextController:
    def __init__(
        self,
        table: ContextTable,
        catalog: Callable[[], KubeCatalog],
        actions: Callable[[RenderRequest], frozenset[str]],
    ) -> None:
        self.table, self.catalog, self.actions = table, catalog, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[ContextRow]:
        return ProjectedRows(
            context_rows(self.catalog(), request.observation.context), lambda: True
        )

    async def filter(
        self, rows: tuple[ContextRow, ...], request: RenderRequest
    ) -> FilterResult[ContextRow]:
        return await apply_filter(rows, request.query, "contexts")

    async def apply(self, rows: tuple[ContextRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
