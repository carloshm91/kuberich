"""Pod/container drill-down retains the captured target and the parent viewport."""

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.events import ScreenResume
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from kubetrol.domain.logs import log_containers
from kubetrol.domain.resources import resource_object
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.logs import LogStream
from kubetrol.services.processes import ProcessRunner
from kubetrol.services.shell import ShellService
from kubetrol.ui.chrome import CONTAINER_SHORTCUTS, Breadcrumbs, WorkspaceChrome, WorkspaceHeader
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
    #container-dialog { width: 100%; height: 1fr; min-height: 3; border: solid $primary; border-title-align: center; }
    #container-title, #container-hints, #container-status { height: 1; text-overflow: ellipsis; }
    #container-title { color: $accent; }
    #container-feedback { height: 1; }
    #container-status { height: auto; text-overflow: fold; }
    #containers { height: 1fr; }
    #container-back { height: 1; border: none; }
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
        self.names = log_containers(manifest)
        if not self.names:
            raise AppError("The selected pod has no regular/init containers.")
        spec = resource_object(manifest.get("spec"))
        # log_containers already validates these bounded lists and unique names.
        self.kinds = {
            value["name"]: "Sidecar" if value.get("restartPolicy") == "Always" else "Init"
            for value in spec.get("initContainers") or []
        }
        self.table = ContainerTable(id="containers", cursor_type="row", zebra_stripes=True)
        self.status = Static(
            "Container names from the selected pod snapshot.", markup=False, id="container-status"
        )

    def compose(self) -> ComposeResult:
        target = self.stream.target
        if self.chrome is not None:
            yield WorkspaceHeader(self.chrome, CONTAINER_SHORTCUTS)
        with Vertical(id="container-dialog"):
            yield Static(
                safe_text(
                    f"Containers · {target.namespace}/{target.name} · {target.session.context}"
                ),
                id="container-title",
            )
            yield Static(
                "Enter/l logs · s shell · Esc pods"
                if self.shell is not None
                else "Enter/l logs · j/k ↑/↓ · g/G first/last · Esc pods",
                markup=False,
                id="container-hints",
            )
            yield self.table
            with VerticalScroll(id="container-feedback"):
                yield self.status
            yield Button("Back to pods", id="container-back", compact=True)
        yield Breadcrumbs(
            self.trail,
            "Pods",
            visible=self.chrome is None or not self.chrome.presentation.crumbsless,
        )

    def on_mount(self) -> None:
        target = self.stream.target
        self.query_one("#container-dialog", Vertical).border_title = safe_text(
            f"containers({target.namespace}/{target.name})[{len(self.names)}]"
        )
        self.table.add_columns("Container", "Type")
        for name in self.names:
            self.table.add_row(safe_text(name), safe_text(self.kinds.get(name, "App")), key=name)
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
