"""Project immutable diagnostics through the shared guarded render pipeline."""

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

from kuberich.domain.diagnostic_rows import DiagnosticRow, diagnostic_rows
from kuberich.domain.navigation import Viewport
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.services.resources import parse_owned
from kuberich.ui.cluster_diagnostics import ClusterDiagnosticsTable
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest


class ClusterDiagnosticsController:
    def __init__(
        self,
        table: ClusterDiagnosticsTable,
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.table, self.actions, self.now = table, actions, now

    async def project(self, request: RenderRequest) -> ProjectedRows[DiagnosticRow]:
        rows = await parse_owned(
            partial(diagnostic_rows, request.observation.diagnostics, now=self.now())
        )
        return ProjectedRows(rows, lambda: True)

    async def filter(
        self, rows: tuple[DiagnosticRow, ...], request: RenderRequest
    ) -> FilterResult[DiagnosticRow]:
        result = await apply_filter(rows, request.query, "diagnostic findings")
        selected = {row.key for row in result.rows}
        return FilterResult(
            tuple(row for row in rows if row.finding is None or row.key in selected),
            result.problem,
            result.unknown,
        )

    async def apply(self, rows: tuple[DiagnosticRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.observation.diagnostics, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
