"""A responsive workspace subscribed to its owned Kubernetes resource view."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from contextlib import suppress
from functools import partial
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from rich.console import RenderableType
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.dom import DOMNode
from textual.events import DescendantFocus, Event, Resize
from textual.geometry import Size
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Static

from kuberich.adapters.credentials import CredentialLogin, ExecToken, auth_problem
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.terminal import current_terminal_size
from kuberich.config.catalog import KubeCatalog, kubeconfig_paths, load_catalog
from kuberich.config.forwarding import ForwardPreferences, forwarding_from
from kuberich.config.navigation import NavigationPreferences, navigation_from
from kuberich.config.schema import Settings
from kuberich.domain.appearance import Appearance
from kuberich.domain.cleanup import finished_pods
from kuberich.domain.clipboard import ClipboardBackend, clipboard_backend, clipboard_bytes, osc52
from kuberich.domain.connections import (
    DEFAULT_CONNECTION,
    ConnectionRequest,
)
from kuberich.domain.credential_helpers import helper_start_failure
from kuberich.domain.interactions import InteractionCommand
from kuberich.domain.keyboard import effective_keymap
from kuberich.domain.kubeconfig_edit import ContextChange
from kuberich.domain.navigation import (
    NamespaceChoice,
    NavigationHistory,
    NavigationState,
)
from kuberich.domain.operations import MAX_BATCH, ResourceAction
from kuberich.domain.processes import ProcessStatus
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_actions import ViewState
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import ResourceSelection
from kuberich.domain.workloads import WorkloadAction
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.appearance import PreferenceSource
from kuberich.services.clipboard import ClipboardQueue, NativeClipboard
from kuberich.services.command_catalog import COMMAND_CATALOG, BoundCommands
from kuberich.services.commands import (
    Command,
    CommandService,
    GenericResourceCommand,
    ResolvedCommand,
)
from kuberich.services.mutations import MutationManager
from kuberich.services.ownership import finish_owned
from kuberich.services.pods import (
    CustomProjection,
    NamespaceProjection,
    PodProjection,
    StandardProjection,
)
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from kuberich.services.updates import UpdateResult, UpdateService
from kuberich.services.workspace import WorkspaceService
from kuberich.ui.appearance_controller import AppearanceController
from kuberich.ui.chrome import (
    POD_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
    WorkspaceLabel,
    header_identity,
)
from kuberich.ui.commands import CommandInput, NavigationInput
from kuberich.ui.contexts import ContextTable
from kuberich.ui.controllers.base import RenderRequest
from kuberich.ui.controllers.filtering import FilterOptions
from kuberich.ui.custom import CustomTable
from kuberich.ui.foreground import ForegroundGate
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.input_dispatch import InputDispatcher
from kuberich.ui.interactions import Interactions
from kuberich.ui.jumps import JumpController
from kuberich.ui.keybindings import NavigationHelpScreen, navigation_help
from kuberich.ui.live_preferences import LivePreferences
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.nested import CommandWorkspace, NestedCommands
from kuberich.ui.plugins import PluginController
from kuberich.ui.pods import PodTable
from kuberich.ui.presentation import DEFAULT_PRESENTATION, Presentation
from kuberich.ui.resource_operations import OperationContext, ResourceOperations
from kuberich.ui.root_views import RootTables, RootViews
from kuberich.ui.shutdown import TerminalSignals
from kuberich.ui.standard import StandardTable
from kuberich.ui.state import AppState, app_state
from kuberich.ui.style_cache import ColorStylesCache, ComponentStylesheet
from kuberich.ui.target_capture import CapturedResource, TargetCapture, TargetSelection
from kuberich.ui.view_errors import ViewErrorPanel
from kuberich.ui.views import ViewPreferences, ViewScreen
from kuberich.ui.workspace_commands import CompletionSources, WorkspaceCommands, bind_commands
from kuberich.ui.workspace_navigation import WorkspaceNavigation
from kuberich.ui.workspace_presenter import WorkspacePresenter
from kuberich.ui.workspace_screen import WorkspaceScreen

if TYPE_CHECKING:
    from kuberich.ui.context_admin import ContextEditResult
    from kuberich.ui.inspection import Page


def __getattr__(name: str) -> object:
    # Retain the existing public import used by embedded workspace consumers.
    if name == "HelpScreen":
        from kuberich.ui.help import HelpScreen

        return HelpScreen
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


DISCONNECTED_STATUS = "Disconnected · No resource data"


class KubeRichApp(App[None]):
    """Keyboard and mouse workspace; startup does not load Kubernetes credentials."""

    CSS_PATH = Path(__file__).with_name("kuberich.tcss")
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = "#resources"
    _startup_stopped = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "focus_filter", "Filter", key_display="/", priority=True),
        Binding("colon", "focus_command", "Cmd", key_display=":", priority=True),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("f1", "show_help", "Help", show=False, priority=True),
        Binding("y", "inspect_yaml", "YAML"),
        Binding("d", "inspect_details", "Details"),
        Binding("e", "inspect_events", "Events"),
        Binding("E", "edit", "Edit", key_display="Shift+E"),
        Binding("v", "configuration_data", "Data keys"),
        Binding("ctrl+d", "review_delete", "Review deletion", show=False),
        Binding("l", "logs", "Logs"),
        Binding("L", "logs_all", "Aggregate logs", key_display="Shift+L"),
        Binding("x", "shell", "Shell"),
        Binding("F", "port_forward", "Port forward", key_display="Shift+F"),
        Binding("c", "contexts", "Contexts"),
        Binding("n", "namespaces", "Namespaces"),
        Binding("r", "retry", "Retry", show=False),
        Binding("i", "connection_details", "Status", show=False),
        Binding("alt+left", "history_back", "Previous view", show=False),
        Binding("alt+right", "history_forward", "Next view", show=False),
        Binding("space", "mark_selection", "Mark", show=False),
        Binding("shift+down", "mark_range(1)", "Extend selection", show=False),
        Binding("shift+up", "mark_range(-1)", "Extend selection", show=False),
        Binding("ctrl+y", "copy_selection", "Copy name", show=False),
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
        preferences: PreferenceSource | None = None,
        updates: UpdateService | None = None,
        environment: Mapping[str, str] | None = None,
        directory: Path | None = None,
        clipboard: NativeClipboard | None = None,
    ) -> None:
        self._foreground = ForegroundGate(lambda: self.views.request())
        super().__init__()
        self.stylesheet = ComponentStylesheet(variables=self.get_css_variables())
        self.title = "KubeRich"
        self.sub_title = "Local preview"
        self._diagnostic_logger = logger
        self._initial_command = initial_command
        self.sessions = SessionService(
            catalog if catalog is not None else KubeCatalog(), connection
        )
        self.workspace = WorkspaceService(self.sessions, on_error=self._handle_exception)
        self.history = NavigationHistory()
        self.interactions = Interactions(self)
        self.navigation = NavigationPreferences()
        self._navigation_warning: str | None = None
        self._navigation_invalid = False
        if preferences is not None:
            try:
                self.navigation = navigation_from(preferences.document)
            except AppError as error:
                self._navigation_warning = str(error)
                self._navigation_invalid = True
        self.navigation_keymap = effective_keymap(self.navigation.keys)
        self.commands = CommandService(AccessPolicy(settings.read_only), self.navigation.aliases)
        self.processes = ProcessRunner(self.commands.policy)
        self.forwards = ForwardManager(self.processes, changed=self._forward_changed)
        self.mutations = MutationManager()
        self.sessions.before_close = self._close_client_operations
        self._terminal_signals = TerminalSignals(self)
        self._shell = settings.shell
        self._process_environment = dict(os.environ) if environment is None else dict(environment)
        self._process_directory = Path.cwd() if directory is None else Path(directory)
        native_clipboard = (
            clipboard
            if clipboard is not None
            else NativeClipboard(self.processes, self._process_environment, self._process_directory)
        )
        self._catalog_task: asyncio.Task[None] | None = None
        self.clipboard_queue = ClipboardQueue(native_clipboard, self._clipboard_failed)
        self.preferences = preferences
        self.live_preferences = LivePreferences(self, settings)
        self.appearance_controller = AppearanceController(
            self,
            settings,
            preferences,
            self._theme_context,
            self.live_preferences.apply,
            lambda: self.chrome.build,
            self._handle_exception,
            invert=presentation.invert,
            updates=updates,
        )
        self.appearance_controller.apply()
        self._mode = ("Read-only" if settings.read_only else "Local preview") + (
            " · inverted" if presentation.invert else ""
        )
        self.resources = PodTable()
        self.namespace_table = NamespaceTable()
        self.namespace_table.display = False
        self.context_table = ContextTable()
        self.context_table.display = False
        self.standard_table = StandardTable()
        self.standard_table.display = False
        self.custom_table = CustomTable()
        self.custom_table.display = False
        self.chrome = WorkspaceChrome(
            partial(header_identity, self.workspace.store, self.sessions),
            f"KubeRich: {version('kuberich')} · {self._mode}",
            presentation,
            self.navigation_keymap,
        )
        self.header = WorkspaceHeader(self.chrome, POD_SHORTCUTS)
        self.breadcrumbs = Breadcrumbs(
            ("pods",), "Clear filter", visible=not presentation.crumbsless
        )

        def focus_table() -> None:
            self.set_focus(self._active_table)

        self.filter_input = NavigationInput(
            focus_table,
            placeholder="Filter resources",
            id="filter",
            history=self.interactions.filter_history,
        )
        self.command_input = CommandInput(
            lambda value: self.command_routes.suggestions(value),
            focus_table,
            lambda value: self.command_routes.submit(value),
            history=self.interactions.history,
        )
        self.status = WorkspaceLabel(DISCONNECTED_STATUS, id="status", markup=False)
        self.view_error = ViewErrorPanel(self.action_retry_view)
        self.view_preferences = ViewPreferences(self)
        self.views = RootViews(
            RootTables(
                self.resources,
                self.namespace_table,
                self.context_table,
                self.standard_table,
                self.custom_table,
            ),
            self._foreground,
            lambda: self.sessions.catalog,
            self.view_preferences,
            self.interactions.filter,
            self._filter_options,
            lambda request: self.presenter.available_actions(request),
            lambda: self.presenter.capture(),
            lambda request, outcome: self.presenter.publish(request, outcome),
            self._handle_exception,
            pod_projection=lambda: PodProjection(),
            namespace_projection=lambda: NamespaceProjection(),
            standard_projection=lambda definition: StandardProjection(definition),
            custom_projection=lambda layout: CustomProjection(layout),
            recover=self._view_rendered,
        )
        self.navigator = WorkspaceNavigation(
            self,
            self.sessions,
            self.workspace,
            self.views,
            self.history,
            self.filter_input,
            self.command_input,
            self.header,
            self.view_preferences,
            self.commands.policy,
            self._set_status,
            self._set_notice,
            self._apply_theme,
            self._update_trail,
            self._disable_namespace_favorites,
            lambda context: dict(self.navigation.favorites).get(context, ()),
        )
        self.presenter = WorkspacePresenter(
            self,
            self.workspace,
            self.views,
            self.interactions,
            self.navigator,
            self.header,
            self.breadcrumbs,
            self.filter_input,
            self.status,
            self.commands.policy,
            self.forwards,
            lambda: self.appearance.full_gvr_titles,
            self._observation_changed,
            self._handle_exception,
            recover=self.views.renderer.fail,
        )
        self.plugins = PluginController(self)
        self.input_dispatch = InputDispatcher(self, self.plugins.bindings, self.plugins.open)
        self.jumps = JumpController(self)
        self.targets = TargetCapture(
            lambda: self.workspace.store.observation,
            lambda: self.sessions.client,
            self._target_selection,
            self._set_notice,
            self._set_status,
        )
        self.operations = ResourceOperations(
            self,
            self.targets.capture,
            self._operation_context,
            self.commands.policy,
            self.mutations,
            self.forwards,
            self.processes,
            self._set_status,
            session_current=self._session_current,
            forwarding=self._forwarding_preferences,
            delete_context=lambda: self._edit_context(ContextChange.DELETE),
            stop_plugins=self.plugins.manager.stop_for_client,
        )
        self.command_routes = WorkspaceCommands(
            self,
            lambda value: self.commands.resolve(value, self.workspace.discovery),
            self.workspace,
            self.navigator,
            self.views,
            self.interactions,
            self._bind_commands(),
            self.plugins.open,
            lambda: CompletionSources(
                self.sessions.catalog.names,
                self.navigation.aliases,
                tuple(plugin.name for plugin in self.plugins.plugins),
                self.jumps.names,
            ),
        )
        self.nested_commands = NestedCommands(
            self.command_routes.suggestions, self.interactions.history, self.route_nested
        )

    def _bind_commands(self) -> BoundCommands:
        return bind_commands(
            self.commands.policy,
            {
                Command.EMPTY: lambda: self._set_status(self._workspace_status()),
                Command.HELP: self.action_show_help,
                Command.THEMES: self.action_change_theme,
                Command.ABOUT: self.action_about,
                Command.VIEWS: self.action_views,
                Command.PLUGINS: self.plugins.open,
                Command.PLUGIN_JOBS: self.action_plugin_jobs,
                Command.QUIT: self.exit,
                Command.STATUS: self.action_connection_details,
                Command.RETRY: self.navigator.retry,
                Command.LOGIN: self.action_login,
                Command.BACK: self.navigator.history_back,
                Command.FORWARD: self.navigator.history_forward,
                Command.SHELL: self.action_shell,
                Command.ATTACH: self.action_attach,
                Command.UPLOAD: self.action_upload,
                Command.DOWNLOAD: self.action_download,
                Command.PORT_FORWARD: self.operations.port_forward,
                Command.PORT_FORWARDS: self.operations.port_forwards,
                Command.ANNOTATE: self.operations.annotate,
                Command.EDIT: self.operations.edit,
                Command.WRITES: self.operations.writes,
                Command.RESTART: partial(self.operations.workload, WorkloadAction.RESTART),
                Command.ROLLOUT: partial(self.operations.workload, WorkloadAction.STATUS),
                Command.DELETE: partial(self.action_resource_operation, ResourceAction.DELETE),
                Command.DELETE_BATCH: partial(
                    self.action_resource_operation, ResourceAction.DELETE, batch=True
                ),
                Command.TRIGGER: partial(self.action_resource_operation, ResourceAction.TRIGGER),
                Command.SUSPEND: partial(self.action_resource_operation, ResourceAction.SUSPEND),
                Command.RESUME: partial(self.action_resource_operation, ResourceAction.RESUME),
                Command.REFRESH: self.navigator.refresh_discovery,
                Command.LOGS_ALL: self.operations.logs_all,
                Command.CLEANUP: self.action_cleanup_pods,
                Command.UNAVAILABLE: lambda: self._set_status(
                    "Command unavailable in this preview. Use :help for available views and actions."
                ),
            },
            {
                Command.PODS: self._command_pods,
                Command.NAMESPACES: lambda value: (
                    self.navigator.namespaces()
                    if value is None
                    else self.navigator.namespace_selected(value)
                ),
                Command.CONTEXTS: lambda value: (
                    self.navigator.contexts()
                    if value is None
                    else self.navigator.context_selected(value)
                ),
                Command.COLUMNS: lambda value: self.navigator.columns(value or ""),
                Command.SERVER: lambda value: self.navigator.server(value or ""),
                Command.RENAME: lambda value: self._edit_context(ContextChange.RENAME, value or ""),
                Command.JUMP: self.jumps.open,
                Command.SCALE: lambda value: self.operations.workload(
                    WorkloadAction.SCALE, value or ""
                ),
                Command.ROLLBACK: lambda value: self.operations.workload(
                    WorkloadAction.ROLLBACK, value or ""
                ),
            },
        )

    def _command_pods(self, argument: str | None) -> None:
        if argument is not None:
            self.navigator.namespace_selected(argument)
        else:
            self.navigator.select_resource("pods")
            self._set_status(self._workspace_status())

    def action_plugin_jobs(self) -> None:
        from kuberich.ui.plugin_screens import PluginJobs

        self.push_screen(PluginJobs(self.plugins.manager))

    def _theme_context(self) -> str | None:
        return (
            self.workspace.store.observation.context
            or self.sessions.request.context
            or self.sessions.catalog.current
        )

    @property
    def appearance(self) -> Appearance:
        return self.appearance_controller.appearance

    @property
    def update_result(self) -> UpdateResult:
        return self.appearance_controller.update_result

    def _apply_theme(self, context: str | None = None) -> None:
        self.appearance_controller.apply(context)

    def action_change_theme(self) -> None:
        self.appearance_controller.open_themes()

    def action_about(self) -> None:
        self.appearance_controller.open_about()

    @property
    def state(self) -> AppState:
        """Return a fresh, frozen semantic snapshot of the root workspace state.

        Safe to read before mounting or when the active table is empty without mutating
        application state. ``context``, ``namespace`` and ``scope`` report the underlying
        workspace observation.
        """
        return app_state(
            self._resource_name,
            self.workspace.store.observation,
            self._active_table.capture_viewport().selected,
        )

    async def run_command(self, text: str) -> None:
        """Dispatch ``text`` through the active root or nested command-bar route.

        Completion is dispatch-only. Nested transitions, their history entries, and
        asynchronous connection or watch changes may finish later and are observed via
        visible UI state. This never waits for a network connection or a long-lived stream.
        Ignored when no screen is mounted or when a non-command modal screen is active.
        """
        if not self.screen_stack:
            return
        if isinstance(self.screen, CommandWorkspace):
            self.screen.leave_command()
            self.route_nested(self.screen, text)
            return
        if isinstance(self.screen, ModalScreen):
            return
        if self.focused is self.command_input:
            self.command_input.value = ""
            self.set_focus(self._active_table)
        self.command_routes.submit(text)

    @property
    def retained_aggregate_log_view_count(self) -> int:
        return self.operations.retained_aggregate_count

    def get_default_screen(self) -> WorkspaceScreen:
        return WorkspaceScreen(self._foreground)

    @property
    def _resource_name(self) -> str:
        return self.views.route.display_key

    @property
    def _generic_selection(self) -> ResourceSelection | None:
        route = self.views.route
        return route.selection if route.kind is ViewKind.CUSTOM else None

    @property
    def _active_table(self) -> PodTable | NamespaceTable | ContextTable | StandardTable:
        return self.views.table

    def request_render(self) -> None:
        self.views.request()

    def action_retry_view(self) -> None:
        self.views.renderer.retry()

    def _view_rendered(self, request: RenderRequest, error: Exception | None) -> None:
        if not request.current():
            return
        self.view_error.show_failure(self.views.renderer.is_failed(request))
        if error is not None:
            with suppress(AppError):
                self._diagnostic_logger.error(
                    "Resource view rendering failed.",
                    exc_info=(type(error), error, error.__traceback__),
                )

    def _update_trail(self) -> None:
        self.presenter.update_trail()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        self._update_trail()

    def _set_status(self, message: str) -> None:
        self.presenter.status(message)

    def _forward_changed(self) -> None:
        self.views.request()

    async def on_event(self, event: Event) -> None:
        await self.input_dispatch.dispatch(event, super().on_event)

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
            yield self.view_error
            yield self.resources
            yield self.namespace_table
            yield self.context_table
            yield self.standard_table
            yield self.custom_table
            with Vertical(id="empty-state"):
                yield WorkspaceLabel("No cluster connection", id="empty-title", markup=False)
                yield WorkspaceLabel(
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

    def _register_child(
        self, parent: DOMNode, child: Widget, before: int | None, after: int | None
    ) -> None:
        # Pinned Textual registration owns new widgets before their first paint.
        # Keep its validation/order and scope the cache correction to this app.
        super()._register_child(parent, child, before, after)
        child._styles_cache = ColorStylesCache()

    def on_mount(self) -> None:
        first_paint = asyncio.Event()

        async def before_connect() -> None:
            await first_paint.wait()
            if self._startup_stopped:
                raise asyncio.CancelledError

        self.sessions.before_connect = before_connect
        self.call_after_refresh(first_paint.set)
        self.set_keymap(dict(self.navigation_keymap))
        self.plugins.refresh()
        for table in (
            self.resources,
            self.standard_table,
            self.custom_table,
            self.namespace_table,
            self.context_table,
        ):
            table.effective_keys = self.navigation_keymap
        if not self.is_headless and not self.is_web:
            self._terminal_signals.install()
            if not self.navigation.mouse and self._driver is not None:
                # Own a known reporting state in this alternate screen even
                # when the caller left mouse reporting enabled. Textual skips
                # both enable and disable sequences when run(mouse=False).
                self._driver.write("\x1b[?1000l\x1b[?1003l\x1b[?1015l\x1b[?1006l")
        self.query_one("#all-namespaces").display = False
        self.resources.setup()
        self.namespace_table.setup()
        self.context_table.setup()
        self.standard_table.setup()
        self.query_one("#resource-view", Vertical).border_title = "Resources · no connection"
        self.screen.set_class(self.size.width < 70, "compact")
        self.screen.set_class(self.size.height < 16, "short")
        self.set_focus(self.resources)
        self._set_status(DISCONNECTED_STATUS)
        self.appearance_controller.attach_build_info(self.header.query_one("#build-info", Static))
        self.live_preferences.start((self.appearance_controller.warning, self._navigation_warning))
        if self._initial_command is not Command.QUIT:
            self.call_after_refresh(self.appearance_controller.start_updates)
            self.presenter.start()
            self.views.start()
            self.navigator.initialize(self._initial_command, self.command_routes.apply)
        else:
            self.exit()

    def _filter_options(self, context: str | None) -> FilterOptions:
        return FilterOptions(
            self.interactions.errors,
            self.interactions.favorites,
            dict(self.navigation.favorites).get(context or "", ()),
        )

    def _start_connection(
        self,
        context: str,
        *,
        scope: NamespaceChoice | None = None,
        remember: bool = True,
        authenticate: CredentialLogin | None = None,
    ) -> None:
        self.navigator.connect(context, scope=scope, remember=remember, authenticate=authenticate)

    def _observation_changed(self) -> None:
        self.plugins.refresh()
        self.plugins.manager.invalidate()
        self.command_input.refresh_choices()
        self.navigator.resolve_pending()
        if self._theme_context() != self.appearance_controller.applied_context:
            self._apply_theme()

    def _set_notice(self, message: str) -> None:
        self.presenter.notice(message)

    @on(PodTable.SortChanged)
    @on(StandardTable.SortChanged)
    @on(NamespaceTable.SortChanged)
    def sort_changed(self) -> None:
        self.view_preferences.remember_sort()
        self.presenter.show_sort()

    async def _close_client_operations(self, client: KubernetesSession) -> None:
        await self.operations.close_for_client(client)

    def copy_to_clipboard(self, text: str) -> None:
        backend = clipboard_backend(
            self._process_environment,
            sys.platform,
            headless=self.is_headless or not self.is_running,
        )
        data = clipboard_bytes(text, backend)
        self._clipboard = text
        if backend is ClipboardBackend.OSC52:
            if self._driver is not None:
                self._driver.write(osc52(data, tmux=bool(self._process_environment.get("TMUX"))))
        elif backend is not ClipboardBackend.MEMORY:
            self.clipboard_queue.submit(data, backend)

    def _clipboard_failed(self, data: bytes, error: AppError) -> None:
        if self._process_environment.get("KUBERICH_CLIPBOARD", "auto") == "auto":
            try:
                sequence = osc52(data, tmux=bool(self._process_environment.get("TMUX")))
                if self._driver is not None:
                    self._driver.write(sequence)
            except AppError:
                self.notify(str(error), severity="error")
        else:
            self.notify(str(error), severity="error")

    def exit(
        self,
        result: None = None,
        return_code: int = 0,
        message: RenderableType | None = None,
    ) -> None:
        self._startup_stopped = True
        self.appearance_controller.stop()
        super().exit(result=result, return_code=return_code, message=message)

    async def on_unmount(self) -> None:
        self.clipboard_queue.stop()
        self.appearance_controller.stop()
        await self.appearance_controller.close()
        try:
            await self.command_routes.close()
            await self.interactions.close()
            if self._catalog_task is not None:
                self._catalog_task.cancel()
                await finish_owned(asyncio.gather(self._catalog_task, return_exceptions=True))
            await self.clipboard_queue.close()
            await self.live_preferences.close()
            await self.plugins.close()
            await self.mutations.close()
            await self.forwards.close()
            await self.processes.close()
            await self.workspace.close()
            await self.presenter.close()
            await self.views.close()
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
        if not self.custom_table.display and self._resource_name in {"configmaps", "secrets"}:
            self.action_configuration_data()
        else:
            self._inspect("details")

    def action_configuration_data(self) -> None:
        from kuberich.services.configuration_data import ConfigurationService
        from kuberich.ui.configuration_data import ConfigurationScreen

        selection = self._capture_target()
        if selection is not None:
            client, resource, _, target, current = selection
            self.push_screen(
                ConfigurationScreen(
                    ConfigurationService(client, resource, target, self.commands.policy, current)
                )
            )

    def deliver_screenshot(
        self,
        filename: str | None = None,
        path: str | None = None,
        time_format: str | None = None,
    ) -> str | None:
        from kuberich.ui.configuration_data import ConfigurationScreen
        from kuberich.ui.plugin_screens import PluginScreen

        if any(
            isinstance(screen, (ConfigurationScreen, PluginScreen)) for screen in self.screen_stack
        ):
            self.notify(
                "Close the configuration data view or plugin input view before taking a screenshot.",
                severity="warning",
            )
            return None
        return super().deliver_screenshot(filename, path, time_format)

    def export_screenshot(self, *, title: str | None = None, simplify: bool = False) -> str:
        from kuberich.ui.configuration_data import ConfigurationScreen
        from kuberich.ui.plugin_screens import PluginScreen

        if any(
            isinstance(screen, (ConfigurationScreen, PluginScreen)) for screen in self.screen_stack
        ):
            raise AppError(
                "Close the configuration data view or plugin input view before exporting a screenshot."
            )
        return super().export_screenshot(title=title, simplify=simplify)

    def action_inspect_yaml(self) -> None:
        self._inspect("yaml")

    def action_inspect_details(self) -> None:
        self._inspect("details")

    def action_inspect_events(self) -> None:
        self._inspect("events")

    def _inspect(self, page: Page) -> None:
        self.operations.inspect(page)

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
        self.operations.port_forwards(selected)

    def action_annotate(self) -> None:
        self.operations.annotate()

    def action_writes(self) -> None:
        self.operations.writes()

    def action_resource_operation(
        self,
        action: ResourceAction,
        *,
        batch: bool = False,
        uids: tuple[str, ...] | None = None,
        labels: tuple[str, ...] | None = None,
    ) -> None:
        table = self._active_table
        visible = tuple(row.key.value for row in table.ordered_rows if row.key.value is not None)
        all_uids = tuple(key.value for key in table.rows if key.value)
        self.operations.operate(
            action,
            batch=batch,
            uids=uids,
            labels=labels,
            visible_uids=visible,
            all_uids=all_uids,
            selection=self.interactions.selection,
        )

    def action_cleanup_pods(self) -> None:
        """Review deleting the finished pods visible in the current pod view."""
        snapshot = self.workspace.store.observation.snapshot
        if self._resource_name != "pods" or self.custom_table.display or snapshot is None:
            self._set_notice("Open a connected :pods view to clean up finished pods.")
            return
        visible = {row.key.value for row in self.resources.ordered_rows}
        found = finished_pods(item for item in snapshot.items if item.uid in visible)
        if not found.candidates:
            self._set_notice("No completed or failed pods in this view.")
            return
        if found.remaining:
            self.notify(f"Showing the first {MAX_BATCH}; {found.remaining} more remain.")
        self.action_resource_operation(
            ResourceAction.DELETE,
            batch=True,
            uids=tuple(item.uid for item in found.candidates),
            labels=tuple(item.label for item in found.candidates),
        )

    def _edit_context(self, change: ContextChange, new_name: str = "") -> None:
        from kuberich.ui.context_admin import ContextEditScreen

        name = self.context_table.capture_viewport().selected
        if self._resource_name != "contexts" or name is None:
            self._set_status("Open :ctx and select a context first.")
            return
        try:
            self.commands.policy.require(Action.MUTATE)
            paths = kubeconfig_paths(self.sessions.request, self._process_environment)
        except AppError as error:
            self._set_status(str(error))
            return
        connected = self.workspace.store.observation.context
        screen = ContextEditScreen(paths, change, name, new_name=new_name, connected=connected)
        self.push_screen(screen, partial(self._context_saved, connected))

    def _context_saved(self, connected: str | None, result: ContextEditResult | None) -> None:
        if result is not None:
            self._catalog_task = asyncio.create_task(self._reload_catalog(connected, result))

    async def _reload_catalog(self, connected: str | None, result: ContextEditResult) -> None:
        plan = result.plan
        try:
            catalog = await asyncio.to_thread(
                load_catalog, self.sessions.request, self._process_environment
            )
        except AppError as error:
            self._set_status(f"Saved, but reloading contexts failed: {error}")
            return
        self.sessions.catalog = catalog
        done = "Renamed" if plan.change is ContextChange.RENAME else "Deleted"
        if plan.new_name is not None and connected == plan.name:
            self._start_connection(plan.new_name, remember=False)
        self._set_notice(f"{done} {plan.name}. Backup: {result.backup}")
        self.views.request()

    def action_workload(self, operation: WorkloadAction, argument: str = "") -> None:
        self.operations.workload(operation, argument)

    def action_edit(self) -> None:
        self.operations.edit()

    def action_port_forward(self) -> None:
        self.operations.port_forward()

    def _open_logs(self, *, containers_first: bool = False, uid: str | None = None) -> None:
        self.operations.open_logs(containers_first=containers_first, uid=uid)

    def action_logs_all(self) -> None:
        self.operations.logs_all()

    def _capture_target(self, uid: str | None = None) -> CapturedResource[KubernetesSession] | None:
        return self.targets.capture(uid)

    def _target_selection(self) -> TargetSelection:
        modal = isinstance(self.screen, ModalScreen)
        return TargetSelection(
            self.views.route,
            None
            if modal or self.views.route.kind is ViewKind.CONTEXTS
            else self.views.table.capture_viewport().selected,
            modal,
        )

    def _operation_context(self) -> OperationContext:
        return OperationContext(
            self.chrome,
            self.breadcrumbs.trail,
            self._shell,
            MappingProxyType(dict(self._process_environment)),
            self._process_directory,
            self.views.route,
            isinstance(self.screen, ModalScreen),
        )

    def _session_current(self, client: KubernetesSession, identity: SessionIdentity) -> bool:
        observed = self.sessions.observation.identity
        return (
            self.sessions.client is client
            and observed is not None
            and observed.connection_id == identity.connection_id
        )

    def _forwarding_preferences(self) -> ForwardPreferences:
        return (
            forwarding_from(self.preferences.document) if self.preferences else ForwardPreferences()
        )

    def action_contexts(self) -> None:
        self.navigator.contexts()

    @on(DataTable.RowSelected, "#contexts")
    def context_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self._resource_name == "contexts":
            self._context_selected(event.row_key.value)

    def action_connection_details(self) -> None:
        from kuberich.ui.scopes import ConnectionScreen

        if not isinstance(self.screen, ModalScreen):
            self.push_screen(ConnectionScreen(self._workspace_status()))

    def _context_selected(self, value: str | None) -> None:
        self.navigator.context_selected(value)

    def _clear_rows(self) -> None:
        self.navigator.clear_rows()

    def action_namespaces(self) -> None:
        self.navigator.namespaces()

    def _disable_namespace_favorites(self) -> None:
        self.interactions.favorites = False

    def _display_resource(
        self, resource: str, *, focus: bool = True, generic: ResourceSelection | None = None
    ) -> None:
        self.navigator.display(resource, focus=focus, generic=generic)

    def _select_resource(
        self,
        resource: str,
        *,
        restore: NavigationState | None = None,
        scope: NamespaceChoice | None = None,
        generic: ResourceSelection | None = None,
    ) -> None:
        self.navigator.select_resource(resource, restore=restore, scope=scope, generic=generic)

    def _namespace_selected(self, value: str | None) -> None:
        self.navigator.namespace_selected(value)

    def action_retry(self) -> None:
        self.navigator.retry()

    def _apply_generic(self, command: GenericResourceCommand) -> None:
        self.navigator.generic(command)

    def _refresh_discovery(self) -> None:
        self.navigator.refresh_discovery()

    def _configure_columns(self, argument: str = "") -> None:
        self.navigator.columns(argument)

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
        view = ViewState(
            self._resource_name,
            generic=self.custom_table.display,
            modal=isinstance(self.screen, ModalScreen),
            typing=isinstance(self.focused, Input),
        )
        return COMMAND_CATALOG.available(action, view)

    def action_mark_selection(self) -> None:
        self.interactions.apply(InteractionCommand("mark"))

    def action_mark_range(self, delta: int) -> None:
        if self.interactions.selection.anchor is None:
            self.action_mark_selection()
        table = self._active_table
        table.move_cursor(row=table.cursor_row + delta)
        self.interactions.apply(InteractionCommand("range"))

    def action_copy_selection(self) -> None:
        self.interactions.apply(InteractionCommand("copy"))

    def action_focus_filter(self) -> None:
        self.set_focus(self.filter_input)

    def action_focus_command(self) -> None:
        # Apply focus before the next queued key, including rapidly typed commands.
        self.set_focus(self.command_input)

    def action_show_help(self) -> None:
        from kuberich.ui.help import HelpScreen

        if not isinstance(self.screen, ModalScreen):
            aliases = "Aliases: " + ", ".join(
                f":{name} → {target}" for name, target in self.navigation.aliases
            )
            aliases += "\nPlugins: :plugins · :plugin NAME · :pluginjobs\n" + "\n".join(
                f"{key} → plugin {name} (overrides its resource action when configured)"
                for key, name in self.plugins.bindings()
            )
            self.push_screen(
                HelpScreen(
                    navigation_help(self.navigation_keymap, self.header.binding_profile),
                    aliases,
                    COMMAND_CATALOG.help_rows(),
                )
            )

    def action_navigation_help(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.action_show_help()
        else:
            profile = getattr(self.focused, "BINDING_PROFILE", "table")
            self.push_screen(NavigationHelpScreen(self.navigation_keymap, profile))

    def action_review_delete(self) -> None:
        self.action_resource_operation(ResourceAction.DELETE)

    def action_views(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.view_preferences.open()

    async def action_back(self) -> None:
        from kuberich.ui.appearance import ThemeScreen
        from kuberich.ui.editing import EditingScreen
        from kuberich.ui.inspection import InspectionScreen
        from kuberich.ui.logs import LogScreen
        from kuberich.ui.mutations import AnnotationScreen
        from kuberich.ui.operations import ResourceOperationScreen
        from kuberich.ui.transfers import TransferScreen
        from kuberich.ui.workloads import WorkloadScreen

        if isinstance(self.screen, CommandWorkspace) and self.screen.leave_command():
            return
        if isinstance(self.screen, (InspectionScreen, LogScreen, ThemeScreen, ViewScreen)):
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
        else:
            self.navigator.back()

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self.views.request()
        self._update_trail()

    @on(Input.Submitted, "#command")
    def command_submitted(self, event: Input.Submitted) -> None:
        self.command_routes.submit(event.value)

    def route_nested(self, origin: CommandWorkspace, value: str) -> None:
        self.command_routes.route(origin, value)

    @on(Input.Changed, "#command")
    def command_changed(self) -> None:
        self.command_input.refresh_choices()

    def _capture_view(self) -> NavigationState | None:
        return self.navigator.capture()

    def _remember_view(self) -> None:
        self.navigator.remember()

    def _navigate_history(self, *, forward: bool = False) -> None:
        self.navigator.move(forward=forward)

    def _restore_navigation(self, state: NavigationState) -> None:
        self.navigator.restore(state)

    def action_history_back(self) -> None:
        self.navigator.history_back()

    def action_history_forward(self) -> None:
        self.navigator.history_forward()

    def _handle_exception(self, error: Exception) -> None:
        """Narrow Textual 8.x boundary: log safely while preserving its cleanup/testing."""
        self.input_dispatch.release_pending()
        with suppress(AppError):
            self._diagnostic_logger.error(
                "Terminal interface failed.", exc_info=(type(error), error, error.__traceback__)
            )
        super()._handle_exception(error)

    def _print_error_renderables(self) -> None:
        # Textual's default prints exception values/source/locals after restoring the TTY.
        # The launcher emits an owned safe message; tests verify this boundary in a PTY.
        self._exit_renderables.clear()
