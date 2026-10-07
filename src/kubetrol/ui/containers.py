"""Pod/container drill-down retains the captured target and the parent viewport."""

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import ScreenResume
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from kubetrol.domain.containers import CONTAINER_COLUMNS, container_rows
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.logs import LogStream
from kubetrol.services.processes import ProcessRunner
from kubetrol.services.shell import ShellService
from kubetrol.ui.chrome import (
    CONTAINER_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kubetrol.ui.logs import LogScreen
from kubetrol.ui.terminal import ShellScreen


class ContainerTable(DataTable[Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "First", show=False),
        Binding("G", "scroll_bottom", "Last", show=False),
    ]


class ContainerScreen(ModalScreen[None]):
    AUTO_FOCUS = "#containers"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("l", "logs", "Logs"),
        Binding("s", "shell", "Shell"),
        Binding("x", "shell", "Shell", show=False),
    ]
    DEFAULT_CSS = """
    ContainerScreen { layout: vertical; background: $background; }
    #container-title, #container-hints, #container-status { height: 1; text-overflow: ellipsis; }
    #container-title { color: $accent; height: 3; border: solid $primary; }
    ContainerScreen.short #container-title { height: 1; border-top: none; border-bottom: none; }
    #container-feedback { height: auto; min-height: 1; max-height: 3; }
    ContainerScreen.short #container-feedback { max-height: 1; }
    #container-status { height: auto; text-overflow: fold; }
    #containers { height: 1fr; }
    #container-hints { width: 1fr; }
    #container-back { width: 14; min-width: 14; height: 1; border: none; }
    #workspace-status { height: 1; margin: 0 1; }
    """

    def __init__(
        self,
        stream: LogStream,
        manifest: dict[str, Any],
        *,
        shell: ShellService | None = None,
        processes: ProcessRunner | None = None,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = ("pods",),
    ) -> None:
        super().__init__()
        self.stream = stream
        self.shell, self.processes = shell, processes
        self.chrome, self.trail = chrome, (*trail, "containers")
        self.rows = container_rows(manifest)
        self.names = tuple(row.name for row in self.rows)
        if not self.names:
            raise AppError("The selected pod has no regular/init containers.")
        self.table = ContainerTable(id="containers", cursor_type="row", zebra_stripes=True)
        self.status = Static(
            "Pod snapshot · CPU/MEM are requests/limits; live usage is not collected.",
            markup=False,
            id="container-status",
        )

    def compose(self) -> ComposeResult:
        target = self.stream.target
        if self.chrome is not None:
            yield WorkspaceHeader(self.chrome, CONTAINER_SHORTCUTS)
        with WorkspaceBars():
            yield Static(
                safe_text(
                    f"Containers · {target.namespace}/{target.name} · {target.session.context}"
                ),
                id="container-title",
            )
            with Horizontal():
                yield Static(
                    "Enter/l logs · s shell · Esc pods"
                    if self.shell is not None
                    else "Enter/l logs · j/k ↑/↓ · g/G first/last · Esc pods",
                    markup=False,
                    id="container-hints",
                )
                yield Button("Back to pods", id="container-back", compact=True)
        with WorkspaceFrame(id="container-dialog"):
            yield self.table
            with VerticalScroll(id="container-feedback"):
                yield self.status
        yield Breadcrumbs(
            self.trail,
            "Pods",
            visible=self.chrome is None or not self.chrome.presentation.crumbsless,
        )
        yield Static("", id="workspace-status", markup=False)

    def on_mount(self) -> None:
        target = self.stream.target
        self.query_one("#container-dialog", Vertical).border_title = safe_text(
            f"containers({target.namespace}/{target.name})[{len(self.names)}]"
        )
        self.table.add_columns(*CONTAINER_COLUMNS)
        for row in self.rows:
            self.table.add_row(*(safe_text(cell) for cell in row.cells()), key=row.name)
        self.validate_target()

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.validate_target()

    def validate_target(self) -> None:
        try:
            self.stream.require_current()
        except AppError as error:
            self.table.disabled = True
            self.status.update(safe_text(str(error)))

    @on(DataTable.RowSelected, "#containers")
    def selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self._open(self.names[event.cursor_row])

    def action_logs(self) -> None:
        self._open(self.names[self.table.cursor_row])

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "shell":
            return self.shell is not None and self.processes is not None
        return True

    def action_shell(self) -> None:
        if self.app.screen is not self:
            return
        if self.shell is None or self.processes is None:
            return
        try:
            request = self.shell.capture(self.names[self.table.cursor_row])
        except AppError as error:
            self.status.update(safe_text(str(error)))
            return

        def returned(message: str | None) -> None:
            self.validate_target()
            self.status.update(safe_text(message or "Shell closed."))

        self.app.push_screen(ShellScreen(self.shell, self.processes, request), returned)

    def _open(self, name: str) -> None:
        if self.app.screen is not self:
            return
        try:
            self.stream.require_current()
        except AppError as error:
            self.validate_target()
            self.status.update(safe_text(str(error)))
            return
        self.app.push_screen(
            LogScreen(self.stream, self.names, selected=name, chrome=self.chrome, trail=self.trail)
        )

    @on(Button.Pressed, "#container-back")
    def back(self) -> None:
        self.dismiss()
