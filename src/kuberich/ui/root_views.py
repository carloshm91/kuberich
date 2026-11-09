"""Own the five real resource tables, typed route and lazy render adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from kuberich.config.catalog import KubeCatalog
from kuberich.domain.curated_navigation import ResolvedCollectionBookmark
from kuberich.domain.custom import CustomLayout
from kuberich.domain.events import EventOptions
from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import PodRow
from kuberich.domain.pulse import PulseDrilldown
from kuberich.domain.registry import (
    EVENT_METADATA_DEFINITION,
    RESOURCE_ALIASES,
    ResourceDefinition,
    ResourceRow,
)
from kuberich.domain.resources import ApiResource
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.services.pods import ResourceProjection
from kuberich.ui.authorization import AuthorizationTable
from kuberich.ui.cluster_diagnostics import ClusterDiagnosticsTable
from kuberich.ui.contexts import ContextTable
from kuberich.ui.controllers.base import RenderOutcome, RenderRequest, ViewDriver
from kuberich.ui.controllers.filtering import FilterOptions, ResourceFilter
from kuberich.ui.controllers.registry import ViewEntry, ViewRegistry
from kuberich.ui.controllers.rendering import RenderCoordinator
from kuberich.ui.custom import CustomTable
from kuberich.ui.event_source import EventSourceClock
from kuberich.ui.events import EventsTable
from kuberich.ui.foreground import ForegroundGate
from kuberich.ui.helm import HelmReleaseTable
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.pulse import PulseTable
from kuberich.ui.relationships import RelationshipTable
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
    pulse: PulseTable
    relationships: RelationshipTable
    authorization: AuthorizationTable
    diagnostics: ClusterDiagnosticsTable
    events: EventsTable
    helm: HelmReleaseTable


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
        standard_projection: Callable[
            [ResourceDefinition, ApiResource | None], ResourceProjection[ResourceRow]
        ],
        custom_projection: Callable[[CustomLayout], ResourceProjection[ResourceRow]],
        recover: Callable[[RenderRequest, Exception | None], None] | None = None,
    ) -> None:
        self.tables, self.foreground = tables, foreground
        self._by_kind: dict[
            ViewKind,
            PodTable
            | NamespaceTable
            | ContextTable
            | StandardTable
            | PulseTable
            | RelationshipTable
            | AuthorizationTable
            | ClusterDiagnosticsTable
            | EventsTable
            | HelmReleaseTable,
        ] = {
            ViewKind.HELM: tables.helm,
            ViewKind.DIAGNOSTICS: tables.diagnostics,
            ViewKind.AUTHORIZATION: tables.authorization,
            ViewKind.RELATIONSHIPS: tables.relationships,
            ViewKind.PULSE: tables.pulse,
            ViewKind.PODS: tables.pods,
            ViewKind.NAMESPACES: tables.namespaces,
            ViewKind.CONTEXTS: tables.contexts,
            ViewKind.STANDARD: tables.standard,
            ViewKind.CUSTOM: tables.custom,
            ViewKind.EVENTS: tables.events,
        }
        self.catalog, self.preferences, self.actions = catalog, preferences, actions
        self.filtering = ResourceFilter(metadata, options)
        self.route = ViewRoute.pods()
        self.drilldown: PulseDrilldown | None = None
        self.expected_uid: str | None = None
        self.curated: ResolvedCollectionBookmark | None = None
        self.event_options = EventOptions()
        self.event_source = EventSourceClock()
        self._pod_factory, self._namespace_factory = pod_projection, namespace_projection
        self._standard_factory, self._custom_factory = standard_projection, custom_projection
        self._custom: CustomController | None = None
        self.registry = ViewRegistry(
            {
                ViewKind.HELM: self._helm,
                ViewKind.DIAGNOSTICS: self._diagnostics,
                ViewKind.AUTHORIZATION: self._authorization,
                ViewKind.RELATIONSHIPS: self._relationships,
                ViewKind.PULSE: self._pulse,
                ViewKind.PODS: self._pods,
                ViewKind.NAMESPACES: self._namespaces,
                ViewKind.CONTEXTS: self._contexts,
                ViewKind.STANDARD: self._standard,
                ViewKind.CUSTOM: self._custom_entry,
                ViewKind.EVENTS: self._events,
            }
        )
        self.renderer = RenderCoordinator(
            foreground, self.registry, capture, publish, failed, recover=recover
        )

    @property
    def table(
        self,
    ) -> (
        PodTable
        | NamespaceTable
        | ContextTable
        | StandardTable
        | PulseTable
        | RelationshipTable
        | AuthorizationTable
        | ClusterDiagnosticsTable
        | EventsTable
        | HelmReleaseTable
    ):
        return self._by_kind[self.route.kind]

    def select(self, route: ViewRoute) -> None:
        selected = self._by_kind[route.kind]
        self.route = route
        for table in self._by_kind.values():
            table.display = table is selected
        if route.kind is ViewKind.STANDARD:
            definition = (
                replace(EVENT_METADATA_DEFINITION, group=route.selection.group)
                if route.selection is not None and route.resource_name == "events"
                else RESOURCE_ALIASES[route.resource_name or ""]
            )
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

    def _pulse(self) -> ViewEntry:
        from kuberich.ui.controllers.pulse import PulseController

        return ViewEntry(ViewDriver(PulseController(self.tables.pulse, self.actions)))

    def _relationships(self) -> ViewEntry:
        from kuberich.ui.controllers.relationships import RelationshipController

        return ViewEntry(
            ViewDriver(RelationshipController(self.tables.relationships, self.actions))
        )

    def _authorization(self) -> ViewEntry:
        from kuberich.ui.controllers.authorization import AuthorizationController

        return ViewEntry(
            ViewDriver(AuthorizationController(self.tables.authorization, self.actions))
        )

    def _diagnostics(self) -> ViewEntry:
        from kuberich.ui.controllers.cluster_diagnostics import ClusterDiagnosticsController

        return ViewEntry(
            ViewDriver(ClusterDiagnosticsController(self.tables.diagnostics, self.actions))
        )

    def _helm(self) -> ViewEntry:
        from kuberich.ui.controllers.helm import HelmController

        return ViewEntry(ViewDriver(HelmController(self.tables.helm, self.actions)))

    def _events(self) -> ViewEntry:
        from kuberich.ui.controllers.events import EventsController

        controller = EventsController(
            self.tables.events,
            lambda: self.event_options,
            self.event_source.capture,
            self.actions,
        )
        return ViewEntry(ViewDriver(controller), controller.retire_projection)

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
        self.expected_uid = None
        self.curated = None
        self.event_options = EventOptions()
        self.event_source.reset()
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
