"""Own the five real resource tables, typed route and lazy render adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kuberich.config.catalog import KubeCatalog
from kuberich.domain.custom import CustomLayout
from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import RESOURCE_ALIASES, ResourceDefinition, ResourceRow
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.services.pods import ResourceProjection
from kuberich.ui.contexts import ContextTable
from kuberich.ui.controllers.base import RenderOutcome, RenderRequest, ViewDriver
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from kuberich.ui.controllers.registry import ViewEntry, ViewRegistry
from kuberich.ui.controllers.rendering import RenderCoordinator
from kuberich.ui.custom import CustomTable
from kuberich.ui.foreground import ForegroundGate
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable

if TYPE_CHECKING:
    from kuberich.ui.controllers.custom import CustomController, CustomPreferences


@dataclass(frozen=True)
class RootTables:
    pods: PodTable
    namespaces: NamespaceTable
    contexts: ContextTable
    standard: StandardTable
    custom: CustomTable


class RootViews:
    def __init__(
        self,
        tables: RootTables,
        foreground: ForegroundGate,
        catalog: Callable[[], KubeCatalog],
        preferences: CustomPreferences,
        metadata: MetadataFilter,
        options: Callable[[str | None], FilterOptions],
        actions: Callable[[RenderRequest], frozenset[str]],
        capture: Callable[[], RenderRequest],
        publish: Callable[[RenderRequest, RenderOutcome], None],
        failed: Callable[[Exception], None],
        *,
        pod_projection: Callable[[], ResourceProjection[PodRow]],
        namespace_projection: Callable[[], ResourceProjection[NamespaceRow]],
        standard_projection: Callable[[ResourceDefinition], ResourceProjection[ResourceRow]],
        custom_projection: Callable[[CustomLayout], ResourceProjection[ResourceRow]],
        recover: Callable[[RenderRequest, Exception | None], None] | None = None,
    ) -> None:
        self.tables, self.foreground = tables, foreground
        self._by_kind: dict[ViewKind, PodTable | NamespaceTable | ContextTable | StandardTable] = {
            ViewKind.PODS: tables.pods,
            ViewKind.NAMESPACES: tables.namespaces,
            ViewKind.CONTEXTS: tables.contexts,
            ViewKind.STANDARD: tables.standard,
            ViewKind.CUSTOM: tables.custom,
        }
        self.catalog, self.preferences, self.actions = catalog, preferences, actions
        self.filtering = ResourceFilter(metadata, options)
        self.route = ViewRoute.pods()
        self._pod_factory, self._namespace_factory = pod_projection, namespace_projection
        self._standard_factory, self._custom_factory = standard_projection, custom_projection
        self._custom: CustomController | None = None
        self.registry = ViewRegistry(
            {
                ViewKind.PODS: self._pods,
                ViewKind.NAMESPACES: self._namespaces,
                ViewKind.CONTEXTS: self._contexts,
                ViewKind.STANDARD: self._standard,
                ViewKind.CUSTOM: self._custom_entry,
            }
        )
        self.renderer = RenderCoordinator(
            foreground, self.registry, capture, publish, failed, recover=recover
        )

    @property
    def table(self) -> PodTable | NamespaceTable | ContextTable | StandardTable:
        return self._by_kind[self.route.kind]

    def select(self, route: ViewRoute) -> None:
        selected = self._by_kind[route.kind]
        self.route = route
        for table in self._by_kind.values():
            table.display = table is selected
        if route.kind is ViewKind.STANDARD:
            definition = RESOURCE_ALIASES[route.resource_name or ""]
            if self.tables.standard.definition != definition:
                self.tables.standard.configure(definition)

    def _pods(self) -> ViewEntry:
        from kuberich.ui.controllers.pods import PodController

        controller = PodController(
            self.tables.pods,
            self.filtering,
            self.preferences.prepare,
            self.actions,
            projection=self._pod_factory(),
        )
        return ViewEntry(ViewDriver(controller), controller.retire_projection)

    def _namespaces(self) -> ViewEntry:
        from kuberich.ui.controllers.namespaces import NamespaceController

        controller = NamespaceController(
            self.tables.namespaces,
            self.filtering,
            self.preferences.prepare,
            self.actions,
            projection=self._namespace_factory(),
        )
        return ViewEntry(ViewDriver(controller), controller.retire_projection)

    def _contexts(self) -> ViewEntry:
        from kuberich.ui.controllers.contexts import ContextController

        controller = ContextController(self.tables.contexts, self.catalog, self.actions)
        return ViewEntry(ViewDriver(controller))

    def _standard(self) -> ViewEntry:
        from kuberich.ui.controllers.standard import StandardController

        controller = StandardController(
            self.tables.standard,
            lambda: self.tables.standard.definition,
            self.filtering,
            self.preferences.prepare,
            self.actions,
            projection=self._standard_factory,
        )
        return ViewEntry(ViewDriver(controller), controller.retire_projection)

    @property
    def custom(self) -> CustomController:
        if self._custom is None:
            from kuberich.ui.controllers.custom import CustomController

            self._custom = CustomController(
                self.tables.custom,
                self.filtering,
                self.preferences,
                self.actions,
                projection=self._custom_factory,
            )
        return self._custom

    def _custom_entry(self) -> ViewEntry:
        return ViewEntry(ViewDriver(self.custom), close=self.custom.retire_projection)

    def reset_context(self) -> None:
        if self._custom is not None:
            self._custom.reset_context()

    def remember_layout(self, context: str | None, layout: CustomLayout) -> None:
        self.custom.remember_layout(context, layout)

    def request(self) -> None:
        self.renderer.request()

    def start(self) -> None:
        self.renderer.start()

    async def close(self) -> None:
        try:
            await self.renderer.close()
        finally:
            await self.registry.close()
