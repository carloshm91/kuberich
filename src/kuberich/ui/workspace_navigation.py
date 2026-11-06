"""Own context/resource history and restoration through explicit workspace ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Input

from kuberich.adapters.credentials import CredentialLogin
from kuberich.domain.cluster_diagnostics import DiagnosticBookmark
from kuberich.domain.curated_navigation import AllResources, ResolvedCollectionBookmark
from kuberich.domain.custom import CustomLayout
from kuberich.domain.events import EventGroupMembers, EventOptions, event_descriptor_supported
from kuberich.domain.navigation import NamespaceChoice, NavigationHistory, NavigationState, Viewport
from kuberich.domain.pods import PodColumn
from kuberich.domain.registry import RESOURCE_ALIASES, resource_selection
from kuberich.domain.relationships import (
    RelationshipBookmark,
    RelationshipMode,
    RelationshipPath,
    RelationshipRef,
    relationship_actionable,
    resolve_reference,
)
from kuberich.domain.resource_queries import ResourceQuery, query_command
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceSelection, ViewObservation, ViewStatus
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.security.presentation import safe_text
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import (
    Command,
    GenericResourceCommand,
    ResolvedCommand,
    ResourceCommand,
    ScopedCommand,
)
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from kuberich.ui.chrome import (
    CTX_SHORTCUTS,
    NS_SHORTCUTS,
    POD_SHORTCUTS,
    RESOURCE_SHORTCUTS,
    SERVICE_SHORTCUTS,
    WorkspaceHeader,
    WorkspaceLabel,
    workload_shortcuts,
)
from kuberich.ui.cluster_diagnostics import ClusterDiagnosticsTable
from kuberich.ui.commands import CommandInput
from kuberich.ui.contexts import ContextTable
from kuberich.ui.events import EventsTable
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.root_views import RootViews
from kuberich.ui.standard import StandardTable
from kuberich.ui.views import ViewPreferences

if TYPE_CHECKING:
    from kuberich.services.curated_navigation import CuratedOrigin, ResolvedCuratedDestination
    from kuberich.ui.authorization_navigation import AuthorizationNavigation
    from kuberich.ui.diagnostic_navigation import DiagnosticNavigation


@dataclass(frozen=True)
class NavigationTrail:
    tokens: tuple[str, ...]
    destination: str


class WorkspaceNavigation:
    def __init__(
        self,
        host: App[None],
        sessions: SessionService,
        workspace: WorkspaceService,
        views: RootViews,
        history: NavigationHistory,
        filter_input: Input,
        command_input: CommandInput,
        header: WorkspaceHeader,
        view_preferences: ViewPreferences,
        policy: AccessPolicy,
        status: Callable[[str], None],
        notice: Callable[[str], None],
        apply_theme: Callable[[str | None], None],
        changed: Callable[[], None],
        disable_favorites: Callable[[], None],
        favorites: Callable[[str], tuple[str, ...]],
        *,
        errors: Callable[[], bool] = lambda: False,
        set_errors: Callable[[bool], None] = lambda _: None,
    ) -> None:
        self.host, self.sessions, self.workspace, self.views = host, sessions, workspace, views
        self.history, self.filter_input, self.command_input = history, filter_input, command_input
        self.header, self.view_preferences, self.policy = header, view_preferences, policy
        self.status, self.notice, self.apply_theme, self.changed = (
            status,
            notice,
            apply_theme,
            changed,
        )
        self.disable_favorites, self.favorites = disable_favorites, favorites
        self.errors, self.set_errors = errors, set_errors
        self._restore_state: tuple[int, NavigationState] | None = None
        self._context_parent: NavigationState | None = None
        self._context_state: NavigationState | None = None
        self._namespace_parent: NavigationState | None = None
        self._namespace_state: NavigationState | None = None
        self._namespace_route = False
        self._column_notice: str | None = None
        self._pending_generic: GenericResourceCommand | None = None
        self._pending_relationships: NavigationState | None = None
        self.authorization: AuthorizationNavigation | None = None
        self.diagnostics: DiagnosticNavigation | None = None

    @property
    def resource_name(self) -> str:
        return self.views.route.display_key

    @property
    def generic_selection(self) -> ResourceSelection | None:
        route = self.views.route
        return route.selection if route.kind is ViewKind.CUSTOM else None

    def clear_column_notice(self) -> None:
        self._column_notice = None

    def set_column_notice(self, message: str) -> None:
        self._column_notice = message

    def cancel_pending_resource_restore(self) -> None:
        """A newer native intent replaces deferred graph/generic destinations."""
        self._pending_relationships = None
        self._pending_generic = None

    def command_error(self, message: str) -> None:
        if self.views.route.kind is ViewKind.CUSTOM:
            self._column_notice = message
        self.status(message)

    def resolve_pending(self) -> None:
        if self.diagnostics is not None:
            self.diagnostics.resolve_pending()
        if self.authorization is not None:
            self.authorization.resolve_pending()
        if self._pending_relationships is not None and self.workspace.discovery is not None:
            state, self._pending_relationships = self._pending_relationships, None
            self.restore(state)
        if self._pending_generic is not None and self.workspace.discovery is not None:
            command, self._pending_generic = self._pending_generic, None
            self.generic(command)

    def initialize(
        self, initial: ResolvedCommand, apply: Callable[[ResolvedCommand], None]
    ) -> None:
        if initial is Command.EXPORTS:
            apply(initial)
            return
        context = self.sessions.request.context or self.sessions.catalog.current
        if initial is Command.NAMESPACES:
            self.workspace.prepare_resource(ResourceSelection("namespaces"))
            self.display("namespaces")
        scope = None
        if isinstance(initial, ScopedCommand):
            if initial.command is Command.CONTEXTS:
                context = initial.argument
            else:
                scope = NamespaceChoice(None if initial.argument == "*" else initial.argument)
        if isinstance(initial, ResourceCommand):
            self.workspace.prepare_resource(initial.definition.selection)
            self.display(initial.definition.name)
            if initial.scope is not None:
                scope = NamespaceChoice(None if initial.scope == "*" else initial.scope)
        if isinstance(initial, GenericResourceCommand):
            self._pending_generic = initial
        if initial is Command.EVENTS or (
            isinstance(initial, ScopedCommand) and initial.command is Command.EVENTS
        ):
            self._pending_generic = GenericResourceCommand(
                "events", scope=initial.argument if isinstance(initial, ScopedCommand) else None
            )
        if (
            context is not None
            and initial is not Command.THEMES
            and initial is not Command.ABOUT
            and initial is not Command.VIEWS
        ):
            self.connect(context, scope=scope)
        if (
            not isinstance(initial, (ScopedCommand, ResourceCommand, GenericResourceCommand))
            and initial is not Command.NAMESPACES
        ):
            apply(initial)

    def connect(
        self,
        context: str,
        *,
        scope: NamespaceChoice | None = None,
        remember: bool = True,
        authenticate: CredentialLogin | None = None,
    ) -> None:
        try:
            validate_argument(context)
        except AppError as error:
            self.status(str(error))
            return
        if remember:
            self._pending_relationships = None
            self.remember()
        if self.authorization is not None:
            self.authorization.context_changing(context, explicit=remember)
        if self.diagnostics is not None:
            self.diagnostics.context_changing(context, explicit=remember)
        if context != self.workspace.store.observation.context:
            self._namespace_parent = self._namespace_state = None
            self._namespace_route = False
            self.views.reset_context()
            if self.resource_name == "relationships":
                self.workspace.prepare_resource(ResourceSelection("pods"))
                self.display("pods")
        self.apply_theme(context)
        self.workspace.connect(context, scope=scope, authenticate=authenticate)
        self.clear_rows()
        self.header.update_identity()
        self.changed()
        self.status("Connecting · F2 contexts · F4 retry · Ctrl+Q quit")

    def contexts(self) -> None:
        self._pending_relationships = None
        if not self.sessions.catalog.names:
            self.notice("No contexts found. Configure KUBECONFIG or use --kubeconfig.")
        elif not isinstance(self.host.screen, ModalScreen):
            if self.resource_name == "contexts":
                self.host.set_focus(self.views.tables.contexts)
                return
            self._context_parent = self.capture()
            self.remember()
            self.display("contexts")
            self.filter_input.value = (
                self._context_state.query if self._context_state is not None else ""
            )
            if self._context_state is not None:
                self._restore_state = self.workspace.store.observation.revision, self._context_state
            self.command_input.reset_choice()
            self.views.request()

    def context_selected(self, value: str | None) -> None:
        if value is not None:
            diagnostic_parent = (
                self._context_parent if self.resource_name == "contexts" else self.capture()
            )
            self._pending_relationships = None
            self._context_state = (
                self.capture() if self.resource_name == "contexts" else self._context_state
            )
            self.remember()
            if (
                self.diagnostics is not None
                and diagnostic_parent is not None
                and diagnostic_parent.diagnostics is not None
            ):
                self.display("diagnostics")
                self.diagnostics.context_changing(value, explicit=True)
                self.filter_input.value = ""
                self.connect(value, remember=False)
                return
            self.workspace.prepare_resource(ResourceSelection("pods"))
            self.display("pods")
            self.filter_input.value = ""
            self.connect(value, remember=False)

    def clear_rows(self) -> None:
        self._restore_state = None
        if self.resource_name == "contexts":
            self.command_input.reset_choice()
            self.views.request()
            return
        table = self.views.table
        assert not isinstance(table, ContextTable)
        table.reset(self.workspace.store.observation.revision)
        self.views.table.remove_class("populated")
        self.host.query_one("#empty-state").set_class(False, "populated")
        self.host.query_one("#empty-title", WorkspaceLabel).update_text("Loading resources")
        self.command_input.reset_choice()

    def pulse(self, *, restore: NavigationState | None = None, remember: bool = True) -> None:
        self._pending_relationships = None
        if isinstance(self.host.screen, ModalScreen):
            return
        if self.resource_name == "pulse" and restore is None:
            self.host.set_focus(self.views.tables.pulse)
            return
        if remember:
            self.remember()
        self.workspace.select_pulse()
        self.display("pulse")
        self.clear_rows()
        self.filter_input.value = restore.query if restore is not None else ""
        if restore is not None:
            self.set_errors(restore.errors)
            self._restore_state = self.workspace.store.observation.revision, restore
        self.views.request()

    def pulse_selected(self, key: str | None) -> None:
        snapshot = self.workspace.store.observation.pulse
        if (
            self.views.route.kind is not ViewKind.PULSE
            or snapshot is None
            or snapshot.scope.session != self.sessions.observation.identity
            or snapshot.scope != self.views.tables.pulse.scope
        ):
            self.notice("Pulse scope changed; select a current summary before drilling down.")
            return
        drilldown = self.views.tables.pulse.drilldown(key)
        if drilldown is None:
            self.notice("This aggregate has no resource drill-down. Select a health summary.")
            return
        # Capture the served API, namespace, predicate, sort and optional UID before selection.
        resource = drilldown.resource
        known = RESOURCE_ALIASES.get(resource.name)
        generic = (
            ResourceSelection(
                resource.name, resource.group, resource.version, True, drilldown.query
            )
            if not (resource.name == "pods" and not resource.group)
            and (known is None or known.group != resource.group)
            else None
        )
        state = NavigationState(
            snapshot.scope.session.context,
            drilldown.namespace if resource.namespaced else snapshot.scope.namespace,
            column=drilldown.sort,
            descending=drilldown.descending,
            selected=drilldown.uid,
            resource=resource.name,
            generic=generic,
            server_query=drilldown.query,
            drilldown=drilldown,
        )
        self.select_resource(
            resource.name,
            restore=state,
            scope=NamespaceChoice(state.namespace),
            generic=generic,
        )

    def relationships(
        self,
        target: ResourceTarget,
        resource: ApiResource,
        mode: RelationshipMode,
        *,
        restore: NavigationState | None = None,
        remember: bool = True,
    ) -> None:
        self._pending_relationships = None
        if mode is RelationshipMode.USED_BY and (resource.group, resource.name) not in {
            ("", "configmaps"),
            ("", "secrets"),
            ("", "serviceaccounts"),
            ("", "persistentvolumeclaims"),
            ("scheduling.k8s.io", "priorityclasses"),
        }:
            self.notice(
                "UsedBy supports ConfigMaps, Secrets, ServiceAccounts, PVCs and PriorityClasses."
            )
            return
        previous = self.capture()
        try:
            self.workspace.select_relationships(
                target,
                resource,
                mode,
                expanded=restore.relationships.expanded
                if restore is not None and restore.relationships is not None
                else frozenset({()}),
            )
        except AppError as error:
            self.notice(str(error))
            return
        if remember and previous is not None:
            self.history.visit(previous)
        self.display("relationships")
        self.clear_rows()
        self.filter_input.value = restore.query if restore is not None else ""
        self.set_errors(False)
        if restore is not None:
            self._restore_state = self.workspace.store.observation.revision, restore
        self.views.request()

    def expand_relationship(self, path: RelationshipPath, expanded: bool) -> None:
        table = self.views.tables.relationships
        if (
            self.views.route.kind is not ViewKind.RELATIONSHIPS
            or table.request is None
            or table.request != self.workspace.relationship_request
            or table.request.scope.root.session != self.sessions.observation.identity
        ):
            self.notice("Relationship scope changed; select a current row.")
            return
        row = table.row_at(path)
        if row is None or not row.expandable:
            self.notice("This relationship cannot expand. Use o to open an available resource.")
            return
        state = self.capture()
        self.workspace.set_relationship_expanded(path, expanded=expanded)
        if state is not None:
            self._restore_state = self.workspace.store.observation.revision, state
        self.views.request()

    def relationship_selected(self, path: RelationshipPath | None) -> None:
        if path is not None:
            request = self.views.tables.relationships.request
            if request is not None:
                self.expand_relationship(path, path not in request.expanded)

    def open_resource(
        self,
        resource: ApiResource,
        namespace: str | None,
        *,
        uid: str | None = None,
        query: str = "",
        bookmark: ResolvedCollectionBookmark | None = None,
    ) -> None:
        """Open a discovered descriptor through the normal navigation/history path."""
        namespace = namespace if resource.namespaced else None
        if bookmark is not None and (
            bookmark.resource != resource or bookmark.namespace != namespace
        ):
            self.notice("The captured collection does not match its resource destination.")
            return
        discovery = self.workspace.discovery
        known = RESOURCE_ALIASES.get(resource.name)
        preferred = discovery is not None and resource == discovery.resolve(
            resource.name, group=resource.group
        )
        builtin = (
            (resource.name == "events" and resource.group in {"", "events.k8s.io"})
            or (not resource.group and resource.name in {"pods", "namespaces"})
            or (known is not None and known.group == resource.group)
        ) and (preferred or (known is not None and known.curated) or resource.name == "events")
        generic = (
            None
            if builtin
            else ResourceSelection(resource.name, resource.group, resource.version, True)
        )
        context = self.workspace.store.observation.context
        if context is None:
            return
        state = NavigationState(
            context,
            namespace
            if resource.namespaced
            else self.workspace.store.observation.connection.namespace,
            query=query,
            selected=uid,
            resource=resource.name if builtin else resource.name + "." + (resource.group or "core"),
            generic=generic,
            server_query=bookmark.query if bookmark is not None else ResourceQuery(),
            expected_uid=uid,
            curated=bookmark
            or (
                ResolvedCollectionBookmark(resource, namespace, AllResources(), ResourceQuery())
                if (known is not None and known.group == resource.group and known.curated)
                or (resource.name == "events" and resource.group in {"", "events.k8s.io"})
                else None
            ),
        )
        self.select_resource(
            state.resource, restore=state, scope=NamespaceChoice(state.namespace), generic=generic
        )

    def events_options(self, options: EventOptions) -> None:
        """Change local Events presentation without restarting its owned watch."""
        if self.views.route.kind is not ViewKind.EVENTS:
            return
        if self.views.expected_uid is not None and options.grouped:
            self.notice("This view follows one captured Event; use :events before grouping.")
            return
        if options == self.views.event_options:
            return
        self.remember()
        self.views.event_options = options
        self.views.request()

    def events(self, namespace: str | None = None) -> None:
        """Choose an actually discovered Event API; explicit GVR commands remain exact."""
        discovery = self.workspace.discovery
        if discovery is None:
            self.notice("Wait for the current resource catalogue before browsing Events.")
            return
        candidates = tuple(
            resource
            for resource in discovery.resources
            if resource.name == "events" and resource.group in {"", "events.k8s.io"}
        )
        supported = tuple(
            resource for resource in candidates if event_descriptor_supported(resource)
        )
        resource = next((item for item in supported if item.group == "events.k8s.io"), None)
        resource = resource or (
            supported[0] if supported else candidates[0] if candidates else None
        )
        if resource is None:
            self.notice("No Event API was discovered; check discovery and permissions.")
            return
        if namespace is not None and not resource.namespaced:
            self.notice(
                "The discovered Event resource is cluster-scoped; omit the namespace argument."
            )
            return
        self.open_resource(
            resource,
            (None if namespace == "*" else namespace)
            if namespace is not None
            else self.workspace.store.observation.connection.namespace,
        )

    def events_current(self) -> bool:
        if self.views.route.kind is not ViewKind.EVENTS:
            return False
        table = self.views.tables.events
        source = table.source
        observation = self.workspace.store.observation
        return (
            source is not None
            and source.scope == observation.scope
            and source.revision == observation.revision
            and table.options == self.views.event_options
        )

    def events_selected(self) -> bool:
        """Handle a group or refuse obsolete rows; False permits current raw inspection."""
        if not self.events_current():
            self.notice("The Events source or options changed; wait for current rows.")
            return True
        table = self.views.tables.events
        group = table.selected_group()
        if group is None:
            if table.selected_event_uid() is not None:
                return False
            self.notice("Select a current Event or group before opening it.")
            return True
        self.events_options(
            replace(table.options, grouped=False, members=EventGroupMembers(group.key))
        )
        return True

    def curated_current(self, origin: CuratedOrigin) -> bool:
        """Keep fresh GET identity compatible with its unchanged observed baseline."""
        view = self.workspace.store.observation
        if (
            view.revision != origin.revision
            or view.scope is None
            or view.scope.session != origin.session
            or self.sessions.observation.identity != origin.session
            or view.scope.resource != origin.resource
            or view.snapshot is None
            or view.status is ViewStatus.FAILED
        ):
            return False
        return any(
            record.uid == origin.record_uid
            and record.name == origin.record_name
            and record.namespace == origin.namespace
            and record.resource_version
            in {
                origin.observed_resource_version,
                origin.resource_version,
            }
            for record in view.snapshot.items
        )

    def open_curated(self, origin: CuratedOrigin, destination: ResolvedCuratedDestination) -> None:
        """Apply an explicit inspector intent without recapturing another selected row."""
        from kuberich.domain.curated_navigation import (
            AuthorizationDestination,
            RelationshipDestination,
        )
        from kuberich.services.curated_navigation import ResolvedCollection, ResolvedObject

        if len(self.host.screen_stack) != 1 or not self.curated_current(origin):
            self.notice("The captured resource changed; reopen its details before navigating.")
            return
        if isinstance(destination, ResolvedCollection):
            self.open_resource(
                destination.resource,
                destination.namespace,
                bookmark=ResolvedCollectionBookmark(
                    destination.resource,
                    destination.namespace,
                    destination.predicate,
                    destination.query,
                ),
            )
        elif isinstance(destination, ResolvedObject):
            self.open_resource(
                destination.resource, destination.record.namespace, uid=destination.record.uid
            )
        elif isinstance(destination, RelationshipDestination):
            self.relationships(
                ResourceTarget(
                    origin.session,
                    origin.resource.group,
                    origin.resource.name,
                    origin.namespace,
                    origin.record_name,
                    origin.record_uid,
                ),
                origin.resource,
                destination.mode,
            )
        elif isinstance(destination, AuthorizationDestination) and self.authorization is not None:
            self.authorization.open(destination.intent)

    def open_relationship(self, path: RelationshipPath | None) -> None:
        table = self.views.tables.relationships
        if (
            path is None
            or self.views.route.kind is not ViewKind.RELATIONSHIPS
            or table.request is None
            or table.request != self.workspace.relationship_request
            or table.request.scope.root.session != self.sessions.observation.identity
        ):
            self.notice("Select a current resource relationship before opening it.")
            return
        row = table.row_at(path)
        if row is None or not relationship_actionable(row) or row.ref.resource is None:
            self.notice(
                "This relationship is unavailable or its identity changed; refresh the graph."
            )
            return
        self.open_resource(row.ref.resource, row.ref.namespace, uid=row.observed_uid)

    def namespaces(self) -> None:
        self.disable_favorites()
        observation = self.workspace.store.observation.connection
        if observation.state not in USABLE_CONNECTIONS:
            message = "Connect to a context before selecting a namespace."
            self.notice(message)
        elif not isinstance(self.host.screen, ModalScreen):
            if self.authorization is not None:
                self.authorization.begin_namespace_picker()
            if self.diagnostics is not None:
                self.diagnostics.begin_namespace_picker()
            self.select_resource("namespaces", restore=self._namespace_state)

    def display(
        self,
        resource: str,
        *,
        focus: bool = True,
        generic: ResourceSelection | None = None,
        selection: ResourceSelection | None = None,
    ) -> None:
        route = (
            ViewRoute.custom(generic)
            if generic is not None
            else ViewRoute.contexts()
            if resource == "contexts"
            else ViewRoute.pulse()
            if resource == "pulse"
            else ViewRoute.relationships()
            if resource == "relationships"
            else ViewRoute.authorization()
            if resource == "authorization"
            else ViewRoute.diagnostics()
            if resource == "diagnostics"
            else ViewRoute.namespaces()
            if resource == "namespaces"
            else ViewRoute.events(selection or ResourceSelection("events"))
            if resource == "events"
            else ViewRoute.pods()
            if resource == "pods"
            else ViewRoute.standard(RESOURCE_ALIASES[resource])
        )
        if selection is not None and generic is None and route.selection is not None:
            route = ViewRoute(route.kind, selection)
        if (
            route.kind is ViewKind.EVENTS
            and route.selection is not None
            and self.workspace.discovery is not None
        ):
            descriptor = self.workspace.discovery.resolve(
                route.selection.name, group=route.selection.group, version=route.selection.version
            )
            if not event_descriptor_supported(descriptor):
                route = ViewRoute(ViewKind.STANDARD, route.selection)
        self.views.select(route)
        if self.authorization is not None:
            self.authorization.departing(route.kind)
        if self.diagnostics is not None:
            self.diagnostics.departing(route.kind)
        self.views.drilldown = None
        self.views.expected_uid = None
        self.views.curated = None
        self.views.event_options = EventOptions()
        self._column_notice = None
        namespaces = route.kind is ViewKind.NAMESPACES
        self.host.query_one("#all-namespaces").display = namespaces
        self.header.shortcuts = (
            (("Enter", "Evidence"), ("o", "Open object"), ("/", "Filter"), ("Esc", "Previous"))
            if resource == "diagnostics"
            else (
                ("Enter", "Follow evidence"),
                ("o", "Open object"),
                ("/", "Filter"),
                ("Esc", "Previous"),
            )
            if resource == "authorization"
            else (("Enter", "Expand"), ("o", "Open"), ("/", "Filter"), ("Esc", "Previous"))
            if resource == "relationships"
            else (
                ("Enter", "Details/members"),
                ("w", "Warnings"),
                ("t", "Group/raw"),
                ("/", "Filter"),
                ("Esc", "Previous"),
            )
            if route.kind is ViewKind.EVENTS
            else (
                ("Enter", "Drill down"),
                ("M", "Metric history"),
                (":", "Command"),
                ("/", "Filter"),
                ("Esc", "Previous"),
            )
            if resource in {"pulse", "relationships", "authorization", "diagnostics"}
            else CTX_SHORTCUTS
            if resource == "contexts"
            else NS_SHORTCUTS
            if namespaces
            else RESOURCE_SHORTCUTS
            if generic is not None
            else POD_SHORTCUTS
            if resource == "pods"
            else SERVICE_SHORTCUTS
            if resource == "services"
            else workload_shortcuts(resource, self.policy.read_only)
        )
        self.header.binding_profile = (
            "table"
            if resource in {"pulse", "relationships", "authorization", "diagnostics"}
            else "events"
            if route.kind is ViewKind.EVENTS
            else "contexts"
            if resource == "contexts"
            else "namespaces"
            if namespaces
            else "resources"
        )
        self.header.render_shortcuts()
        if focus and len(self.host.screen_stack) == 1:
            self.host.set_focus(self.views.table)
        self.changed()

    def select_resource(
        self,
        resource: str,
        *,
        restore: NavigationState | None = None,
        scope: NamespaceChoice | None = None,
        generic: ResourceSelection | None = None,
    ) -> None:
        self._pending_relationships = None
        current = self.capture()
        if self.resource_name == "contexts":
            self._context_state = current
        if (
            resource == self.resource_name
            and generic == self.generic_selection
            and scope is None
            and self.views.drilldown is None
            and self.views.expected_uid is None
            and self.views.curated is None
            and restore is None
        ):
            self.host.set_focus(self.views.table)
            return
        try:
            selection = (
                ResourceSelection(
                    restore.curated.resource.name,
                    restore.curated.resource.group,
                    restore.curated.resource.version,
                    generic is not None,
                    restore.curated.query,
                )
                if restore is not None and restore.curated is not None
                else ResourceSelection(
                    restore.drilldown.resource.name,
                    restore.drilldown.resource.group,
                    restore.drilldown.resource.version,
                )
                if restore is not None and restore.drilldown is not None and generic is None
                else generic or resource_selection(resource)
            )
            if restore is not None:
                selection = replace(selection, query=restore.server_query)
                if generic is not None:
                    generic = selection
            self.workspace.select_resource(selection)
            if scope is not None:
                self.workspace.select_namespace(scope.namespace)
        except AppError as error:
            self.status(str(error))
            return
        if current is not None:
            self.history.visit(current)
            if current.resource == "namespaces":
                self._namespace_state = current
                self._namespace_route = True
            elif resource == "namespaces":
                self._namespace_parent = current
        self.display(resource, generic=generic, selection=selection)
        self.views.drilldown = restore.drilldown if restore is not None else None
        self.views.expected_uid = restore.expected_uid if restore is not None else None
        self.views.curated = restore.curated if restore is not None else None
        self.views.event_options = restore.events if restore is not None else EventOptions()
        self.clear_rows()
        self.filter_input.value = restore.query if restore is not None else ""
        if restore is not None:
            self.set_errors(restore.errors)
            self._restore_state = self.workspace.store.observation.revision, restore
        self.views.request()

    def namespace_selected(self, value: str | None) -> None:
        if value is not None:
            try:
                choice = NamespaceChoice(None if value == "*" else value)
                current = self.capture()
                if self.diagnostics is not None and self.diagnostics.namespace_selected(
                    choice, current
                ):
                    return
                if self.authorization is not None and self.authorization.namespace_selected(
                    choice, current
                ):
                    return
                was_namespace_view = self.resource_name == "namespaces"
                was_context_view = self.resource_name == "contexts"
                if was_context_view:
                    self._context_state = current
                generic = (
                    self.generic_selection
                    if self.views.tables.custom.display
                    else self._namespace_parent.generic
                    if was_namespace_view and self._namespace_parent is not None
                    else None
                )
                parent = self._namespace_parent if was_namespace_view else current
                if parent is not None and parent.relationships is not None:
                    bookmark = parent.relationships
                    descriptor = bookmark.root.resource
                    if current is not None:
                        self.history.visit(current)
                    if was_namespace_view:
                        self._namespace_state = current
                    if (
                        descriptor is not None
                        and descriptor.namespaced
                        and choice.namespace is not None
                        and choice.namespace != bookmark.root.namespace
                    ):
                        self.open_resource(descriptor, choice.namespace)
                    else:
                        self.restore(replace(parent, namespace=choice.namespace))
                    return
                if parent is not None and parent.resource == "pulse":
                    self.workspace.select_pulse()
                    self.workspace.select_namespace(choice.namespace)
                    if current is not None:
                        self.history.visit(current)
                    if was_namespace_view:
                        self._namespace_state = current
                    self.display("pulse", focus=not isinstance(self.host.focused, Input))
                    self.clear_rows()
                    self.filter_input.value = ""
                    self.views.drilldown = None
                    self.views.request()
                    self.header.update_identity()
                    return
                pod_query = (
                    parent.server_query
                    if parent is not None and parent.resource == "pods"
                    else ResourceQuery()
                )
                self.workspace.select_resource(generic or ResourceSelection(query=pod_query))
                self.workspace.select_namespace(choice.namespace)
                if was_namespace_view:
                    self._namespace_state = current
                    self._namespace_route = True
                if current is not None:
                    self.history.visit(current)
                self.display(
                    (generic.name + "." + (generic.group or "core"))
                    if generic is not None
                    else "pods",
                    generic=generic,
                    focus=was_namespace_view
                    or was_context_view
                    or not isinstance(self.host.focused, Input),
                )
                self.clear_rows()
                if was_namespace_view or was_context_view:
                    self.filter_input.value = ""
                self.header.update_identity()
                self.status(self.workspace.store.observation.message)
            except AppError as error:
                self.status(str(error))

    def retry(self) -> None:
        context = (
            self.workspace.store.observation.context
            or self.sessions.request.context
            or self.sessions.catalog.current
        )
        if context is not None:
            self.connect(context)
        else:
            self.contexts()

    def generic(self, command: GenericResourceCommand) -> None:
        try:
            if command.name == "events" and command.group is None and command.version is None:
                self.events(command.scope)
                return
            discovery = self.workspace.discovery
            if discovery is None:
                raise AppError("Wait for the current resource catalogue or use :refresh.")
            resource = discovery.resolve(command.name, group=command.group, version=command.version)
            if command.scope is not None and not resource.namespaced:
                raise AppError("This resource is cluster-scoped; omit the namespace argument.")
            known = RESOURCE_ALIASES.get(resource.name)
            if resource.name == "events" and resource.group in {"", "events.k8s.io"}:
                self.open_resource(
                    resource,
                    (None if command.scope == "*" else command.scope)
                    if command.scope is not None
                    else self.workspace.store.observation.connection.namespace,
                )
                return
            if known is not None and known.group == resource.group and known.curated:
                self.open_resource(
                    resource,
                    (None if command.scope == "*" else command.scope)
                    if command.scope is not None
                    else self.workspace.store.observation.connection.namespace,
                )
                return
            selection = ResourceSelection(
                resource.name, resource.group, command.version, server_columns=True
            )
            scope = (
                NamespaceChoice(None if command.scope == "*" else command.scope)
                if command.scope is not None
                else None
            )
            self.select_resource(
                resource.name + "." + (resource.group or "core"),
                scope=scope,
                generic=selection,
            )
            if self.generic_selection == selection:
                view = self.workspace.store.observation
                layout = self.views.custom.layout_for(view.context, resource)
                self.views.custom.configure(layout, view.revision)
        except AppError as error:
            self._column_notice = str(error)
            self.status(self._column_notice)

    def refresh_discovery(self) -> None:
        if self.diagnostics is not None and self.diagnostics.active:
            self.diagnostics.refresh()
            return
        if self.authorization is not None and self.authorization.active:
            self.authorization.refresh()
            return
        state = self.capture()
        try:
            self.workspace.refresh_discovery()
        except AppError as error:
            self.status(str(error))
            return
        self.clear_rows()
        if state is not None:
            self._restore_state = self.workspace.store.observation.revision, state
        self._column_notice = None
        self.command_input.refresh_choices()
        self.views.request()

    def columns(self, argument: str = "") -> None:
        layout = (
            self.views.tables.custom.resource_layout if self.views.tables.custom.display else None
        )
        if layout is None:
            self.status("Select a discovered resource before configuring server columns.")
            return
        try:
            if not argument:
                available = ", ".join(
                    f"c{i + 1}={safe_text(column.name).plain}"
                    for i, column in enumerate(layout.headers)
                    if column.format != "name" and column.name.casefold() != "age"
                )
                self._column_notice = (
                    "Columns: "
                    + (available or "metadata only")
                    + " · :columns default / none / cN ..."
                )
            else:
                configured = (
                    CustomLayout.build(layout.resource, layout.headers)
                    if argument == "default"
                    else layout.configure(() if argument == "none" else tuple(argument.split()))
                )
                self.views.custom.configure(configured, self.workspace.store.observation.revision)
                self.view_preferences.columns_changed(configured)
                view = self.workspace.store.observation
                self.views.remember_layout(view.context, configured)
                self._column_notice = "Custom columns updated for this session."
                self.views.request()
        except AppError as error:
            self._column_notice = str(error)
        self.status(self._column_notice or self.workspace.store.observation.message)

    def namespace_choices(self) -> tuple[str, ...]:
        connection = self.workspace.store.observation.connection
        if connection.state not in USABLE_CONNECTIONS:
            return ()
        current = (connection.namespace,) if connection.namespace is not None else ()
        favorites = self.favorites(connection.identity.context if connection.identity else "")
        return ("*", *sorted(set(connection.namespaces) | set(current) | set(favorites)))

    def server(self, text: str) -> None:
        """Replace the owned server query only on an explicit command."""
        if self.resource_name in {
            "contexts",
            "pulse",
            "relationships",
            "authorization",
            "diagnostics",
        }:
            self.notice(
                "Server selectors apply to Kubernetes resources; open a resource view first."
            )
            return
        current = self.workspace.selection.query
        if not text:
            self.notice(
                f"Server query · label: {current.label_selector or 'none'}"
                f" · field: {current.field_selector or 'none'}"
                f" · {'compact metadata' if current.compact else 'full objects'}"
                " · :server label/field EXPR · clear · compact · full"
            )
            return
        previous = self.capture()
        try:
            query = query_command(current, text)
            if query == current:
                self.server("")
                return
            self.workspace.set_query(query)
        except AppError as error:
            self.notice(str(error))
            return
        if previous is not None:
            self.history.visit(previous)
        generic = self.generic_selection
        curated, event_options = self.views.curated, self.views.event_options
        self.display(
            self.resource_name,
            generic=replace(generic, query=query) if generic is not None else None,
            selection=self.workspace.selection,
        )
        self.views.curated = replace(curated, query=query) if curated is not None else None
        self.views.event_options = event_options
        self.clear_rows()
        self.views.request()

    def capture(self) -> NavigationState | None:
        view = self.workspace.store.observation
        if self.resource_name != "contexts" and (
            view.context is None or view.connection.state not in USABLE_CONNECTIONS
        ):
            return None
        viewport = self.views.table.capture_viewport()
        return NavigationState(
            view.context or "",
            view.connection.namespace,
            self.filter_input.value,
            self.views.table.sort_column
            if isinstance(
                self.views.table,
                (StandardTable, NamespaceTable, ClusterDiagnosticsTable, EventsTable),
            )
            else self.views.tables.pods.sort_column,
            self.views.table.descending
            if isinstance(
                self.views.table,
                (StandardTable, NamespaceTable, ClusterDiagnosticsTable, EventsTable),
            )
            else self.views.tables.pods.descending,
            viewport.selected,
            viewport.index,
            viewport.x,
            viewport.y,
            viewport.top,
            self.resource_name,
            self.generic_selection,
            self.views.tables.custom.resource_layout.headers
            if self.views.tables.custom.display
            and self.views.tables.custom.resource_layout is not None
            else (),
            self.workspace.selection.query,
            self.views.drilldown,
            viewport.top_offset,
            self.errors(),
            RelationshipBookmark(
                RelationshipRef(
                    request.scope.resource.api_version,
                    request.scope.resource.kind,
                    request.scope.root.namespace,
                    request.scope.root.name,
                    request.scope.root.uid,
                    request.scope.resource,
                ),
                request.scope.mode,
                request.expanded,
            )
            if self.resource_name == "relationships"
            and (request := self.workspace.relationship_request) is not None
            else None,
            self.views.expected_uid,
            self.workspace.authorization_request.intent
            if self.resource_name == "authorization"
            and self.workspace.authorization_request is not None
            else None,
            DiagnosticBookmark(diagnostic.request.scope.namespace, diagnostic.request.scope.root)
            if self.resource_name == "diagnostics" and (diagnostic := view.diagnostics) is not None
            else None,
            self.views.curated,
            self.views.event_options,
        )

    def remember(self) -> None:
        current = self.capture()
        if current is not None:
            self.history.visit(current)

    def move(self, *, forward: bool = False) -> None:
        current = self.capture()
        view = self.workspace.store.observation
        if current is None and view.context is not None:
            current = NavigationState(view.context, view.connection.namespace)
        state = self.history.move(current, forward=forward) if current is not None else None
        if state is None:
            self.status("No next view in history." if forward else "No previous view in history.")
            return
        self.restore(state)

    def restore(self, state: NavigationState) -> None:
        if state.diagnostics is not None and self.diagnostics is not None:
            self.diagnostics.restore(state)
            return
        if state.authorization is not None and self.authorization is not None:
            self.authorization.restore(state)
            return
        if state.resource == "relationships" and state.relationships is not None:
            current = self.workspace.store.observation
            identity, discovery = current.connection.identity, self.workspace.discovery
            if (
                state.context != current.context
                or current.connection.state not in USABLE_CONNECTIONS
                or identity is None
                or discovery is None
            ):
                self._pending_relationships = state
                self.workspace.prepare_resource(ResourceSelection("pods"))
                self.display("pods")
                self.connect(state.context, scope=NamespaceChoice(state.namespace), remember=False)
                return
            root = resolve_reference(discovery, state.relationships.root)
            if root.resource is None or root.uid is None:
                self.notice(
                    "The relationship root API is unavailable in the current discovery catalogue."
                )
                return
            if current.connection.namespace != state.namespace:
                self.workspace.select_namespace(state.namespace)
            self.relationships(
                ResourceTarget(
                    identity,
                    root.resource.group,
                    root.resource.name,
                    root.namespace,
                    root.name,
                    root.uid,
                ),
                root.resource,
                state.relationships.mode,
                restore=state,
                remember=False,
            )
            return
        if state.resource == "contexts":
            if self.resource_name != "contexts":
                self._context_parent = self.capture()
            self.display("contexts")
            self.filter_input.value = state.query
            self.set_errors(state.errors)
            self._restore_state = self.workspace.store.observation.revision, state
            self.views.request()
            return
        if state.resource == "pulse":
            current = self.workspace.store.observation
            self.pulse(restore=state, remember=False)
            if (
                state.context != current.context
                or current.connection.state not in USABLE_CONNECTIONS
            ):
                self.connect(state.context, scope=NamespaceChoice(state.namespace), remember=False)
                self._restore_state = self.workspace.store.observation.revision, state
            else:
                self.workspace.select_namespace(state.namespace)
                self._restore_state = self.workspace.store.observation.revision, state
            return
        scope = NamespaceChoice(state.namespace)
        selection = replace(
            state.generic
            or (
                ResourceSelection(
                    state.curated.resource.name,
                    state.curated.resource.group,
                    state.curated.resource.version,
                )
                if state.curated is not None
                else ResourceSelection(
                    state.drilldown.resource.name,
                    state.drilldown.resource.group,
                    state.drilldown.resource.version,
                )
                if state.drilldown is not None
                else resource_selection(state.resource)
            ),
            query=state.server_query,
        )
        generic = selection if state.generic is not None else None
        current = self.workspace.store.observation
        if state.context == current.context and current.connection.state in USABLE_CONNECTIONS:
            self.workspace.select_resource(selection)
            self.workspace.select_namespace(state.namespace)
            self.display(state.resource, generic=generic, selection=selection)
            self.clear_rows()
            self.header.update_identity()
        else:
            self.workspace.prepare_resource(selection)
            self.display(state.resource, generic=generic, selection=selection)
            self.connect(state.context, scope=scope, remember=False)
        self.filter_input.value = state.query
        self.set_errors(state.errors)
        self.views.drilldown = state.drilldown
        self.views.expected_uid = state.expected_uid
        self.views.curated = state.curated
        self.views.event_options = state.events
        self._restore_state = self.workspace.store.observation.revision, state

    def history_back(self) -> None:
        self.move()

    def history_forward(self) -> None:
        self.move(forward=True)

    def restore_pending(self, state: NavigationState) -> None:
        """Restore common history geometry after the matching native data applies."""
        self._restore_state = self.workspace.store.observation.revision, state

    def _relationship_restore_ready(self, view: ViewObservation) -> bool:
        snapshot, table = view.relationships, self.views.tables.relationships
        if snapshot is None or not snapshot.rows or table.request != snapshot.request:
            return False
        # Progressive publications can replace rows before a scheduled scroll restore.
        # Wait for the settled collection; missing/replaced/filtered keys then fall back.
        return not self.workspace.relationship_collecting

    def after_render(self, view: ViewObservation) -> None:
        if (
            self._restore_state is not None
            and self._restore_state[0] == view.revision
            and (
                view.snapshot is not None
                or self.views.route.kind is ViewKind.CONTEXTS
                or (self.views.route.kind is ViewKind.PULSE and view.pulse is not None)
                or (
                    self.views.route.kind is ViewKind.DIAGNOSTICS
                    and self.diagnostics is not None
                    and self.diagnostics.restore_ready(view)
                )
                or (
                    self.views.route.kind is ViewKind.AUTHORIZATION
                    and self.authorization is not None
                    and self.authorization.restore_ready(view)
                )
                or (
                    self.views.route.kind is ViewKind.RELATIONSHIPS
                    and self._relationship_restore_ready(view)
                )
            )
        ):
            state = self._restore_state[1]
            if isinstance(self.views.table, (PodTable, StandardTable, NamespaceTable, EventsTable)):
                if self.resource_name == "pods":
                    self.views.tables.pods.restore_sort(PodColumn(state.column), state.descending)
                elif (
                    isinstance(self.views.table, (StandardTable, NamespaceTable, EventsTable))
                    and not self.views.tables.custom.display
                ):
                    self.views.table.restore_sort(state.column, state.descending)
            if self.views.tables.custom.display:
                compatible = (
                    self.views.tables.custom.resource_layout is not None
                    and self.views.tables.custom.resource_layout.headers == state.headers
                )
                self.views.tables.custom.restore_sort(
                    state.column if compatible else "name",
                    state.descending if compatible else False,
                )
            self.views.table.restore_viewport(
                Viewport(state.selected, state.index, state.x, state.y, state.top, state.top_offset)
            )
            self._restore_state = None
        if self._column_notice is not None:
            self.status(self._column_notice)

    def trail(self) -> NavigationTrail:
        trail = (
            ("events", "group members")
            if self.views.route.kind is ViewKind.EVENTS
            and self.views.event_options.members is not None
            else (self.history.previous[-1].resource, self.resource_name)
            if self.views.curated is not None and self.history.previous
            else ("pulse", self.resource_name)
            if self.views.drilldown is not None
            else ("namespaces", "pods")
            if self._namespace_route and self.resource_name == "pods"
            else (self.resource_name,)
        )
        destination = (
            "Leave input"
            if isinstance(self.host.focused, Input)
            else "Clear filter"
            if self.filter_input.value
            else "Namespaces"
            if self._namespace_route and self.resource_name == "pods"
            else (
                self._namespace_parent.resource.title()
                if self._namespace_parent is not None
                else "Pods"
            )
            if self.resource_name == "namespaces"
            else self._context_parent.resource.title()
            if self.resource_name == "contexts" and self._context_parent is not None
            else "Pods"
            if self.resource_name == "contexts"
            else "Pulse"
            if self.views.drilldown is not None
            else "Previous view"
            if self.resource_name in {"pulse", "relationships", "authorization", "diagnostics"}
            or self.views.expected_uid is not None
            or self.views.curated is not None
            or self.views.route.kind is ViewKind.EVENTS
            else f"Stay in {self.resource_name}"
        )
        return NavigationTrail(trail, destination)

    def back(self) -> None:
        if (
            self.resource_name in {"pulse", "relationships", "authorization", "diagnostics"}
            or self.views.drilldown is not None
            or self.views.expected_uid is not None
            or self.views.curated is not None
            or self.views.route.kind is ViewKind.EVENTS
        ):
            self.history_back()
        elif self.resource_name == "contexts":
            self._context_state = self.capture()
            if self._context_parent is not None:
                self.restore(self._context_parent)
            else:
                selection = self.workspace.selection
                self.display(
                    selection.name + "." + (selection.group or "core")
                    if selection.server_columns
                    else selection.name,
                    generic=selection if selection.server_columns else None,
                )
                self.views.request()
        elif (
            self.resource_name == "pods" or self.views.tables.custom.display
        ) and self._namespace_route:
            self.namespaces()
        elif self.resource_name == "namespaces":
            self._namespace_route = False
            if self._namespace_parent is not None:
                self.restore(self._namespace_parent)
            else:
                self.select_resource("pods")
        else:
            self.filter_input.value = ""
            self.status(self.workspace.store.observation.message)
