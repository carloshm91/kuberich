"""Project authorization evidence through the owned, guarded render pipeline."""

from collections.abc import Callable
from functools import partial

from kuberich.domain.authorization_rows import AuthorizationRow, authorization_rows
from kuberich.domain.navigation import Viewport
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.services.resources import parse_owned
from kuberich.ui.authorization import AuthorizationTable
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest


class AuthorizationController:
    def __init__(
        self, table: AuthorizationTable, actions: Callable[[RenderRequest], frozenset[str]]
    ) -> None:
        self.table, self.actions = table, actions

    async def project(self, request: RenderRequest) -> ProjectedRows[AuthorizationRow]:
        rows = await parse_owned(partial(authorization_rows, request.observation.authorization))
        return ProjectedRows(rows, lambda: True)

    async def filter(
        self, rows: tuple[AuthorizationRow, ...], request: RenderRequest
    ) -> FilterResult[AuthorizationRow]:
        result = await apply_filter(rows, request.query, "authorization evidence")
        selected = {row.key for row in result.rows}
        return FilterResult(
            tuple(
                row
                for row in rows
                if row.key in selected
                or row.key.startswith(("summary:", "source:", "warning:", "identity:", "review:"))
            ),
            result.problem,
            result.unknown,
        )

    async def apply(self, rows: tuple[AuthorizationRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.observation.authorization, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
