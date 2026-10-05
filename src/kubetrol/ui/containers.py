"""Pod/container drill-down retains the captured target and the parent viewport."""

from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.events import ScreenResume
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from kubetrol.domain.logs import log_containers
from kubetrol.domain.resources import resource_object
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.logs import LogStream
from kubetrol.ui.logs import LogScreen


class ContainerTable(DataTable[Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "First", show=False),
        Binding("G", "scroll_bottom", "Last", show=False),
    ]


class ContainerScreen(ModalScreen[None]):
    AUTO_FOCUS = "#containers"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("l", "logs", "Logs")]
    DEFAULT_CSS = """
    ContainerScreen { align: center middle; background: $background 80%; }
    #container-dialog { width: 96%; height: 96%; border: round $primary; }
    #container-title, #container-hints, #container-status { height: 1; text-overflow: ellipsis; }
    #container-title { color: $accent; }
    #containers { height: 1fr; }
    #container-back { height: 1; border: none; }
    """

    def __init__(self, stream: LogStream, manifest: dict[str, Any]) -> None:
        super().__init__()
        self.stream = stream
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
        with Vertical(id="container-dialog"):
            yield Static(
                safe_text(
                    f"Containers · {target.namespace}/{target.name} · {target.session.context}"
                ),
                id="container-title",
            )
            yield Static(
                "Enter/l logs · j/k ↑/↓ · g/G first/last · Esc pods",
                markup=False,
                id="container-hints",
            )
            yield self.table
            yield self.status
            yield Button("Back to pods", id="container-back", compact=True)

    def on_mount(self) -> None:
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

    def _open(self, name: str) -> None:
        if self.app.screen is not self:
            return
        try:
            self.stream.require_current()
        except AppError as error:
            self.validate_target()
            self.status.update(safe_text(str(error)))
            return
        self.app.push_screen(LogScreen(self.stream, self.names, selected=name))

    @on(Button.Pressed, "#container-back")
    def back(self) -> None:
        self.dismiss()
