"""Own context/resource history and restoration through explicit workspace ports."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Input

from kuberich.adapters.credentials import CredentialLogin
from kuberich.domain.custom import CustomLayout
from kuberich.domain.navigation import NamespaceChoice, NavigationHistory, NavigationState, Viewport
from kuberich.domain.pods import PodColumn
from kuberich.domain.registry import RESOURCE_ALIASES, resource_selection
from kuberich.domain.resource_queries import ResourceQuery, query_command
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceSelection, ViewObservation
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
from kuberich.ui.commands import CommandInput
from kuberich.ui.contexts import ContextTable
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.root_views import RootViews
from kuberich.ui.standard import StandardTable
from kuberich.ui.views import ViewPreferences


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
        self._restore_state: tuple[int, NavigationState] | None = None
        self._context_parent: NavigationState | None = None
        self._context_state: NavigationState | None = None
        self._namespace_parent: NavigationState | None = None
        self._namespace_state: NavigationState | None = None
        self._namespace_route = False
        self._column_notice: str | None = None
        self._pending_generic: GenericResourceCommand | None = None

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

    def command_error(self, message: str) -> None:
        if self.views.route.kind is ViewKind.CUSTOM:
            self._column_notice = message
        self.status(message)

    def resolve_pending(self) -> None:
        if self._pending_generic is not None and self.workspace.discovery is not None:
            command, self._pending_generic = self._pending_generic, None
            self.generic(command)

    def initialize(
        self, initial: ResolvedCommand, apply: Callable[[ResolvedCommand], None]
    ) -> None:
        context = self.sessions.request.context or self.sessions.catalog.current
        if initial is Command.NAMESPACES:
            self.workspace.selection = ResourceSelection("namespaces")
            self.display("namespaces")
        scope = None
        if isinstance(initial, ScopedCommand):
            if initial.command is Command.CONTEXTS:
                context = initial.argument
            else:
                scope = NamespaceChoice(None if initial.argument == "*" else initial.argument)
        if isinstance(initial, ResourceCommand):
            self.workspace.selection = initial.definition.selection
            self.display(initial.definition.name)
            if initial.scope is not None:
                scope = NamespaceChoice(None if initial.scope == "*" else initial.scope)
        if isinstance(initial, GenericResourceCommand):
            self._pending_generic = initial
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
            self.remember()
        if context != self.workspace.store.observation.context:
            self._namespace_parent = self._namespace_state = None
            self._namespace_route = False
            self.views.reset_context()
        self.apply_theme(context)
        self.workspace.connect(context, scope=scope, authenticate=authenticate)
        self.clear_rows()
        self.header.update_identity()
        self.changed()
        self.status("Connecting · F2 contexts · F4 retry · Ctrl+Q quit")

    def contexts(self) -> None:
        if not self.sessions.catalog.names:
            self.status("No contexts found. Configure KUBECONFIG or use --kubeconfig.")
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
            self._context_state = (
                self.capture() if self.resource_name == "contexts" else self._context_state
            )
            self.remember()
            self.workspace.selection = ResourceSelection("pods")
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

    def namespaces(self) -> None:
        self.disable_favorites()
        observation = self.workspace.store.observation.connection
        if observation.state not in USABLE_CONNECTIONS:
            message = "Connect to a context before selecting a namespace."
            self.notice(message)
        elif not isinstance(self.host.screen, ModalScreen):
            self.select_resource("namespaces", restore=self._namespace_state)

    def display(
        self, resource: str, *, focus: bool = True, generic: ResourceSelection | None = None
    ) -> None:
        route = (
            ViewRoute.custom(generic)
            if generic is not None
            else ViewRoute.contexts()
            if resource == "contexts"
            else ViewRoute.namespaces()
            if resource == "namespaces"
            else ViewRoute.pods()
            if resource == "pods"
            else ViewRoute.standard(RESOURCE_ALIASES[resource])
        )
        self.views.select(route)
        self._column_notice = None
        namespaces = route.kind is ViewKind.NAMESPACES
        self.host.query_one("#all-namespaces").display = namespaces
        self.header.shortcuts = (
            CTX_SHORTCUTS
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
            "contexts" if resource == "contexts" else "namespaces" if namespaces else "resources"
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
        current = self.capture()
        if self.resource_name == "contexts":
            self._context_state = current
        if resource == self.resource_name and generic == self.generic_selection and scope is None:
            self.host.set_focus(self.views.table)
            return
        try:
            selection = generic or resource_selection(resource)
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
        self.display(resource, generic=generic)
        self.clear_rows()
        self.filter_input.value = restore.query if restore is not None else ""
        if restore is not None:
            self._restore_state = self.workspace.store.observation.revision, restore
        self.views.request()

    def namespace_selected(self, value: str | None) -> None:
        if value is not None:
            try:
                choice = NamespaceChoice(None if value == "*" else value)
                current = self.capture()
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
            discovery = self.workspace.discovery
            if discovery is None:
                raise AppError("Wait for the current resource catalogue or use :refresh.")
            resource = discovery.resolve(command.name, group=command.group, version=command.version)
            if command.scope is not None and not resource.namespaced:
                raise AppError("This resource is cluster-scoped; omit the namespace argument.")
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
        if self.resource_name == "contexts":
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
        self.display(
            self.resource_name,
            generic=replace(generic, query=query) if generic is not None else None,
        )
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
            if isinstance(self.views.table, (StandardTable, NamespaceTable))
            else self.views.tables.pods.sort_column,
            self.views.table.descending
            if isinstance(self.views.table, (StandardTable, NamespaceTable))
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
        if state.resource == "contexts":
            if self.resource_name != "contexts":
                self._context_parent = self.capture()
            self.display("contexts")
            self.filter_input.value = state.query
            self._restore_state = self.workspace.store.observation.revision, state
            self.views.request()
            return
        scope = NamespaceChoice(state.namespace)
        selection = replace(
            state.generic or resource_selection(state.resource), query=state.server_query
        )
        generic = selection if state.generic is not None else None
        current = self.workspace.store.observation
        if state.context == current.context and current.connection.state in USABLE_CONNECTIONS:
            self.workspace.select_resource(selection)
            self.workspace.select_namespace(state.namespace)
            self.display(state.resource, generic=generic)
            self.clear_rows()
            self.header.update_identity()
        else:
            self.workspace.selection = selection
            self.display(state.resource, generic=generic)
            self.connect(state.context, scope=scope, remember=False)
        self.filter_input.value = state.query
        self._restore_state = self.workspace.store.observation.revision, state

    def history_back(self) -> None:
        self.move()

    def history_forward(self) -> None:
        self.move(forward=True)

    def after_render(self, view: ViewObservation) -> None:
        if (
            self._restore_state is not None
            and self._restore_state[0] == view.revision
            and (view.snapshot is not None or self.views.route.kind is ViewKind.CONTEXTS)
        ):
            state = self._restore_state[1]
            if isinstance(self.views.table, (PodTable, StandardTable, NamespaceTable)):
                if self.resource_name == "pods":
                    self.views.tables.pods.restore_sort(PodColumn(state.column), state.descending)
                elif (
                    isinstance(self.views.table, (StandardTable, NamespaceTable))
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
                Viewport(state.selected, state.index, state.x, state.y, state.top)
            )
            self._restore_state = None
        if self._column_notice is not None:
            self.status(self._column_notice)

    def trail(self) -> NavigationTrail:
        trail = (
            ("namespaces", "pods")
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
            else f"Stay in {self.resource_name}"
        )
        return NavigationTrail(trail, destination)

    def back(self) -> None:
        if self.resource_name == "contexts":
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
