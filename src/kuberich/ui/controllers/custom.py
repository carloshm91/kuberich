"""Own bounded server layouts and bind each projection to its captured schema."""

from collections.abc import Callable
from typing import Protocol

from kuberich.domain.custom import CustomLayout
from kuberich.domain.navigation import MAX_HISTORY, Viewport
from kuberich.domain.registry import ResourceRow
from kuberich.domain.resources import ApiResource
from kuberich.domain.views import ViewObservation
from kuberich.services.filtering import FilterResult
from kuberich.services.pods import CustomProjection, ResourceProjection
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter
from kuberich.ui.controllers.resources import ResourceTable


class CustomResourceTable(ResourceTable[ResourceRow], Protocol):
    @property
    def resource_layout(self) -> CustomLayout | None: ...

    def configure_layout(self, layout: CustomLayout, revision: int) -> None: ...


class CustomPreferences(Protocol):
    def prepare(
        self, view: ViewObservation, layout: CustomLayout | None = None
    ) -> CustomLayout | None: ...

    def configure_custom(self, view: ViewObservation) -> None: ...


class CustomController:
    def __init__(
        self,
        table: CustomResourceTable,
        filtering: ResourceFilter,
        preferences: CustomPreferences,
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: Callable[[CustomLayout], ResourceProjection[ResourceRow]] = CustomProjection,
    ) -> None:
        self.table, self.filtering = table, filtering
        self.preferences, self.actions = preferences, actions
        self._layouts: dict[tuple[str, str, str, str], CustomLayout] = {}
        self.factory = projection
        self._projection: ResourceProjection[ResourceRow] | None = None
        self._projection_layout: CustomLayout | None = None

    def reset_context(self) -> None:
        """Discard context-specific layout preferences on connection replacement."""
        self._layouts.clear()

    def layout_for(self, context: str | None, resource: ApiResource) -> CustomLayout:
        key = (context or "", resource.group, resource.version, resource.name)
        return self._layouts.get(key) or CustomLayout.build(resource, ())

    def remember_layout(self, context: str | None, layout: CustomLayout) -> None:
        resource = layout.resource
        key = (context or "", resource.group, resource.version, resource.name)
        self._layouts.pop(key, None)
        self._layouts[key] = layout
        while len(self._layouts) > MAX_HISTORY:
            del self._layouts[next(iter(self._layouts))]

    def configure(self, layout: CustomLayout, revision: int) -> None:
        """An explicit column choice owns a fresh decoder, including default."""
        self.table.configure_layout(layout, revision)
        self._projection = self.factory(layout)
        self._projection_layout = layout

    async def retire_projection(self) -> None:
        if self._projection is not None:
            await self._projection.project(None)

    async def project(self, request: RenderRequest) -> ProjectedRows[ResourceRow]:
        view = request.observation
        snapshot = view.snapshot
        layout = self.table.resource_layout
        if snapshot is not None:
            key = (
                view.context or "",
                snapshot.resource.group,
                snapshot.resource.version,
                snapshot.resource.name,
            )
            layout = self._layouts.get(key)
            if (
                layout is None
                or layout.resource != snapshot.resource
                or layout.headers != snapshot.columns
            ):
                layout = CustomLayout.build(snapshot.resource, snapshot.columns)
            layout = self.preferences.prepare(view, layout) or layout
            self.remember_layout(view.context, layout)
            if self.table.resource_layout != layout:
                self.table.configure_layout(layout, view.revision)
            if self._projection_layout != layout:
                self._projection = self.factory(layout)
                self._projection_layout = layout
            self.preferences.configure_custom(view)
        projection = self._projection
        try:
            rows = await projection.project(snapshot) if projection is not None else ()
        finally:
            if projection is not None and projection is not self._projection:
                # Explicit columns can replace the decoder while its owned
                # worker is draining. Release that retired owner's records too.
                await projection.project(None)
        return ProjectedRows(rows, lambda: layout is None or layout == self.table.resource_layout)

    async def filter(
        self, rows: tuple[ResourceRow, ...], request: RenderRequest
    ) -> FilterResult[ResourceRow]:
        return await self.filtering.apply(rows, request)

    async def apply(self, rows: tuple[ResourceRow, ...], request: RenderRequest) -> bool:
        return await self.table.apply_rows(rows, request.observation.revision, request.current)

    def capture_viewport(self) -> Viewport:
        return self.table.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.table.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.actions(request)
