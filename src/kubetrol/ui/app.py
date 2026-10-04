"""A responsive, disconnected workspace ready for real resource services."""

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

from kubetrol.config.schema import Settings
from kubetrol.errors import AppError

DISCONNECTED_STATUS = "Disconnected · No resource data"


class HelpScreen(ModalScreen[None]):
    """Scrollable help keeps its close control accessible in small terminals."""

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Keyboard help", id="help-title", markup=False)
            with VerticalScroll(id="help-scroll"):
                yield Static(
                    Text(
                        "/                 Focus filter\n"
                        ":                 Focus command\n"
                        "? or F1           Open help\n"
                        "Tab / Shift+Tab   Move focus\n"
                        "Escape            Back / leave input\n"
                        "Escape in table   Clear active filter\n"
                        "q / Ctrl+Q        Quit (q outside inputs)\n"
                        "Ctrl+C            Quit\n\n"
                        "Commands: help, quit (Enter to submit).\n\n"
                        "This preview has no cluster connection. Context selection, "
                        "live resources, logs and shell are upcoming."
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
        Binding("escape", "back", "Back", show=False, priority=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        super().__init__()
        self.title = "Kubetrol"
        self.sub_title = "Local preview"
        self._diagnostic_logger = logger
        if settings.theme not in self.available_themes:
            raise AppError("Selected theme is unavailable; choose a built-in Textual theme.")
        self.theme = settings.theme
        self._mode = "Read-only preference" if settings.read_only else "Local preview"
        self.resources = DataTable[Text](id="resources", cursor_type="row", zebra_stripes=True)
        self.filter_input = Input(
            placeholder="Filter resources", id="filter", compact=True, max_length=256
        )
        self.command_input = Input(
            placeholder="help / quit", id="command", compact=True, max_length=256
        )
        self.status = Static(DISCONNECTED_STATUS, id="status", markup=False)

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
        self.resources.add_columns("NAMESPACE", "NAME", "READY", "STATUS", "AGE")
        self.query_one("#resource-view", Vertical).border_title = "Resources · no connection"
        self.screen.set_class(self.size.width < 70, "compact")
        self.screen.set_class(self.size.height < 16, "short")
        self.set_focus(self.resources)

    def on_resize(self, event: Resize) -> None:
        self.screen_stack[0].set_class(event.size.width < 70, "compact")
        self.screen_stack[0].set_class(event.size.height < 16, "short")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"focus_filter", "focus_command"}:
            return not isinstance(self.screen, HelpScreen) and not isinstance(self.focused, Input)
        return True

    def action_focus_filter(self) -> None:
        self.set_focus(self.filter_input)

    def action_focus_command(self) -> None:
        # Apply focus before the next queued key, including rapidly typed commands.
        self.set_focus(self.command_input)

    def action_show_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    async def action_back(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.screen.dismiss()
        elif isinstance(self.focused, Input):
            self.command_input.value = ""
            self.set_focus(self.resources)
        else:
            self.filter_input.value = ""
            self.status.update(DISCONNECTED_STATUS)

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        self.status.update(
            "Filter active · No resources while disconnected"
            if event.value
            else DISCONNECTED_STATUS
        )

    @on(Input.Submitted, "#filter")
    def filter_submitted(self) -> None:
        self.set_focus(self.resources)

    @on(Input.Submitted, "#command")
    def command_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip().removeprefix(":").lower()
        self.command_input.value = ""
        self.set_focus(self.resources)
        if command in {"help", "?"}:
            self.action_show_help()
        elif command in {"quit", "q", "exit"}:
            self.exit()
        elif command:
            self.status.update("Command unavailable in this preview. Use help or quit.")
        else:
            self.status.update(DISCONNECTED_STATUS)

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
