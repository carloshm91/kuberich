"""Capture Event options before projection and guard every later table publication."""

from collections.abc import Callable

from kuberich.domain.events import EventObjectRow, EventOptions, EventRow, EventSourceState
from kuberich.domain.navigation import Viewport
from kuberich.domain.views import ViewObservation
from kuberich.services.events import EventProjection, EventProjectionResult
from kuberich.services.filtering import FilterResult, apply_filter
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.events import EventsTable


class EventsController:
    def __init__(
        self,
        table: EventsTable,
        options: Callable[[], EventOptions],
        source: Callable[[ViewObservation], EventSourceState | None],
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: EventProjection | None = None,
    ) -> None:
        self.table, self.options, self.source, self.actions = table, options, source, actions
        self.projection = projection if projection is not None else EventProjection()
        self._generation = 0
        self._publication: tuple[EventProjectionResult, EventOptions] | None = None

    async def project(self, request: RenderRequest) -> ProjectedRows[EventRow]:
        self._generation += 1
        generation = self._generation
        options, source, bookmark = (
            self.options(),
            self.source(request.observation),
            request.curated,
        )
        result = await self.projection.project(
            request.observation.snapshot, source, options, bookmark=bookmark
        )

        def current() -> bool:
            return generation == self._generation and self.options() == options

        if current() and request.current():
            self._publication = result, options
        rows = result.rows
        if request.expected_uid is not None:
            rows = tuple(
                row
                for row in rows
                if isinstance(row, EventObjectRow) and row.uid == request.expected_uid
            )
        return ProjectedRows(rows, current)

    async def filter(
        self, rows: tuple[EventRow, ...], request: RenderRequest
    ) -> FilterResult[EventRow]:
        return await apply_filter(rows, request.query, "events")

    async def apply(self, rows: tuple[EventRow, ...], request: RenderRequest) -> bool:
        publication, generation = self._publication, self._generation
        if publication is None:
            return False
        result, options = publication
        return await self.table.apply_rows(
            rows,
            request.observation.revision,
            lambda: (
                request.current() and generation == self._generation and self.options() == options
            ),
            source=result.source,
            options=options,
            limited=result.limited,
            notices=result.notices,
        )

    async def retire_projection(self) -> None:
        self._generation += 1
        self._publication = None
        await self.projection.retire()

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
