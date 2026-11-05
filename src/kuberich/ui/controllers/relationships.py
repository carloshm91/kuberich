"""Project native relationship rows through the shared guarded rendering pipeline."""

from collections.abc import Callable

from kuberich.domain.navigation import Viewport
from kuberich.domain.relationships import RelationshipRow
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.relationships import RelationshipTable


class RelationshipController:
    def __init__(
        self,
        table: RelationshipTable,
        actions: Callable[[RenderRequest], frozenset[str]],
    ) -> None:
        self.table, self.actions = table, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[RelationshipRow]:
        snapshot = request.observation.relationships
        return ProjectedRows(snapshot.rows if snapshot is not None else (), lambda: True)

    async def filter(
        self, rows: tuple[RelationshipRow, ...], request: RenderRequest
    ) -> FilterResult[RelationshipRow]:
        result = await apply_filter(rows, request.query, "relationships")
        ancestors = {row.path[:depth] for row in result.rows for depth in range(len(row.path) + 1)}
        return FilterResult(
            tuple(row for row in rows if row.path in ancestors), result.problem, result.unknown
        )

    async def apply(self, rows: tuple[RelationshipRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(
            rows, request.observation.relationships, request.current, filtered=bool(request.query)
        )

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
