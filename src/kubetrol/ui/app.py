"""A responsive, disconnected workspace ready for real resource services."""

import asyncio
import logging
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Static

from kubetrol.config.catalog import KubeCatalog
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import (
    DEFAULT_CONNECTION,
    ConnectionRequest,
    ConnectionState,
    SessionObservation,
)
from kubetrol.errors import AppError
from kubetrol.security.arguments import validate_argument
from kubetrol.security.presentation import safe_text
from kubetrol.services.access import AccessPolicy
from kubetrol.services.commands import Command, CommandService
from kubetrol.services.sessions import SessionService
from kubetrol.ui.presentation import DEFAULT_PRESENTATION, Presentation
from kubetrol.ui.scopes import ConnectionScreen, ScopeScreen

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
                        "F2 / F3           Contexts / namespaces\n"
                        "F4                Retry connection\n"
                        "F5                Full connection status\n"
                        "PageUp / PageDown Scroll help\n"
                        "Tab / Shift+Tab   Move focus\n"
                        "Escape            Back / leave input\n"
                        "Escape in table   Clear active filter\n"
                        "q / Ctrl+Q        Quit (q outside inputs)\n"
                        "Ctrl+C            Quit\n\n"
                        "Commands: help, quit, ctx [NAME], ns [NAME or *].\n\n"
                        "Context sessions and namespace discovery are available. "
                        "Live resources, logs and shell are upcoming."
                    ),
                    id="help-content",
                )
            yield Button("Back", id="close-help", variant="primary", compact=True)

    @on(Button.Pressed, "#close-help")
    def close_help(self) -> None:
        self.dismiss()


class KubetrolApp(App[None]):
    """Keyboard and mouse workspace; startup does not load Kubernetes credentials."""

    CSS_PATH = Path(__file__).with_name("kubetrol.tcss")
    ENABLE_COMMAND_PALETTE = False
    AUTO_FOCUS = "#resources"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("slash", "focus_filter", "Filter", key_display="/", priority=True),
        Binding("colon", "focus_command", "Cmd", key_display=":", priority=True),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("f1", "show_help", "Help", show=False, priority=True),
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
        initial_command: Command = Command.EMPTY,
        catalog: KubeCatalog | None = None,
        connection: ConnectionRequest = DEFAULT_CONNECTION,
    ) -> None:
        super().__init__()
        self.title = "Kubetrol"
        self.sub_title = "Local preview"
        self._diagnostic_logger = logger
        self._presentation = presentation
        self._initial_command = initial_command
        self.sessions = SessionService(
            catalog if catalog is not None else KubeCatalog(), connection
        )
        self._connection_task: asyncio.Task[None] | None = None
        self._connection_attempt = 0
        self.commands = CommandService(AccessPolicy(settings.read_only))
        if settings.theme not in self.available_themes:
            raise AppError("Selected theme is unavailable; choose a built-in Textual theme.")
        self.theme = settings.theme
        self._mode = "Read-only" if settings.read_only else "Local preview"
        self.resources = DataTable[Text](id="resources", cursor_type="row", zebra_stripes=True)
        self.filter_input = Input(
            placeholder="Filter resources", id="filter", compact=True, max_length=256
        )
        self.command_input = Input(
            placeholder="help / ctx / ns / quit", id="command", compact=True, max_length=256
        )
        self.status = Static(DISCONNECTED_STATUS, id="status", markup=False)

    def _set_status(self, message: str) -> None:
        prefix = "Read-only · " if self.commands.policy.read_only else ""
        insecure = "Insecure transport · " if self.sessions.observation.insecure else ""
        self.status.update(safe_text(prefix + insecure + message))

    def _workspace_status(self) -> str:
        return (
            self.sessions.observation.message
            if self.sessions.observation.identity is not None
            else DISCONNECTED_STATUS
        )

    def compose(self) -> ComposeResult:
        with Horizontal(id="app-header"):
            yield Static("kubetrol", id="brand", markup=False)
            yield Static(f"{version('kubetrol')} · {self._mode}", id="build-info", markup=False)
        with Horizontal(id="scope-bar"):
            yield Static("Context: —", id="context", markup=False)
            yield Static("Namespace: —", id="namespace", markup=False)
            yield Static("Disconnected", id="connection", markup=False)
        with Vertical(id="resource-view"):
            yield self.resources
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
        with Horizontal(id="filter-bar", classes="input-bar"):
            yield Static("/", classes="input-label", markup=False)
            yield self.filter_input
        with Horizontal(id="command-bar", classes="input-bar"):
            yield Static(":", classes="input-label", markup=False)
            yield self.command_input
        yield self.status
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#app-header").display = not self._presentation.headless
        self.query_one("#brand").display = not self._presentation.logoless
        self.query_one("#scope-bar").display = not self._presentation.crumbsless
        self.resources.add_columns("NAMESPACE", "NAME", "READY", "STATUS", "AGE")
        self.query_one("#resource-view", Vertical).border_title = "Resources · no connection"
        self.screen.set_class(self.size.width < 70, "compact")
        self.screen.set_class(self.size.height < 16, "short")
        self.set_focus(self.resources)
        self._set_status(DISCONNECTED_STATUS)
        self._apply_command(self._initial_command)
        if self._initial_command is not Command.QUIT:
            context = self.sessions.request.context or self.sessions.catalog.current
            if context is not None:
                self._start_connection(context)

    def _start_connection(self, context: str) -> None:
        try:
            validate_argument(context)
        except AppError as error:
            self._set_status(str(error))
            return
        previous = self._connection_task
        if previous is not None:
            previous.cancel()
        self._connection_attempt += 1
        attempt = self._connection_attempt
        self.query_one("#context", Static).update(safe_text(f"Context: {context}"))
        self.query_one("#namespace", Static).update("Namespace: —")
        self.query_one("#connection", Static).update("Connecting")
        self._set_status("Connecting · F2 contexts · F4 retry · Ctrl+Q quit")
        self._connection_task = asyncio.create_task(self._connect(context, previous, attempt))

    async def _connect(
        self, context: str, previous: asyncio.Task[None] | None, attempt: int
    ) -> None:
        if previous is not None:
            await asyncio.gather(previous, return_exceptions=True)
        try:
            observation = await self.sessions.connect(context)
            if attempt == self._connection_attempt and self.is_running:
                self._show_connection(observation)
        except Exception as error:
            self._handle_exception(error)

    def _show_connection(self, observation: SessionObservation) -> None:
        identity = observation.identity
        self.query_one("#context", Static).update(
            safe_text(f"Context: {identity.context if identity else '—'}")
        )
        self.query_one("#namespace", Static).update(
            safe_text(f"Namespace: {observation.namespace or 'All'}")
        )
        state = observation.state.name.replace("_", " ").title()
        self.query_one("#connection", Static).update(state)
        usable = observation.state in {ConnectionState.CONNECTED, ConnectionState.LIMITED}
        self.query_one("#empty-title", Static).update(
            "Session connected" if usable else "Connection unavailable"
        )
        self.query_one("#empty-description", Static).update(
            "Live resource views are upcoming."
            if usable
            else "Check the connection status below; F2 contexts · F4 retry."
        )
        self.query_one("#resource-view", Vertical).border_title = "Resources · " + state.lower()
        self._set_status(observation.message)

    async def on_unmount(self) -> None:
        self._connection_attempt += 1
        if self._connection_task is not None:
            self._connection_task.cancel()
            await asyncio.gather(self._connection_task, return_exceptions=True)
        await self.sessions.close()

    def action_contexts(self) -> None:
        if not self.sessions.catalog.names:
            self._set_status("No contexts found. Configure KUBECONFIG or use --kubeconfig.")
        elif not isinstance(self.screen, ModalScreen):
            self.push_screen(
                ScopeScreen("Choose context", self.sessions.catalog.names), self._context_selected
            )

    def action_connection_details(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(ConnectionScreen(self._workspace_status()))

    def _context_selected(self, value: str | None) -> None:
        if value is not None:
            self._start_connection(value)

    def action_namespaces(self) -> None:
        if self.sessions.observation.state not in {
            ConnectionState.CONNECTED,
            ConnectionState.LIMITED,
        }:
            self._set_status("Connect to a context before selecting a namespace.")
        elif not isinstance(self.screen, ModalScreen):
            values = tuple(
                sorted(
                    set(self.sessions.observation.namespaces)
                    | {self.sessions.observation.namespace or "default"}
                )
            )
            self.push_screen(
                ScopeScreen("Choose namespace (* = All)", ("*", *values)), self._namespace_selected
            )

    def _namespace_selected(self, value: str | None) -> None:
        if value is not None:
            try:
                self._show_connection(
                    self.sessions.select_namespace(None if value == "*" else value)
                )
            except AppError as error:
                self._set_status(str(error))

    def action_retry(self) -> None:
        context = (
            self.sessions.observation.identity.context
            if self.sessions.observation.identity
            else self.sessions.request.context or self.sessions.catalog.current
        )
        if context is not None:
            self._start_connection(context)
        else:
            self.action_contexts()

    def on_resize(self, event: Resize) -> None:
        self.screen_stack[0].set_class(event.size.width < 70, "compact")
        self.screen_stack[0].set_class(event.size.height < 16, "short")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"focus_filter", "focus_command"}:
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
        if isinstance(self.screen, ModalScreen):
            self.screen.dismiss()
        elif isinstance(self.focused, Input):
            self.command_input.value = ""
            self.set_focus(self.resources)
        else:
            self.filter_input.value = ""
            self._set_status(self._workspace_status())

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self._set_status(
            "Filter active · Resource views are upcoming"
            if event.value
            else self._workspace_status()
        )

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.set_focus(self.resources)

    @on(Input.Submitted, "#command")
    def command_submitted(self, event: Input.Submitted) -> None:
        self.command_input.value = ""
        self.set_focus(self.resources)
        verb, _, value = event.value.strip().removeprefix(":").strip().partition(" ")
        if verb.lower() in {"ctx", "context", "ns", "namespace"}:
            if verb.lower() in {"ctx", "context"}:
                self._start_connection(value.strip()) if value.strip() else self.action_contexts()
            elif value.strip():
                self._namespace_selected(value.strip())
            else:
                self.action_namespaces()
            return
        try:
            command = self.commands.resolve(event.value)
        except AppError as error:
            self._set_status(str(error))
            return
        self._apply_command(command)

    def _apply_command(self, command: Command) -> None:
        if command is Command.HELP:
            self.action_show_help()
        elif command is Command.QUIT:
            self.exit()
        elif command is Command.UNAVAILABLE:
            self._set_status("Command unavailable in this preview. Use help or quit.")
        else:
            self._set_status(self._workspace_status())

    def _handle_exception(self, error: Exception) -> None:
        """Narrow Textual 8.x boundary: log safely while preserving its cleanup/testing."""
        with suppress(AppError):
            self._diagnostic_logger.error(
                "Terminal interface failed.", exc_info=(type(error), error, error.__traceback__)
            )
        super()._handle_exception(error)

    def _print_error_renderables(self) -> None:
        # Textual's default prints exception values/source/locals after restoring the TTY.
        # The launcher emits an owned safe message; tests verify this boundary in a PTY.
        self._exit_renderables.clear()
