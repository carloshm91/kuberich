"""Explicit forward intent and a shared-frame list of app-owned TCP sessions."""

from collections.abc import Callable
from dataclasses import replace
from typing import ClassVar
from uuid import UUID

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Static

from kubetrol.domain.port_forwards import ForwardState, parse_mappings
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.port_forwards import ForwardInfo, ForwardManager, ForwardService
from kubetrol.ui.chrome import (
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)


class ForwardInput(Input):
    """Apply editing/submit bindings before the next queued printable key."""

    BINDINGS: ClassVar[list[BindingType]] = [
        replace(binding, priority=True) for binding in Binding.make_bindings(Input.BINDINGS)
    ]


class ForwardPrompt(ModalScreen[UUID | None]):
    AUTO_FOCUS = "#forward-mappings"
    DEFAULT_CSS = """
    ForwardPrompt { align: center middle; background: $background 80%; }
    #forward-form { width: 90%; max-width: 90; height: 85%; max-height: 24;
        border: round $primary; padding: 0 1; background: $surface; }
    #forward-target { height: 1; text-overflow: ellipsis; }
    #forward-fields { height: 1fr; }
    #forward-fields Static { height: auto; }
    #forward-feedback { height: auto; max-height: 2; }
    #forward-buttons { height: 1; }
    #forward-buttons Button { height: 1; border: none; min-width: 10; }
    """

    def __init__(
        self,
        manager: ForwardManager,
        source: ForwardService,
        current: Callable[[], bool],
        *,
        initial: str = "0:8080",
    ) -> None:
        super().__init__()
        self.manager, self.source, self.current, self.initial = manager, source, current, initial

    def compose(self) -> ComposeResult:
        target = self.source.target
        with Vertical(id="forward-form"):
            yield Static(
                safe_text(f"Forward · {target.namespace}/{target.name}"), id="forward-target"
            )
            with VerticalScroll(id="forward-fields"):
                yield Static("TCP mappings (comma-separated local:remote)", markup=False)
                yield ForwardInput(
                    self.initial, id="forward-mappings", select_on_focus=False, max_length=256
                )
                yield Static(
                    "Local 0 chooses an available port. Context changes stop the forward.",
                    markup=False,
                )
                yield Static("Bind address", markup=False)
                yield ForwardInput(
                    "127.0.0.1", id="forward-address", select_on_focus=False, max_length=64
                )
                yield Checkbox("Allow connections from other hosts", id="forward-remote")
            yield Static("", id="forward-feedback", markup=False)
            with Horizontal(id="forward-buttons"):
                yield Button("Start", id="forward-start", variant="primary", compact=True)
                yield Button("Cancel", id="forward-cancel", compact=True)

    @on(Button.Pressed, "#forward-start")
    @on(Input.Submitted)
    def start(self) -> None:
        try:
            if not self.current():
                raise AppError("The selected target changed. Select the resource again.")
            identity = self.manager.start(
                self.source,
                parse_mappings(self.query_one("#forward-mappings", Input).value),
                self.query_one("#forward-address", Input).value,
                allow_remote=self.query_one("#forward-remote", Checkbox).value,
            )
        except AppError as error:
            self.query_one("#forward-feedback", Static).update(safe_text(str(error)))
        else:
            self.dismiss(identity)

    @on(Button.Pressed, "#forward-cancel")
    def cancel(self) -> None:
        self.dismiss()


class ForwardTable(DataTable[Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "First", show=False),
        Binding("G", "scroll_bottom", "Last", show=False),
    ]


SHORTCUTS = (
    ("s / Stop", "Stop selected"),
    ("/", "Filter"),
    ("j/k", "Down / up"),
    ("g/G", "First / last"),
    ("Esc", "Previous view"),
)


class ForwardScreen(ModalScreen[None]):
    AUTO_FOCUS = "#forward-sessions"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("s", "stop_selected", "Stop", show=False),
        Binding("slash", "filter", "Filter", show=False),
    ]
    DEFAULT_CSS = """
    ForwardScreen { layout: vertical; background: $background; }
    #forward-list-title { height: 1; }
    #forward-list-filter { height: 1; border: none; }
    #forward-list-buttons { height: 1; }
    #forward-list-buttons Button { height: 1; border: none; min-width: 12; }
    #forward-sessions { height: 1fr; }
    #forward-list-status { height: auto; max-height: 2; margin: 0 1; }
    ForwardScreen.short #forward-list-status { height: 1; text-overflow: ellipsis; }
    """

    def __init__(
        self,
        manager: ForwardManager,
        chrome: WorkspaceChrome,
        trail: tuple[str, ...],
        *,
        selected: UUID | None = None,
    ) -> None:
        super().__init__()
        self.manager, self.chrome, self.trail = manager, chrome, trail
        self.initial_selection = selected
        self.table = ForwardTable(id="forward-sessions", cursor_type="row", zebra_stripes=True)
        self._shown: dict[str, ForwardInfo] = {}

    def compose(self) -> ComposeResult:
        yield WorkspaceHeader(self.chrome, SHORTCUTS)
        with WorkspaceBars():
            yield Static(
                "Port forwards · changing context stops active sessions",
                id="forward-list-title",
                markup=False,
            )
            yield Input(placeholder="/ Filter sessions", id="forward-list-filter")
            with Horizontal(id="forward-list-buttons"):
                yield Button("Stop selected", id="forward-list-stop", compact=True)
                yield Button("Back", id="forward-list-back", compact=True)
        with WorkspaceFrame(id="forward-list-frame"):
            yield self.table
        yield Breadcrumbs(
            (*self.trail, "port-forwards"),
            self.trail[-1].title(),
            visible=not self.chrome.presentation.crumbsless,
        )
        yield Static("", id="forward-list-status", markup=False)

    def on_mount(self) -> None:
        self.table.add_columns(
            "CONTEXT", "NAMESPACE", "RESOURCE", "BIND", "REQUESTED", "BOUND (LAST)", "STATE"
        )
        self.refresh_sessions()
        if self.initial_selection is not None and str(self.initial_selection) in self._shown:
            self.table.move_cursor(row=self.table.get_row_index(str(self.initial_selection)))
            self.show_selection()
        self.set_interval(0.15, self.refresh_sessions)

    def _cells(self, info: ForwardInfo) -> tuple[Text, ...]:
        return tuple(
            safe_text(value)
            for value in (
                info.target.session.context,
                info.target.namespace or "",
                f"{info.target.resource}/{info.target.name}",
                info.address,
                ",".join(mapping.argument for mapping in info.mappings),
                ",".join(f"{port.local}->{port.remote}" for port in info.ports) or "—",
                info.state.name,
            )
        )

    def refresh_sessions(self) -> None:
        selected = (
            self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
            if self.table.row_count
            else None
        )
        index = self.table.cursor_row
        query = self.query_one("#forward-list-filter", Input).value.casefold()
        incoming = {
            str(info.identity): info
            for info in self.manager.infos
            if query in " ".join(cell.plain for cell in self._cells(info)).casefold()
        }
        if incoming == self._shown:
            self.show_selection()
            return
        x, y = self.table.scroll_x, self.table.scroll_y
        top = (
            self.table.coordinate_to_cell_key(
                Coordinate(min(int(y), self.table.row_count - 1), 0)
            ).row_key.value
            if self.table.row_count
            else None
        )
        for identity in self._shown.keys() - incoming.keys():
            self.table.remove_row(identity)
        for identity, info in incoming.items():
            if identity not in self._shown:
                self.table.add_row(*self._cells(info), key=identity)
            elif info != self._shown[identity]:
                for column, cell in zip(self.table.columns, self._cells(info), strict=True):
                    self.table.update_cell(identity, column, cell, update_width=True)
        self._shown = incoming
        if self.table.row_count:
            self.table.move_cursor(
                row=self.table.get_row_index(selected)
                if selected in incoming
                else min(index, self.table.row_count - 1),
                scroll=False,
            )
        self.show_selection()
        # Layout and cursor watchers can scroll after a row patch. Restore only
        # while the operator's selection and this patch are still current.
        selection = self.table.cursor_coordinate

        def restore() -> None:
            if self._shown == incoming and self.table.cursor_coordinate == selection:
                destination = self.table.get_row_index(top) + y % 1 if top in incoming else y
                self.table.scroll_to(x, destination, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    @on(Input.Changed, "#forward-list-filter")
    def changed_filter(self) -> None:
        self.refresh_sessions()

    @on(Input.Submitted, "#forward-list-filter")
    def finish_filter(self) -> None:
        self.set_focus(self.table)

    @on(DataTable.RowHighlighted, "#forward-sessions")
    def show_selection(self) -> None:
        identity = (
            self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
            if self.table.row_count
            else None
        )
        info = self._shown.get(identity or "")
        self.query_one("#forward-list-status", Static).update(
            safe_text(
                info.message
                if info
                else "No matching sessions. F on a pod or Service starts a forward."
            )
        )
        self.query_one("#forward-list-stop", Button).disabled = info is None or info.state in {
            ForwardState.STOPPED,
            ForwardState.FAILED,
        }

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not isinstance(self.focused, Input) if action == "stop_selected" else True

    def action_filter(self) -> None:
        self.set_focus(self.query_one("#forward-list-filter", Input))

    @on(Button.Pressed, "#forward-list-stop")
    def action_stop_selected(self) -> None:
        if self.table.row_count:
            identity = self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
            if identity is not None:
                self.run_worker(self.stop(UUID(identity)), group="forward-stop")

    async def stop(self, identity: UUID) -> None:
        await self.manager.stop(identity)
        if self.is_attached and self.is_running:
            self.refresh_sessions()

    @on(Button.Pressed, "#forward-list-back")
    def back(self) -> None:
        self.dismiss()
