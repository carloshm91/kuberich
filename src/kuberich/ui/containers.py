"""Pod/container drill-down retains the captured target and the parent viewport."""

import asyncio
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import ScreenResume
from textual.widgets import Button, DataTable, Input, Static

from kuberich.domain.containers import CONTAINER_COLUMNS, ContainerRow, container_rows
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.transfers import TransferDirection
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.attach import AttachService
from kuberich.services.logs import LogStream
from kuberich.services.processes import ProcessRunner, _finish_owned
from kuberich.services.shell import ShellService
from kuberich.services.transfers import TransferService
from kuberich.ui.chrome import (
    CONTAINER_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.logs import LogScreen
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.presentation import FrameTable
from kuberich.ui.terminal import ShellScreen
from kuberich.ui.transfers import TransferScreen


def _project_containers(record: ResourceRecord) -> tuple[ContainerRow, ...]:
    return container_rows(record.manifest)


class ContainerTable(FrameTable[Text]):
    BINDING_PROFILE = "containers"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("containers")


class ContainerScreen(CommandWorkspace):
    AUTO_FOCUS = "#containers"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("l", "logs", "Logs"),
        Binding("s", "shell", "Shell"),
        Binding("x", "shell", "Shell", show=False),
        Binding("a", "attach", "Attach"),
        Binding("u", "upload", "Upload"),
        Binding("d", "download", "Download"),
    ]
    DEFAULT_CSS = """
    ContainerScreen { layout: vertical; background: $background; }
    #container-title, #container-hints, #container-status { height: 1; text-overflow: ellipsis; }
    #container-title { color: $accent; height: 1; border: none; }
    ContainerScreen.short #container-title { height: 1; border-top: none; border-bottom: none; }
    #container-feedback { height: auto; min-height: 1; max-height: 3; margin: 0 1; }
    ContainerScreen.short #container-feedback { height: 1; max-height: 1; }
    #container-status { height: auto; text-overflow: fold; }
    #containers { height: 1fr; }
    #container-title { width: 1fr; }
    #container-hints { width: 1fr; display: none; }
    ContainerScreen.short #container-hints { display: block; }
    ContainerScreen.short #container-title { display: none; }
    #container-back { width: 14; min-width: 14; height: 1; border: none; }
    """

    def __init__(
        self,
        stream: LogStream,
        manifest: dict[str, Any],
        *,
        shell: ShellService | None = None,
        attach: AttachService | None = None,
        transfers: TransferService | None = None,
        processes: ProcessRunner | None = None,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = ("pods",),
    ) -> None:
        super().__init__()
        self.stream = stream
        self.invalidated = False
        self._pending_record: ResourceRecord | None = None
        self._last_record: ResourceRecord | None = None
        self._rows_task: asyncio.Task[None] | None = None
        self.shell, self.processes = shell, processes
        self.attach = attach
        self.transfers = transfers
        self.chrome, self.trail = chrome, (*trail, "containers")
        self.rows = container_rows(manifest)
        self.names = tuple(row.name for row in self.rows)
        if not self.names:
            raise AppError("The selected pod has no regular/init/ephemeral containers.")
        self.table = ContainerTable(id="containers", cursor_type="row", zebra_stripes=True)
        self.status = Static(
            "Pod snapshot · CPU/MEM are requests/limits; live usage is not collected.",
            markup=False,
            id="container-status",
        )

    def compose(self) -> ComposeResult:
        target = self.stream.target
        if self.chrome is not None:
            yield WorkspaceHeader(self.chrome, CONTAINER_SHORTCUTS, binding_profile="containers")
        with WorkspaceBars():
            with Horizontal(classes="container-caption"):
                yield Static(
                    safe_text(
                        f"Containers · {target.namespace}/{target.name} · {target.session.context}"
                    ),
                    id="container-title",
                )
                yield Static(
                    "Containers · s shell" if self.shell is not None else "Containers Enter logs",
                    markup=False,
                    id="container-hints",
                )
                yield Button("Back to pods", id="container-back", compact=True)
            yield from self.command_bar()
        with WorkspaceFrame(id="container-dialog"):
            yield self.table
        yield Breadcrumbs(
            self.trail,
            "Pods",
            visible=self.chrome is None or not self.chrome.presentation.crumbsless,
        )
        with VerticalScroll(id="container-feedback"):
            yield self.status

    def _set_status(self, message: str | Text) -> None:
        self.status.update(message)

    def on_mount(self) -> None:
        target = self.stream.target
        self.query_one("#container-dialog", Vertical).border_title = safe_text(
            f"containers({target.namespace}/{target.name})[{len(self.names)}]"
        )
        for index, label in enumerate(CONTAINER_COLUMNS):
            self.table.add_column(label, key=str(index))
        for row in self.rows:
            self.table.add_row(*(safe_text(cell) for cell in row.cells()), key=row.name)
        self.validate_target()

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.validate_target()

    def validate_target(self) -> None:
        try:
            if self.invalidated:
                raise AppError("The container target is stale; select the pod again.")
            self.stream.require_current()
        except AppError as error:
            self.invalidated = True
            self._pending_record = None
            self.names = ()
            self.rows = ()
            self.table.clear()
            self.table.disabled = True
            if (
                self._rows_task is not None
                and not self._rows_task.done()
                and not self._rows_task.cancelling()
            ):
                self._rows_task.cancel()
            self._set_status(safe_text(str(error)))

    @on(DataTable.RowSelected, "#containers")
    def selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        name = event.row_key.value
        if name is not None and name in self.names and not self.invalidated:
            self._open(name)

    def action_logs(self) -> None:
        if self.names and not self.invalidated:
            self._open(self._selected_name())

    def _selected_name(self) -> str:
        if self.invalidated or not self.table.row_count:
            raise AppError("Select a current container first.")
        name = self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
        if name not in self.names:
            raise AppError("The selected container is no longer present.")
        return name

    def observe_record(self, record: ResourceRecord) -> None:
        if self.invalidated or record is self._last_record or record.uid != self.stream.target.uid:
            return
        self._last_record = record
        self._pending_record = record
        if self._rows_task is None or self._rows_task.done():
            self._rows_task = asyncio.create_task(self._refresh_rows())

    async def _refresh_rows(self) -> None:
        while self._pending_record is not None and not self.invalidated:
            record, self._pending_record = self._pending_record, None
            worker = asyncio.create_task(asyncio.to_thread(_project_containers, record))
            try:
                rows = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await _finish_owned(asyncio.gather(worker, return_exceptions=True))
                raise
            self.validate_target()
            if self.invalidated or record is not self._last_record:
                continue
            table = self.table
            selected = self._selected_name() if table.row_count else None
            x, y = table.scroll_x, table.scroll_y
            names = tuple(row.name for row in rows)
            for key in tuple(table.rows):
                if key.value not in names:
                    table.remove_row(key)
            for row in rows:
                cells = tuple(safe_text(cell) for cell in row.cells())
                if row.name not in table.rows:
                    table.add_row(*cells, key=row.name)
                else:
                    for index, cell in enumerate(cells):
                        if table.get_cell(row.name, str(index)) != cell:
                            table.update_cell(row.name, str(index), cell, update_width=True)
            self.rows, self.names = rows, names
            if selected in names:
                table.move_cursor(row=table.get_row_index(selected), scroll=False)
            table.scroll_to(x=x, y=y, animate=False, immediate=True, force=True)
            self._set_status(
                "Live pod watch · CPU/MEM are requests/limits; usage is not collected."
            )

    async def stop_owned(self) -> None:
        self.invalidated = True
        self._pending_record = None
        if self._rows_task is not None:
            if not self._rows_task.done() and not self._rows_task.cancelling():
                self._rows_task.cancel()
            await _finish_owned(asyncio.gather(self._rows_task, return_exceptions=True))
        self.names, self.rows = (), ()
        self.table.clear()
        self.table.disabled = True

    async def on_unmount(self) -> None:
        await self.stop_owned()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.focused, Input) or self.invalidated:
            return False
        if action == "shell":
            return self.shell is not None and self.processes is not None
        if action == "attach":
            return self.attach is not None and self.processes is not None
        if action in {"upload", "download"}:
            return self.transfers is not None
        return True

    def action_shell(self) -> None:
        self._terminal(self.shell)

    def action_attach(self) -> None:
        self._terminal(self.attach)

    def action_upload(self) -> None:
        self._transfer(TransferDirection.UPLOAD)

    def action_download(self) -> None:
        self._transfer(TransferDirection.DOWNLOAD)

    def _transfer(self, direction: TransferDirection) -> None:
        if self.app.screen is not self or self.transfers is None:
            return
        try:
            self.transfers.require_current(direction)
        except AppError as error:
            self._set_status(safe_text(str(error)))
            return

        def returned(message: str | None) -> None:
            self.validate_target()
            self._set_status(safe_text(message or "No transfer started."))

        self.app.push_screen(
            TransferScreen(self.transfers, self._selected_name(), direction), returned
        )

    def _terminal(self, service: ShellService | AttachService | None) -> None:
        if self.app.screen is not self:
            return
        if service is None or self.processes is None:
            return
        try:
            request = service.capture(self._selected_name())
        except AppError as error:
            self._set_status(safe_text(str(error)))
            return

        def returned(message: str | None) -> None:
            self.validate_target()
            self._set_status(safe_text(message or "Shell closed."))

        self.app.push_screen(ShellScreen(service, self.processes, request), returned)

    def _open(self, name: str) -> None:
        if self.app.screen is not self:
            return
        try:
            self.stream.require_current()
        except AppError as error:
            self.validate_target()
            self._set_status(safe_text(str(error)))
            return
        self.app.push_screen(
            LogScreen(self.stream, self.names, selected=name, chrome=self.chrome, trail=self.trail)
        )

    @on(Button.Pressed, "#container-back")
    def back(self) -> None:
        self.dismiss()
