"""A responsive workspace subscribed to its owned Kubernetes resource view."""

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import suppress
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import DescendantFocus, Event, Key, Paste, Resize
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static

from kuberich.adapters.credentials import CredentialLogin, ExecToken, auth_problem
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.terminal import current_terminal_size
from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import (
    DEFAULT_CONNECTION,
    ConnectionRequest,
)
from kuberich.domain.credential_helpers import helper_start_failure
from kuberich.domain.custom import CustomLayout
from kuberich.domain.logs import log_containers
from kuberich.domain.navigation import (
    MAX_HISTORY,
    ContextRow,
    NamespaceChoice,
    NavigationHistory,
    NavigationState,
)
from kuberich.domain.operations import MAX_BATCH, ResourceAction
from kuberich.domain.pods import PodColumn
from kuberich.domain.port_forwards import suggested_port
from kuberich.domain.processes import ProcessStatus
from kuberich.domain.registry import RESOURCE_ALIASES, resource_selection
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceSelection, ViewObservation, ViewStatus
from kuberich.domain.workloads import WorkloadAction, applicable
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.security.arguments import validate_argument
from kuberich.security.presentation import safe_text
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.attach import AttachService
from kuberich.services.commands import (
    Command,
    CommandService,
    GenericResourceCommand,
    ResolvedCommand,
    ResourceCommand,
    ScopedCommand,
    suggestions,
)
from kuberich.services.editing import EditingService
from kuberich.services.filtering import apply_filter
from kuberich.services.inspection import InspectionService
from kuberich.services.logs import LogStream
from kuberich.services.mutations import MutationManager, MutationService
from kuberich.services.operations import ResourceOperationService
from kuberich.services.pods import (
    CustomProjection,
    NamespaceProjection,
    PodProjection,
    StandardProjection,
)
from kuberich.services.port_forwards import ForwardManager, ForwardService
from kuberich.services.processes import ProcessRunner, _finish_owned
from kuberich.services.sessions import SessionService
from kuberich.services.shell import ShellService
from kuberich.services.transfers import TransferService
from kuberich.services.workloads import WorkloadService
from kuberich.services.workspace import ViewSubscription, WorkspaceService
from kuberich.ui.chrome import (
    CTX_SHORTCUTS,
    K9S_THEME,
    NS_SHORTCUTS,
    POD_SHORTCUTS,
    RESOURCE_SHORTCUTS,
    SERVICE_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
    workload_shortcuts,
)
from kuberich.ui.commands import CommandInput, NavigationInput
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.contexts import ContextTable
from kuberich.ui.custom import CustomTable
from kuberich.ui.editing import EditingScreen
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.inspection import InspectionScreen, Page
from kuberich.ui.logs import LogScreen
from kuberich.ui.mutations import AnnotationScreen, MutationHistoryScreen
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.operations import ResourceOperationScreen
from kuberich.ui.pods import PodTable, Viewport
from kuberich.ui.port_forwards import ForwardPrompt, ForwardScreen
from kuberich.ui.presentation import DEFAULT_PRESENTATION, Presentation
from kuberich.ui.scopes import ConnectionScreen
from kuberich.ui.shutdown import TerminalSignals
from kuberich.ui.standard import StandardTable
from kuberich.ui.terminal import ShellScreen
from kuberich.ui.transfers import TransferScreen
from kuberich.ui.workloads import WorkloadScreen

DISCONNECTED_STATUS = "Disconnected · No resource data"


class HelpScreen(ModalScreen[None]):
    """Scrollable help keeps its close control accessible in small terminals."""

    AUTO_FOCUS = "#help-scroll"

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Keyboard help", id="help-title", markup=False)
            with VerticalScroll(id="help-scroll"):
                yield Static(
                    Text(
                        "/                 Focus filter\n"
                        ":                 Focus command\n"
                        "? or F1           Open help\n"
                        "c / F2            Contexts (:ctx)\n"
                        "n / F3            Namespaces (:ns)\n"
                        "r / F4            Retry connection (:retry)\n"
                        ":login            Explicit credential helper login and reconnect\n"
                        "i / F5            Connection status (:status)\n"
                        "Letter shortcuts work outside text inputs.\n"
                        "PageUp / PageDown Scroll help\n"
                        "Tab in command    Accept selected suggestion\n"
                        "Up / Down + Enter Select and submit suggestion\n"
                        "Tab / Shift+Tab   Move focus when no suggestion\n"
                        "Alt+Left / Right  Navigation back / forward\n"
                        "Escape            Back / leave input\n"
                        "Escape in table   Clear active filter\n"
                        "q / Ctrl+Q        Quit (q outside inputs)\n"
                        "Ctrl+C            Quit\n\n"
                        "Commands: po/pod/pods [NS or *], ctx [NAME], ns [NAME or *], "
                        "status, retry, login, back, forward, shell/exec, pf/portforwards, "
                        "portforward, annotate, edit (Shift+E), scale, restart, rollback, rollout, "
                        "delete, deletebatch, trigger, suspend, resume, writes, help, quit.\n"
                        "Resources: deploy, rs, sts, ds, job, cj, svc, ep, ing, cm, sec, "
                        "no, pvc, pv, sc. Namespaced resources accept [NS or *].\n"
                        "Discovered: :resource NAME[.GROUP][/VERSION] [NS or *]. "
                        "Unique discovered aliases work directly; ambiguous names require a group.\n"
                        ":refresh renews discovery on the current client. "
                        ":columns shows server keys; :columns cN ... / default / none.\n"
                        "Generic resources are read-only; columns are session-local.\n"
                        "Filter: plain case-insensitive text; re:PATTERN for regex. "
                        "Searches namespace, name, readiness, status and restarts. "
                        "Invalid or timed-out regex shows all pods and an error.\n\n"
                        "Context sessions and live pod synchronization are available. "
                        "Pod rows, container logs and embedded shells are available.\n"
                        "l                 Selected pod logs (regular / init)\n"
                        "Logs: g/G first/last, j/k, / search, p pause, f follow, ? controls.\n"
                        "Enter             Pod containers → container logs\n"
                        "x / :shell        Choose a pod's container for its shell\n"
                        "Shift+F           Start pod/Service TCP port-forward\n"
                        ":pf               List owned forwards; s stops selected\n"
                        "Forwards survive view/namespace changes; context/retry/exit stops them.\n"
                        "Containers: s/x shell, a attach, u upload, d download, Enter/l logs, Esc pods.\n"
                        ":attach / :upload / :download choose a container first.\n"
                        "Shell: Ctrl+] return, Ctrl+C interrupt, Ctrl+Q quit.\n"
                        "d                 Resource details\n"
                        "y / e             YAML / related events\n"
                        "Viewer: m managedFields, / search, n/N matches, Ctrl+Y copy.\n"
                        "s                 Cycle sort column\n"
                        "Shift+S           Reverse sort\n"
                        "Header click      Sort / reverse column\n"
                        "Arrows / PageUp / PageDown navigate the table."
                    ),
                    id="help-content",
                )
            yield Button("Back", id="close-help", variant="primary", compact=True)

    @on(Button.Pressed, "#close-help")
    def close_help(self) -> None:
        self.dismiss()


class KubeRichApp(App[None]):
    """Keyboard and mouse workspace; startup does not load Kubernetes credentials."""

    CSS_PATH = Path(__file__).with_name("kuberich.tcss")
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = "#resources"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "focus_filter", "Filter", key_display="/", priority=True),
        Binding("colon", "focus_command", "Cmd", key_display=":", priority=True),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("f1", "show_help", "Help", show=False, priority=True),
        Binding("y", "inspect_yaml", "YAML"),
        Binding("d", "inspect_details", "Details"),
        Binding("e", "inspect_events", "Events"),
        Binding("E", "edit", "Edit", key_display="Shift+E"),
        Binding("l", "logs", "Logs"),
        Binding("x", "shell", "Shell"),
        Binding("F", "port_forward", "Port forward", key_display="Shift+F"),
        Binding("c", "contexts", "Contexts"),
        Binding("n", "namespaces", "Namespaces"),
        Binding("r", "retry", "Retry", show=False),
        Binding("i", "connection_details", "Status", show=False),
        Binding("alt+left", "history_back", "Previous view", show=False),
        Binding("alt+right", "history_forward", "Next view", show=False),
        Binding("f2", "contexts", "Contexts", show=False, priority=True),
        Binding("f3", "namespaces", "Namespaces", show=False, priority=True),
        Binding("f4", "retry", "Retry", show=False, priority=True),
        Binding("f5", "connection_details", "Status", show=False, priority=True),
        Binding("escape", "back", "Back", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        *,
        presentation: Presentation = DEFAULT_PRESENTATION,
        initial_command: ResolvedCommand = Command.EMPTY,
        catalog: KubeCatalog | None = None,
        connection: ConnectionRequest = DEFAULT_CONNECTION,
    ) -> None:
        super().__init__()
        self.title = "KubeRich"
        self.sub_title = "Local preview"
        self._diagnostic_logger = logger
        self._presentation = presentation
        self._initial_command = initial_command
        self.sessions = SessionService(
            catalog if catalog is not None else KubeCatalog(), connection
        )
        self._connection_task: asyncio.Task[None] | None = None
        self.workspace = WorkspaceService(self.sessions, on_error=self._handle_exception)
        self._view_task: asyncio.Task[None] | None = None
        self._render_task: asyncio.Task[None] | None = None
        self._render_ready = asyncio.Event()
        self._input_completion: asyncio.Future[None] | None = None
        self.history = NavigationHistory()
        self._restore_state: tuple[int, NavigationState] | None = None
        self.commands = CommandService(AccessPolicy(settings.read_only))
        self.processes = ProcessRunner(self.commands.policy)
        self.forwards = ForwardManager(self.processes, changed=self._forward_changed)
        self.mutations = MutationManager()
        self.sessions.before_close = self._close_client_operations
        self._terminal_signals = TerminalSignals(self)
        self._shell = settings.shell
        self._refresh_seconds = settings.refresh_seconds
        self._process_environment = dict(os.environ)
        self._process_directory = Path.cwd()
        self.register_theme(K9S_THEME)
        if settings.theme not in self.available_themes:
            raise AppError("Selected theme is unavailable; choose k9s or a built-in Textual theme.")
        self.theme = settings.theme
        self._mode = "Read-only" if settings.read_only else "Local preview"
        self.resources = PodTable()
        self.namespace_table = NamespaceTable()
        self.namespace_table.display = False
        self.context_table = ContextTable()
        self.context_table.display = False
        self.standard_table = StandardTable()
        self.standard_table.display = False
        self._standard_projection = StandardProjection(self.standard_table.definition)
        self.custom_table = CustomTable()
        self.custom_table.display = False
        self._custom_projection: CustomProjection | None = None
        self._custom_layouts: dict[tuple[str, str, str, str], CustomLayout] = {}
        self._generic_selection: ResourceSelection | None = None
        self._pending_generic: GenericResourceCommand | None = None
        self._column_notice: str | None = None
        self._resource_name = "pods"
        self._context_parent: NavigationState | None = None
        self._context_state: NavigationState | None = None
        self._namespace_parent: NavigationState | None = None
        self._namespace_state: NavigationState | None = None
        self._namespace_route = False
        self._selection_notice: tuple[ViewObservation, str] | None = None
        self._pod_projection = PodProjection()
        self._namespace_projection = NamespaceProjection()
        self.chrome = WorkspaceChrome(
            self._header_identity, f"KubeRich: {version('kuberich')} · {self._mode}", presentation
        )
        self.header = WorkspaceHeader(self.chrome, POD_SHORTCUTS)
        self.breadcrumbs = Breadcrumbs(
            ("pods",), "Clear filter", visible=not presentation.crumbsless
        )

        def focus_table() -> None:
            self.set_focus(self._active_table)

        self.filter_input = NavigationInput(
            focus_table, placeholder="Filter resources", id="filter"
        )
        self.command_input = CommandInput(self._suggestions, focus_table, self._submit_command)
        self.status = Static(DISCONNECTED_STATUS, id="status", markup=False)

    @property
    def _active_table(self) -> PodTable | NamespaceTable | ContextTable | StandardTable:
        if self._resource_name == "contexts":
            return self.context_table
        if self._resource_name == "namespaces":
            return self.namespace_table
        if self.custom_table.display:
            return self.custom_table
        return self.resources if self._resource_name == "pods" else self.standard_table

    def _header_identity(self) -> tuple[str, str, str, str, str]:
        view = self.workspace.store.observation
        entry = self.sessions.catalog.contexts.get(view.context or "")
        context = entry.data if entry is not None else {}
        cluster, user = context.get("cluster"), context.get("user")
        overrides = self.sessions.request.overrides
        cluster, user = overrides.cluster or cluster, overrides.user or user
        selected = self.sessions.client
        subject = (
            selected.context.user.data.get("as") if selected is not None else overrides.as_user
        )
        if isinstance(subject, str):
            user = f"{user or '—'} (as {subject})"
        return (
            view.context or "—",
            cluster if isinstance(cluster, str) else "—",
            user if isinstance(user, str) else "—",
            "—"
            if view.context is None or view.status is ViewStatus.CONNECTING
            else view.connection.namespace or "All",
            "Connecting"
            if view.status is ViewStatus.CONNECTING
            else view.connection.state.name.replace("_", " ").title(),
        )

    def _update_trail(self) -> None:
        if not self.screen_stack:
            return
        trail = (
            ("namespaces", "pods")
            if self._namespace_route and self._resource_name == "pods"
            else (self._resource_name,)
        )
        self.breadcrumbs.trail = trail
        destination = (
            "Leave input"
            if isinstance(self.focused, Input)
            else "Clear filter"
            if self.filter_input.value
            else "Namespaces"
            if self._namespace_route and self._resource_name == "pods"
            else (
                self._namespace_parent.resource.title()
                if self._namespace_parent is not None
                else "Pods"
            )
            if self._resource_name == "namespaces"
            else self._context_parent.resource.title()
            if self._resource_name == "contexts" and self._context_parent is not None
            else "Pods"
            if self._resource_name == "contexts"
            else f"Stay in {self._resource_name}"
        )
        self.breadcrumbs.destination = destination
        self.breadcrumbs.show_trail()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        self._update_trail()

    def _set_status(self, message: str) -> None:
        prefix = "Read-only · " if self.commands.policy.read_only else ""
        insecure = (
            "Insecure transport · " if self.workspace.store.observation.connection.insecure else ""
        )
        forwards = (
            f" · Forwards: {self.forwards.active_count}" if self.forwards.active_count else ""
        )
        self.status.update(safe_text(prefix + insecure + message + forwards))

    def _forward_changed(self) -> None:
        self._render_ready.set()

    async def on_event(self, event: Event) -> None:
        if (
            self.screen_stack
            and isinstance(self.screen, ShellScreen)
            and isinstance(event, (Key, Paste))
            and not event.is_forwarded
        ):
            if isinstance(event, Key):
                if event.key == "ctrl+q" and not (
                    self.screen.attach_mode and self.screen.detach_pending
                ):
                    self.exit()
                else:
                    self.screen.key(event)
            else:
                self.screen.paste(event)
            event.stop()
            event.prevent_default()
            return
        focused = (
            self.focused
            if isinstance(event, Key) and not event.is_forwarded and self.screen_stack
            else None
        )
        input_key = (
            isinstance(event, Key)
            and not event.is_forwarded
            and isinstance(focused, Input)
            and event.key not in {"ctrl+q", "ctrl+c"}
        )
        await super().on_event(event)
        if input_key and isinstance(focused, Input):
            # Forwarded printable keys use the widget's queue. Drain that key before
            # a subsequent editing binding or Enter reads the input's value.
            completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._input_completion = completion

            def settle() -> None:
                if not completion.done():
                    completion.set_result(None)

            try:
                if focused.call_later(settle):
                    await completion
            finally:
                self._input_completion = None

    def _workspace_status(self) -> str:
        return self.workspace.store.observation.message

    def compose(self) -> ComposeResult:
        yield self.header
        with WorkspaceBars():
            with Horizontal(id="filter-bar", classes="input-bar"):
                yield Static("/", classes="input-label", markup=False)
                yield self.filter_input
            with Horizontal(id="command-bar", classes="input-bar"):
                yield Static(":", classes="input-label", markup=False)
                yield self.command_input
        with WorkspaceFrame(id="resource-view"):
            yield Button("0  All namespaces", id="all-namespaces", compact=True)
            yield self.resources
            yield self.namespace_table
            yield self.context_table
            yield self.standard_table
            yield self.custom_table
            with Vertical(id="empty-state"):
                yield Static("No cluster connection", id="empty-title", markup=False)
                yield Static(
                    "Live resources are not connected in this preview.",
                    id="empty-description",
                    markup=False,
                )
                yield Static(
                    "Try / to focus the filter or :help for commands.",
                    id="empty-hint",
                    markup=False,
                )
        yield self.breadcrumbs
        yield self.status

    def on_mount(self) -> None:
        if not self.is_headless and not self.is_web:
            self._terminal_signals.install()
        self.query_one("#all-namespaces").display = False
        self.resources.setup()
        self.namespace_table.setup()
        self.context_table.setup()
        self.standard_table.setup()
        self.set_interval(self._refresh_seconds, self._refresh_tables)
        self.query_one("#resource-view", Vertical).border_title = "Resources · no connection"
        self.screen.set_class(self.size.width < 70, "compact")
        self.screen.set_class(self.size.height < 16, "short")
        self.set_focus(self.resources)
        self._set_status(DISCONNECTED_STATUS)
        if self._initial_command is not Command.QUIT:
            subscription = self.workspace.subscribe()
            self._view_task = asyncio.create_task(self._observe_view(subscription))
            self._render_task = asyncio.create_task(self._render_views())
            context = self.sessions.request.context or self.sessions.catalog.current
            initial = self._initial_command
            if initial is Command.NAMESPACES:
                self.workspace.selection = ResourceSelection("namespaces")
                self._display_resource("namespaces")
            scope = None
            if isinstance(initial, ScopedCommand):
                if initial.command is Command.CONTEXTS:
                    context = initial.argument
                else:
                    scope = NamespaceChoice(None if initial.argument == "*" else initial.argument)
            if isinstance(initial, ResourceCommand):
                self.workspace.selection = initial.definition.selection
                self._display_resource(initial.definition.name)
                if initial.scope is not None:
                    scope = NamespaceChoice(None if initial.scope == "*" else initial.scope)
            if isinstance(initial, GenericResourceCommand):
                self._pending_generic = initial
            if context is not None:
                self._start_connection(context, scope=scope)
            if (
                not isinstance(initial, (ScopedCommand, ResourceCommand, GenericResourceCommand))
                and initial is not Command.NAMESPACES
            ):
                self._apply_command(initial)
        else:
            self.exit()

    def _start_connection(
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
            self._set_status(str(error))
            return
        if remember:
            self._remember_view()
        if context != self.workspace.store.observation.context:
            self._namespace_parent = self._namespace_state = None
            self._namespace_route = False
            self._custom_layouts.clear()
        self._connection_task = self.workspace.connect(
            context, scope=scope, authenticate=authenticate
        )
        self._clear_rows()
        self.header.update_identity()
        self._update_trail()
        self._set_status("Connecting · F2 contexts · F4 retry · Ctrl+Q quit")

    def _refresh_tables(self) -> None:
        self.resources.refresh_ages()
        self.namespace_table.refresh_ages()
        self.standard_table.refresh_ages()
        self.custom_table.refresh_ages()
        self._render_ready.set()

    async def _observe_view(self, subscription: ViewSubscription) -> None:
        try:
            async for observation in subscription:
                if observation.context is None:
                    continue
                if (
                    self.is_running
                    and observation.revision == self.workspace.store.observation.revision
                ):
                    self._render_ready.set()
                    self.command_input.refresh_choices()
                    if self._pending_generic is not None and self.workspace.discovery is not None:
                        pending, self._pending_generic = self._pending_generic, None
                        self._apply_generic(pending)
                    for header in self.query(WorkspaceHeader):
                        header.update_identity()
                    for screen in tuple(self.screen_stack):
                        if isinstance(
                            screen, (InspectionScreen, LogScreen, ContainerScreen, ShellScreen)
                        ):
                            screen.validate_target()
        except Exception as error:
            self._handle_exception(error)
        finally:
            subscription.close()

    async def _render_views(self) -> None:
        try:
            while True:
                await self._render_ready.wait()
                self._render_ready.clear()
                view = self.workspace.store.observation
                query = self.filter_input.value
                kind = self._resource_name

                def current(
                    view: ViewObservation = view,
                    query: str = query,
                    kind: str = kind,
                    layout: CustomLayout | None = None,
                ) -> bool:
                    return (
                        self.is_running
                        and view is self.workspace.store.observation
                        and query == self.filter_input.value
                        and kind == self._resource_name
                        and (layout is None or layout == self.custom_table.resource_layout)
                    )

                if kind == "namespaces":
                    await self._pod_projection.project(None)
                    await self._standard_projection.project(None)
                    ns_rows = await self._namespace_projection.project(view.snapshot)
                    ns_result = await apply_filter(ns_rows, query, "namespaces")
                    count, filtered, problem = len(ns_rows), len(ns_result.rows), ns_result.problem
                    applied = await self.namespace_table.apply_rows(
                        ns_result.rows, view.revision, current
                    )
                elif kind == "contexts":
                    await self._pod_projection.project(None)
                    await self._namespace_projection.project(None)
                    await self._standard_projection.project(None)
                    context_rows = self._context_rows(view.context)
                    ctx_result = await apply_filter(context_rows, query, "contexts")
                    count, filtered, problem = (
                        len(context_rows),
                        len(ctx_result.rows),
                        ctx_result.problem,
                    )
                    applied = await self.context_table.apply_rows(ctx_result.rows, current)
                elif kind == "pods":
                    await self._namespace_projection.project(None)
                    await self._standard_projection.project(None)
                    rows = await self._pod_projection.project(view.snapshot)
                    result = await apply_filter(rows, query)
                    count, filtered, problem = len(rows), len(result.rows), result.problem
                    applied = await self.resources.apply_rows(result.rows, view.revision, current)
                elif self.custom_table.display:
                    await self._pod_projection.project(None)
                    await self._namespace_projection.project(None)
                    await self._standard_projection.project(None)
                    snapshot = view.snapshot
                    layout = self.custom_table.resource_layout
                    if snapshot is not None:
                        key = (
                            view.context or "",
                            snapshot.resource.group,
                            snapshot.resource.version,
                            snapshot.resource.name,
                        )
                        layout = self._custom_layouts.get(key)
                        if (
                            layout is None
                            or layout.resource != snapshot.resource
                            or layout.headers != snapshot.columns
                        ):
                            layout = CustomLayout.build(snapshot.resource, snapshot.columns)
                        self._remember_layout(key, layout)
                        if self.custom_table.resource_layout != layout:
                            self.custom_table.configure_layout(layout, view.revision)
                            self._custom_projection = CustomProjection(layout)
                    custom_rows = (
                        await self._custom_projection.project(snapshot)
                        if self._custom_projection is not None
                        else ()
                    )
                    custom_result = await apply_filter(custom_rows, query, kind)
                    count, filtered, problem = (
                        len(custom_rows),
                        len(custom_result.rows),
                        custom_result.problem,
                    )
                    applied = await self.custom_table.apply_rows(
                        custom_result.rows, view.revision, partial(current, layout=layout)
                    )
                else:
                    await self._pod_projection.project(None)
                    await self._namespace_projection.project(None)
                    standard_rows = await self._standard_projection.project(view.snapshot)
                    standard_result = await apply_filter(standard_rows, query, kind)
                    count, filtered, problem = (
                        len(standard_rows),
                        len(standard_result.rows),
                        standard_result.problem,
                    )
                    applied = await self.standard_table.apply_rows(
                        standard_result.rows, view.revision, current
                    )
                if applied:
                    self._show_view(view)
                    if query:
                        detail = (
                            "Local kubeconfig catalogue" if kind == "contexts" else view.message
                        )
                        self._set_view_status(
                            view, problem or f"Filter active · {filtered}/{count} {kind} · {detail}"
                        )
                        if (
                            count
                            and not filtered
                            and (view.status is ViewStatus.LIVE or kind == "contexts")
                            and problem is None
                        ):
                            self.query_one("#empty-title", Static).update(
                                f"No {kind} match this filter"
                            )
                            self.query_one("#empty-description", Static).update(
                                "Escape in the table clears the filter."
                            )
                    if (
                        self._restore_state is not None
                        and self._restore_state[0] == view.revision
                        and (view.snapshot is not None or kind == "contexts")
                    ):
                        state = self._restore_state[1]
                        if self.custom_table.display:
                            compatible = (
                                self.custom_table.resource_layout is not None
                                and self.custom_table.resource_layout.headers == state.headers
                            )
                            self.custom_table.restore_sort(
                                state.column if compatible else "name",
                                state.descending if compatible else False,
                            )
                        self._active_table.restore_viewport(
                            Viewport(state.selected, state.index, state.x, state.y, state.top)
                        )
                        self._restore_state = None
                    if self._column_notice is not None:
                        self._set_status(self._column_notice)
                    self._update_trail()
        except Exception as error:
            self._handle_exception(error)

    def _context_rows(self, selected: str | None) -> tuple[ContextRow, ...]:
        rows = []
        for name, entry in self.sessions.catalog.contexts.items():
            cluster, user, namespace = (
                entry.data.get(key) for key in ("cluster", "user", "namespace")
            )
            rows.append(
                ContextRow(
                    name,
                    cluster if isinstance(cluster, str) else "—",
                    user if isinstance(user, str) else "—",
                    namespace if isinstance(namespace, str) else "default",
                    name == selected,
                )
            )
        return tuple(rows)

    def _show_view(self, view: ViewObservation) -> None:
        observation = view.connection
        self.header.update_identity()
        if self._resource_name == "contexts":
            self.query_one("#resource-view", Vertical).border_title = safe_text(
                f"contexts[{self.context_table.row_count}]"
            )
            self.query_one("#empty-state").display = not bool(self.context_table.row_count)
            self.context_table.set_class(bool(self.context_table.row_count), "populated")
            self.query_one("#empty-title", Static).update("No contexts match this filter")
            self.query_one("#empty-description", Static).update(
                "Escape in the table clears the filter."
            )
            self._show_sort()
            self._set_view_status(
                view, "Local kubeconfig contexts · Enter connect · Esc previous view"
            )
            return
        usable = observation.state in USABLE_CONNECTIONS
        self.query_one("#empty-title", Static).update(
            "Stale resource data"
            if view.snapshot is not None and view.problem is not None
            else "Resource data unavailable"
            if usable and view.status is ViewStatus.FAILED
            else f"No {self._resource_name} in this scope"
            if view.snapshot is not None and not view.snapshot.items
            else f"{self._resource_name.title()} ready"
            if view.status is ViewStatus.LIVE
            else "Loading resources"
            if usable
            else "Connection unavailable"
        )
        self.query_one("#empty-description", Static).update(
            f"No {self._resource_name} were returned. :ns namespaces · :ctx contexts."
            if view.status is ViewStatus.LIVE
            else "Keeping the last snapshot while reconnecting. Press i for details."
            if view.status is ViewStatus.STALE
            else "Press i for status · r retry · :ctx choose context."
        )
        scope = (
            "all"
            if self._resource_name == "namespaces"
            else "cluster"
            if view.scope is not None and not view.scope.resource.namespaced
            else observation.namespace or "all"
        )
        self.query_one("#resource-view", Vertical).border_title = safe_text(
            f"{self._resource_name}({scope})[{self._active_table.row_count}]"
            + (
                f" · {view.scope.resource.api_version}"
                if self.custom_table.display and view.scope is not None
                else ""
            )
            + f" · {view.status.name.lower()}"
        )
        self.query_one("#empty-state").display = not bool(self._active_table.row_count)
        self._active_table.set_class(bool(self._active_table.row_count), "populated")
        self._show_sort()
        self._set_view_status(view, view.message)

    def _set_view_status(self, view: ViewObservation, message: str) -> None:
        if self._selection_notice is not None:
            notice_view, notice = self._selection_notice
            if notice_view is view:
                message = notice
            else:
                self._selection_notice = None
        self._set_status(message)

    @on(PodTable.SortChanged)
    @on(StandardTable.SortChanged)
    def _show_sort(self) -> None:
        self.query_one("#resource-view", Vertical).border_subtitle = (
            self.resources.sort_summary
            if self._resource_name == "pods"
            else "Name ↑ · Enter connect · * selected session"
            if self._resource_name == "contexts"
            else "Name ↑ · Enter use namespace · 0 all"
            if self._resource_name == "namespaces"
            else self.custom_table.sort_summary
            if self.custom_table.display
            else self.standard_table.sort_summary
        )

    async def _close_client_operations(self, client: KubernetesSession) -> None:
        closing = asyncio.gather(
            self.mutations.stop_for_client(client),
            self.forwards.stop_for_client(client),
            *(
                screen.stop_owned()
                for screen in tuple(self.screen_stack)
                if isinstance(
                    screen, (AnnotationScreen, EditingScreen, WorkloadScreen, TransferScreen)
                )
                and screen.source.client is client
            ),
            *(
                screen.stop_owned()
                for screen in tuple(self.screen_stack)
                if isinstance(screen, ResourceOperationScreen)
                and screen.sources[0].client is client
            ),
        )
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await _finish_owned(closing)
            raise

    async def on_unmount(self) -> None:
        try:
            await self.mutations.close()
            await self.forwards.close()
            await self.processes.close()
            await self.workspace.close()
            if self._view_task is not None:
                await asyncio.gather(self._view_task, return_exceptions=True)
            if self._render_task is not None:
                self._render_task.cancel()
                await asyncio.gather(self._render_task, return_exceptions=True)
            await self._pod_projection.project(None)
            await self._namespace_projection.project(None)
            await self._standard_projection.project(None)
            if self._custom_projection is not None:
                await self._custom_projection.project(None)
        finally:
            self._terminal_signals.restore()

    @on(DataTable.RowSelected, "#namespaces")
    def namespace_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        view = self.workspace.store.observation
        record = (
            next((item for item in view.snapshot.items if item.uid == event.row_key.value), None)
            if view.snapshot is not None
            else None
        )
        if self._resource_name == "namespaces" and record is not None:
            self._namespace_selected(record.name)

    @on(Button.Pressed, "#all-namespaces")
    def action_all_namespaces(self) -> None:
        self._namespace_selected("*")

    @on(DataTable.RowSelected, "#resources")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_logs(containers_first=True, uid=event.row_key.value)

    @on(DataTable.RowSelected, "#standard-resources")
    @on(DataTable.RowSelected, "#custom-resources")
    def standard_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._inspect("details")

    def action_inspect_yaml(self) -> None:
        self._inspect("yaml")

    def action_inspect_details(self) -> None:
        self._inspect("details")

    def action_inspect_events(self) -> None:
        self._inspect("events")

    def _inspect(self, page: Page) -> None:
        selection = self._capture_target()
        if selection is not None:
            client, resource, _, target, current = selection
            self.push_screen(
                InspectionScreen(
                    InspectionService(client, resource, target, self.commands.policy, current),
                    page,
                )
            )

    def action_logs(self) -> None:
        self._open_logs()

    def action_shell(self) -> None:
        try:
            self.commands.policy.require(Action.EXEC)
        except AppError as error:
            self._set_status(str(error))
            return
        self._open_logs(containers_first=True)

    def action_attach(self) -> None:
        try:
            self.commands.policy.require(Action.ATTACH)
        except AppError as error:
            self._set_status(str(error))
            return
        self._open_logs(containers_first=True)

    def action_upload(self) -> None:
        try:
            self.commands.policy.require(Action.MUTATE)
        except AppError as error:
            self._set_status(str(error))
            return
        self._open_logs(containers_first=True)

    def action_download(self) -> None:
        self._open_logs(containers_first=True)

    def action_port_forwards(self, selected: UUID | None = None) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(
                ForwardScreen(self.forwards, self.chrome, self.breadcrumbs.trail, selected=selected)
            )

    def action_annotate(self) -> None:
        try:
            self.commands.policy.require(Action.MUTATE)
        except AppError as error:
            self._set_status(str(error))
            return
        selection = self._capture_target()
        if selection is not None:
            client, resource, _, target, current = selection
            source = MutationService(client, resource, target, self.commands.policy, current)
            try:
                source.require_current()
            except AppError:
                self._set_status(
                    "This captured resource API cannot be modified here. Select a patchable resource."
                )
                return
            self.push_screen(AnnotationScreen(source, self.mutations))

    def action_writes(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(MutationHistoryScreen(self.mutations))

    def action_resource_operation(self, action: ResourceAction, *, batch: bool = False) -> None:
        try:
            self.commands.policy.require(Action.MUTATE)
        except AppError as error:
            self._set_status(str(error))
            return
        selection = self._capture_target()
        if selection is None:
            return
        selections = [selection]
        if batch:
            uids = tuple(key.value for key in self._active_table.rows)
            if len(uids) > MAX_BATCH:
                self._set_status(
                    "Filter this view to at most 100 rows before choosing a delete batch."
                )
                return
            selections = []
            for uid in uids:
                captured = self._capture_target(uid)
                if captured is None:
                    return
                selections.append(captured)
        sources = []
        try:
            for client, resource, _, target, current in selections:
                source = ResourceOperationService(
                    client, resource, target, self.commands.policy, current, action
                )
                source.require_current()
                sources.append(source)
        except AppError as error:
            self._set_status(str(error))
            return
        self.push_screen(ResourceOperationScreen(tuple(sources), self.mutations, batch=batch))

    def action_workload(self, operation: WorkloadAction, argument: str = "") -> None:
        try:
            self.commands.policy.require(
                Action.READ if operation is WorkloadAction.STATUS else Action.MUTATE
            )
        except AppError as error:
            self._set_status(str(error))
            return
        selection = self._capture_target()
        if selection is not None:
            client, resource, _, target, current = selection
            try:
                applicable(resource, operation)
            except AppError as error:
                self._set_status(str(error))
                return
            self.push_screen(
                WorkloadScreen(
                    WorkloadService(client, resource, target, self.commands.policy, current),
                    self.mutations,
                    operation,
                    argument,
                )
            )

    def action_edit(self) -> None:
        try:
            self.commands.policy.require(Action.MUTATE)
        except AppError as error:
            self._set_status(str(error))
            return
        selection = self._capture_target()
        if selection is not None:
            client, resource, _, target, current = selection
            source = EditingService(client, resource, target, self.commands.policy, current)
            try:
                source.require_current()
            except AppError:
                self._set_status("Select a readable, patchable resource before editing.")
                return
            self.push_screen(
                EditingScreen(
                    source,
                    self.mutations,
                    self.processes,
                    self._process_environment,
                    self._process_directory,
                )
            )

    def _forward_started(self, identity: UUID | None) -> None:
        if identity is not None:
            self.action_port_forwards(identity)

    def action_port_forward(self) -> None:
        try:
            self.commands.policy.require(Action.PORT_FORWARD)
        except AppError as error:
            self._set_status(str(error))
            return
        selection = self._capture_target()
        if selection is None:
            return
        client, _, record, target, selected = selection

        def current_connection() -> bool:
            identity = self.sessions.observation.identity
            return (
                self.sessions.client is client
                and identity is not None
                and identity.connection_id == target.session.connection_id
            )

        source = ForwardService(
            client,
            target,
            self.commands.policy,
            current_connection,
            environment=self._process_environment,
            directory=self._process_directory,
        )
        try:
            source.require_current()
        except AppError as error:
            self._set_status(str(error))
            return
        remote = suggested_port(target.resource, record.manifest)
        self.push_screen(
            ForwardPrompt(self.forwards, source, selected, initial=f"0:{remote}"),
            self._forward_started,
        )

    def _open_logs(self, *, containers_first: bool = False, uid: str | None = None) -> None:
        selection = self._capture_target(uid)
        if selection is None:
            return
        client, resource, record, target, current = selection
        try:
            if resource.group or resource.name != "pods" or not record.namespace:
                raise AppError("Select a namespaced pod to open container logs.")
            containers = log_containers(record.manifest)
            if not containers:
                raise AppError("The selected pod has no regular/init/ephemeral containers.")
        except AppError as error:
            self._set_status(str(error))
            return
        stream = LogStream(client, target, self.commands.policy, current)
        self.push_screen(
            ContainerScreen(
                stream,
                record.manifest,
                shell=ShellService(
                    client,
                    target,
                    self.commands.policy,
                    current,
                    shell=self._shell,
                    environment=self._process_environment,
                    directory=self._process_directory,
                ),
                processes=self.processes,
                attach=AttachService(
                    client,
                    target,
                    self.commands.policy,
                    current,
                    environment=self._process_environment,
                    directory=self._process_directory,
                ),
                transfers=TransferService(
                    client,
                    target,
                    self.commands.policy,
                    current,
                    environment=self._process_environment,
                    directory=self._process_directory,
                ),
                chrome=self.chrome,
                trail=self.breadcrumbs.trail,
            )
            if containers_first
            else LogScreen(stream, containers, chrome=self.chrome, trail=self.breadcrumbs.trail)
        )

    def _capture_target(
        self,
        uid: str | None = None,
    ) -> (
        tuple[KubernetesSession, ApiResource, ResourceRecord, ResourceTarget, Callable[[], bool]]
        | None
    ):
        if isinstance(self.screen, ModalScreen):
            return None
        if self._resource_name == "contexts":
            self._set_status(
                "Contexts are local configuration. Enter connects to the selected context."
            )
            return None
        view = self.workspace.store.observation
        scope, snapshot, client = view.scope, view.snapshot, self.sessions.client
        uid = uid if uid is not None else self._active_table.capture_viewport().selected
        if scope is None or snapshot is None or client is None or uid is None:
            self._set_status("Select a connected resource before opening a viewer.")
            return None
        record = next((item for item in snapshot.items if item.uid == uid), None)
        if record is None or record.uid is None:
            self._set_status("The selected target is stale; select the resource again.")
            return None
        target = ResourceTarget(
            scope.session,
            scope.resource.group,
            scope.resource.name,
            record.namespace,
            record.name,
            record.uid,
        )

        def current() -> bool:
            observation = self.workspace.store.observation
            return (
                self.sessions.client is client
                and observation.scope == scope
                and observation.revision == view.revision
                and observation.snapshot is not None
                and any(item.uid == target.uid for item in observation.snapshot.items)
            )

        return client, scope.resource, record, target, current

    def action_contexts(self) -> None:
        if not self.sessions.catalog.names:
            self._set_status("No contexts found. Configure KUBECONFIG or use --kubeconfig.")
        elif not isinstance(self.screen, ModalScreen):
            if self._resource_name == "contexts":
                self.set_focus(self.context_table)
                return
            self._context_parent = self._capture_view()
            self._remember_view()
            self._display_resource("contexts")
            self.filter_input.value = (
                self._context_state.query if self._context_state is not None else ""
            )
            if self._context_state is not None:
                self._restore_state = self.workspace.store.observation.revision, self._context_state
            self.command_input.reset_choice()
            self._render_ready.set()

    @on(DataTable.RowSelected, "#contexts")
    def context_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self._resource_name == "contexts":
            self._context_selected(event.row_key.value)

    def action_connection_details(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(ConnectionScreen(self._workspace_status()))

    def _context_selected(self, value: str | None) -> None:
        if value is not None:
            self._context_state = (
                self._capture_view() if self._resource_name == "contexts" else self._context_state
            )
            self._remember_view()
            self.workspace.selection = ResourceSelection("pods")
            self._display_resource("pods")
            self.filter_input.value = ""
            self._start_connection(value, remember=False)

    def _clear_rows(self) -> None:
        self._restore_state = None
        if self._resource_name == "contexts":
            self.command_input.reset_choice()
            self._render_ready.set()
            return
        table = self._active_table
        assert not isinstance(table, ContextTable)
        table.reset(self.workspace.store.observation.revision)
        self._active_table.remove_class("populated")
        self.query_one("#empty-state").display = True
        self.query_one("#empty-title", Static).update("Loading resources")
        self.command_input.reset_choice()

    def action_namespaces(self) -> None:
        observation = self.workspace.store.observation.connection
        if observation.state not in USABLE_CONNECTIONS:
            message = "Connect to a context before selecting a namespace."
            self._selection_notice = self.workspace.store.observation, message
            self._set_status(message)
        elif not isinstance(self.screen, ModalScreen):
            self._select_resource("namespaces", restore=self._namespace_state)

    def _display_resource(
        self, resource: str, *, focus: bool = True, generic: ResourceSelection | None = None
    ) -> None:
        self._resource_name = resource
        self._generic_selection = generic
        self._column_notice = None
        namespaces = resource == "namespaces"
        self.namespace_table.display = namespaces
        self.context_table.display = resource == "contexts"
        self.resources.display = resource == "pods"
        self.standard_table.display = generic is None and resource in RESOURCE_ALIASES
        self.custom_table.display = generic is not None
        if self.standard_table.display:
            definition = RESOURCE_ALIASES[resource]
            if self.standard_table.definition != definition:
                self.standard_table.configure(definition)
                self._standard_projection = StandardProjection(definition)
        self.query_one("#all-namespaces").display = namespaces
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
            else workload_shortcuts(resource, self.commands.policy.read_only)
        )
        self.header.render_shortcuts()
        if focus and len(self.screen_stack) == 1:
            self.set_focus(self._active_table)
        self._update_trail()

    def _select_resource(
        self,
        resource: str,
        *,
        restore: NavigationState | None = None,
        scope: NamespaceChoice | None = None,
        generic: ResourceSelection | None = None,
    ) -> None:
        current = self._capture_view()
        if self._resource_name == "contexts":
            self._context_state = current
        if resource == self._resource_name and generic == self._generic_selection and scope is None:
            self.set_focus(self._active_table)
            return
        try:
            self._connection_task = self.workspace.select_resource(
                generic or resource_selection(resource)
            )
            if scope is not None:
                self._connection_task = self.workspace.select_namespace(scope.namespace)
        except AppError as error:
            self._set_status(str(error))
            return
        if current is not None:
            self.history.visit(current)
            if current.resource == "namespaces":
                self._namespace_state = current
                self._namespace_route = True
            elif resource == "namespaces":
                self._namespace_parent = current
        self._display_resource(resource, generic=generic)
        self._clear_rows()
        self.filter_input.value = restore.query if restore is not None else ""
        if restore is not None:
            self._restore_state = self.workspace.store.observation.revision, restore
        self._render_ready.set()

    def _namespace_selected(self, value: str | None) -> None:
        if value is not None:
            try:
                choice = NamespaceChoice(None if value == "*" else value)
                current = self._capture_view()
                was_namespace_view = self._resource_name == "namespaces"
                was_context_view = self._resource_name == "contexts"
                if was_context_view:
                    self._context_state = current
                generic = (
                    self._generic_selection
                    if self.custom_table.display
                    else self._namespace_parent.generic
                    if was_namespace_view and self._namespace_parent is not None
                    else None
                )
                self.workspace.select_resource(generic or ResourceSelection("pods"))
                self._connection_task = self.workspace.select_namespace(choice.namespace)
                if was_namespace_view:
                    self._namespace_state = current
                    self._namespace_route = True
                if current is not None:
                    self.history.visit(current)
                self._display_resource(
                    (generic.name + "." + (generic.group or "core"))
                    if generic is not None
                    else "pods",
                    generic=generic,
                    focus=was_namespace_view
                    or was_context_view
                    or not isinstance(self.focused, Input),
                )
                self._clear_rows()
                if was_namespace_view or was_context_view:
                    self.filter_input.value = ""
                self.header.update_identity()
                self._set_status(self._workspace_status())
            except AppError as error:
                self._set_status(str(error))

    def action_retry(self) -> None:
        context = (
            self.workspace.store.observation.context
            or self.sessions.request.context
            or self.sessions.catalog.current
        )
        if context is not None:
            self._start_connection(context)
        else:
            self.action_contexts()

    def _remember_layout(self, key: tuple[str, str, str, str], layout: CustomLayout) -> None:
        self._custom_layouts.pop(key, None)
        self._custom_layouts[key] = layout
        while len(self._custom_layouts) > MAX_HISTORY:
            del self._custom_layouts[next(iter(self._custom_layouts))]

    def _apply_generic(self, command: GenericResourceCommand) -> None:
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
            self._select_resource(
                resource.name + "." + (resource.group or "core"),
                scope=scope,
                generic=selection,
            )
            if self._generic_selection == selection:
                key = (
                    self.workspace.store.observation.context or "",
                    resource.group,
                    resource.version,
                    resource.name,
                )
                layout = self._custom_layouts.get(key) or CustomLayout.build(resource, ())
                self.custom_table.configure_layout(
                    layout, self.workspace.store.observation.revision
                )
                self._custom_projection = CustomProjection(layout)
        except AppError as error:
            self._column_notice = str(error)
            self._set_status(self._column_notice)

    def _refresh_discovery(self) -> None:
        state = self._capture_view()
        try:
            self._connection_task = self.workspace.refresh_discovery()
        except AppError as error:
            self._set_status(str(error))
            return
        self._clear_rows()
        if state is not None:
            self._restore_state = self.workspace.store.observation.revision, state
        self._column_notice = None
        self.command_input.refresh_choices()
        self._render_ready.set()

    def _configure_columns(self, argument: str = "") -> None:
        layout = self.custom_table.resource_layout if self.custom_table.display else None
        if layout is None:
            self._set_status("Select a discovered resource before configuring server columns.")
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
                self.custom_table.configure_layout(
                    configured, self.workspace.store.observation.revision
                )
                self._custom_projection = CustomProjection(configured)
                view = self.workspace.store.observation
                self._remember_layout(
                    (
                        view.context or "",
                        configured.resource.group,
                        configured.resource.version,
                        configured.resource.name,
                    ),
                    configured,
                )
                self._column_notice = "Custom columns updated for this session."
                self._render_ready.set()
        except AppError as error:
            self._column_notice = str(error)
        self._set_status(self._column_notice or self._workspace_status())

    def action_login(self) -> None:
        context = (
            self.workspace.store.observation.context
            or self.sessions.request.context
            or self.sessions.catalog.current
        )
        if context is None:
            self.action_contexts()
        else:
            self._start_connection(context, authenticate=self._credential_login)

    async def _credential_login(self, credentials: ExecToken) -> str | None:
        command = credentials.invocation(interactive=True)
        try:
            result = await terminal_handoff(self, self.processes, command, timeout=300)
        except ExecutableUnavailable:
            raise auth_problem(helper_start_failure(command.argv, missing=True)) from None
        except AppError:
            raise auth_problem(
                "Credential login requires a usable native terminal and executable. Complete the configured provider login externally, then retry."
            ) from None
        if result.status is not ProcessStatus.SUCCEEDED:
            raise auth_problem(
                "Credential login did not complete. Retry :login or complete the configured provider login externally, then retry the connection."
            )
        return credentials.accept(result.stdout, command)

    def on_resize(self, event: Resize) -> None:
        if not self.is_headless and not self.is_web:
            size = current_terminal_size()
            if size is not None:
                # Nested POSIX signal callbacks may enqueue an older snapshot
                # after a newer one. Normalize the public event before Textual's
                # base handler updates layout/owned child geometry.
                event.size = event.virtual_size = event.container_size = Size(*size)
        self.header.layout_header()
        self.screen_stack[0].set_class(event.size.width < 70, "compact")
        self.screen_stack[0].set_class(event.size.height < 16, "short")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if self.custom_table.display and action == "edit":
            return False
        if action == "port_forward" and self._resource_name not in {"pods", "services"}:
            return False
        if (
            action in {"logs", "shell", "attach", "upload", "download"}
            and self._resource_name != "pods"
        ):
            return False
        if action in {
            "focus_filter",
            "focus_command",
            "history_back",
            "history_forward",
            "inspect_yaml",
            "inspect_details",
            "inspect_events",
            "edit",
            "logs",
            "shell",
            "attach",
            "upload",
            "download",
            "port_forward",
        }:
            return not isinstance(self.screen, ModalScreen) and not isinstance(self.focused, Input)
        return True

    def action_focus_filter(self) -> None:
        self.set_focus(self.filter_input)

    def action_focus_command(self) -> None:
        # Apply focus before the next queued key, including rapidly typed commands.
        self.set_focus(self.command_input)

    def action_show_help(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(HelpScreen())

    async def action_back(self) -> None:
        if isinstance(self.screen, (InspectionScreen, LogScreen)):
            self.screen.back()
        elif isinstance(self.screen, TransferScreen):
            await self.screen.cancel()
        elif isinstance(
            self.screen, (AnnotationScreen, EditingScreen, WorkloadScreen, ResourceOperationScreen)
        ):
            screen = self.screen
            await screen.stop_owned()
            screen.dismiss()
        elif isinstance(self.screen, ModalScreen):
            self.screen.dismiss()
        elif isinstance(self.focused, Input):
            self.command_input.value = ""
            self.set_focus(self._active_table)
            self._update_trail()
        elif self.filter_input.value:
            self.filter_input.value = ""
            self._set_status(self._workspace_status())
            self._update_trail()
        elif self._resource_name == "contexts":
            self._context_state = self._capture_view()
            if self._context_parent is not None:
                self._restore_navigation(self._context_parent)
            else:
                selection = self.workspace.selection
                self._display_resource(
                    selection.name + "." + (selection.group or "core")
                    if selection.server_columns
                    else selection.name,
                    generic=selection if selection.server_columns else None,
                )
                self._render_ready.set()
        elif (self._resource_name == "pods" or self.custom_table.display) and self._namespace_route:
            self.action_namespaces()
        elif self._resource_name == "namespaces":
            self._namespace_route = False
            if self._namespace_parent is not None:
                self._restore_navigation(self._namespace_parent)
            else:
                self._select_resource("pods")
        else:
            self.filter_input.value = ""
            self._set_status(self._workspace_status())

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self._render_ready.set()
        self._update_trail()

    @on(Input.Submitted, "#command")
    def command_submitted(self, event: Input.Submitted) -> None:
        self._submit_command(event.value)

    def _submit_command(self, value: str) -> None:
        self._column_notice = None
        try:
            command = self.commands.resolve(value, self.workspace.discovery)
        except AppError as error:
            if self.custom_table.display:
                self._column_notice = str(error)
            self._set_status(str(error))
            return
        self._apply_command(command)

    def _apply_command(self, command: ResolvedCommand) -> None:
        if isinstance(command, GenericResourceCommand):
            self._apply_generic(command)
            return
        if isinstance(command, ResourceCommand):
            scope = (
                NamespaceChoice(None if command.scope == "*" else command.scope)
                if command.scope is not None
                else None
            )
            self._select_resource(command.definition.name, scope=scope)
            return
        action_command = command.command if isinstance(command, ScopedCommand) else command
        if self.custom_table.display and action_command in {
            Command.ANNOTATE,
            Command.EDIT,
            Command.DELETE,
            Command.DELETE_BATCH,
            Command.TRIGGER,
            Command.SUSPEND,
            Command.RESUME,
            Command.SCALE,
            Command.RESTART,
            Command.ROLLBACK,
        }:
            self._column_notice = "Generic resources are read-only in this checkpoint."
            self._set_status(self._column_notice)
            return
        if isinstance(command, ScopedCommand):
            if command.command is Command.COLUMNS:
                self._configure_columns(command.argument)
            elif command.command in {Command.SCALE, Command.ROLLBACK}:
                self.action_workload(
                    WorkloadAction.SCALE
                    if command.command is Command.SCALE
                    else WorkloadAction.ROLLBACK,
                    command.argument,
                )
            elif command.command is Command.CONTEXTS:
                self._context_selected(command.argument)
            else:
                self._namespace_selected(command.argument)
            return
        if command is Command.HELP:
            self.action_show_help()
        elif command is Command.QUIT:
            self.exit()
        elif command is Command.UNAVAILABLE:
            self._set_status(
                "Command unavailable in this preview. Use :help for available views and actions."
            )
        elif command is Command.CONTEXTS:
            self.action_contexts()
        elif command is Command.NAMESPACES:
            self.action_namespaces()
        elif command is Command.STATUS:
            self.action_connection_details()
        elif command is Command.RETRY:
            self.action_retry()
        elif command is Command.REFRESH:
            self._refresh_discovery()
        elif command is Command.COLUMNS:
            self._configure_columns()
        elif command is Command.LOGIN:
            self.action_login()
        elif command is Command.BACK:
            self.action_history_back()
        elif command is Command.FORWARD:
            self.action_history_forward()
        elif command is Command.PODS:
            self._select_resource("pods")
            self._set_status(self._workspace_status())
        elif command is Command.SHELL:
            self.action_shell()
        elif command is Command.ATTACH:
            self.action_attach()
        elif command is Command.UPLOAD:
            self.action_upload()
        elif command is Command.DOWNLOAD:
            self.action_download()
        elif command is Command.PORT_FORWARD:
            self.action_port_forward()
        elif command is Command.PORT_FORWARDS:
            self.action_port_forwards()
        elif command is Command.ANNOTATE:
            self.action_annotate()
        elif command is Command.WRITES:
            self.action_writes()
        elif command is Command.EDIT:
            self.action_edit()
        elif command in {
            Command.DELETE,
            Command.DELETE_BATCH,
            Command.TRIGGER,
            Command.SUSPEND,
            Command.RESUME,
        }:
            self.action_resource_operation(
                {
                    Command.DELETE: ResourceAction.DELETE,
                    Command.DELETE_BATCH: ResourceAction.DELETE,
                    Command.TRIGGER: ResourceAction.TRIGGER,
                    Command.SUSPEND: ResourceAction.SUSPEND,
                    Command.RESUME: ResourceAction.RESUME,
                }[command],
                batch=command is Command.DELETE_BATCH,
            )
        elif command in {Command.SCALE, Command.RESTART, Command.ROLLBACK, Command.ROLLOUT}:
            self.action_workload(
                {
                    Command.SCALE: WorkloadAction.SCALE,
                    Command.RESTART: WorkloadAction.RESTART,
                    Command.ROLLBACK: WorkloadAction.ROLLBACK,
                    Command.ROLLOUT: WorkloadAction.STATUS,
                }[command]
            )
        else:
            self._set_status(self._workspace_status())

    def _namespace_choices(self) -> tuple[str, ...]:
        connection = self.workspace.store.observation.connection
        if connection.state not in USABLE_CONNECTIONS:
            return ()
        current = (connection.namespace,) if connection.namespace is not None else ()
        return ("*", *sorted(set(connection.namespaces) | set(current)))

    def _suggestions(self, value: str) -> tuple[str, ...]:
        return suggestions(
            value, self.sessions.catalog.names, self._namespace_choices(), self.workspace.discovery
        )

    @on(Input.Changed, "#command")
    def command_changed(self) -> None:
        self.command_input.refresh_choices()

    def _capture_view(self) -> NavigationState | None:
        view = self.workspace.store.observation
        if self._resource_name != "contexts" and (
            view.context is None or view.connection.state not in USABLE_CONNECTIONS
        ):
            return None
        viewport = self._active_table.capture_viewport()
        return NavigationState(
            view.context or "",
            view.connection.namespace,
            self.filter_input.value,
            self._active_table.sort_column
            if isinstance(self._active_table, StandardTable)
            else self.resources.sort_column,
            self._active_table.descending
            if isinstance(self._active_table, StandardTable)
            else self.resources.descending,
            viewport.selected,
            viewport.index,
            viewport.x,
            viewport.y,
            viewport.top,
            self._resource_name,
            self._generic_selection,
            self.custom_table.resource_layout.headers
            if self.custom_table.display and self.custom_table.resource_layout is not None
            else (),
        )

    def _remember_view(self) -> None:
        current = self._capture_view()
        if current is not None:
            self.history.visit(current)

    def _navigate_history(self, *, forward: bool = False) -> None:
        current = self._capture_view()
        view = self.workspace.store.observation
        if current is None and view.context is not None:
            current = NavigationState(view.context, view.connection.namespace)
        state = self.history.move(current, forward=forward) if current is not None else None
        if state is None:
            self._set_status(
                "No next view in history." if forward else "No previous view in history."
            )
            return
        self._restore_navigation(state)

    def _restore_navigation(self, state: NavigationState) -> None:
        if state.resource == "contexts":
            if self._resource_name != "contexts":
                self._context_parent = self._capture_view()
            self._display_resource("contexts")
            self.filter_input.value = state.query
            self._restore_state = self.workspace.store.observation.revision, state
            self._render_ready.set()
            return
        scope = NamespaceChoice(state.namespace)
        current = self.workspace.store.observation
        if state.context == current.context and current.connection.state in USABLE_CONNECTIONS:
            self.workspace.select_resource(state.generic or resource_selection(state.resource))
            self._connection_task = self.workspace.select_namespace(state.namespace)
            self._display_resource(state.resource, generic=state.generic)
            self._clear_rows()
            self.header.update_identity()
        else:
            self.workspace.selection = state.generic or resource_selection(state.resource)
            self._display_resource(state.resource, generic=state.generic)
            self._start_connection(state.context, scope=scope, remember=False)
        self.filter_input.value = state.query
        if state.resource == "pods":
            self.resources.restore_sort(PodColumn(state.column), state.descending)
        elif state.resource in RESOURCE_ALIASES:
            self.standard_table.restore_sort(state.column, state.descending)
        self._restore_state = self.workspace.store.observation.revision, state

    def action_history_back(self) -> None:
        self._navigate_history()

    def action_history_forward(self) -> None:
        self._navigate_history(forward=True)

    def _handle_exception(self, error: Exception) -> None:
        """Narrow Textual 8.x boundary: log safely while preserving its cleanup/testing."""
        if self._input_completion is not None and not self._input_completion.done():
            self._input_completion.set_result(None)
        with suppress(AppError):
            self._diagnostic_logger.error(
                "Terminal interface failed.", exc_info=(type(error), error, error.__traceback__)
            )
        super()._handle_exception(error)

    def _print_error_renderables(self) -> None:
        # Textual's default prints exception values/source/locals after restoring the TTY.
        # The launcher emits an owned safe message; tests verify this boundary in a PTY.
        self._exit_renderables.clear()
