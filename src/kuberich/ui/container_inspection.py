"""A finite captured-container inspector with separate one-use value disclosure."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.events import ScreenResume, ScreenSuspend
from textual.widgets import Button, DataTable, Input, Static, TextArea

from kuberich.domain.configuration_data import clipboard_value
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.container_inspection import (
    OBSERVATION_NOTICE,
    EntryId,
    InspectionSnapshot,
    metadata_table,
)
from kuberich.domain.exports import ExportPresentation, TableSource
from kuberich.domain.navigation import Viewport
from kuberich.domain.resources import ResourceRecord
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
from kuberich.services.inspection import read_error
from kuberich.services.ownership import finish_owned
from kuberich.ui.chrome import (
    CONTAINER_INSPECTION_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.export_captures import captured_lease, header_namespace, target_scope
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.presentation import FrameTable

if TYPE_CHECKING:
    from kuberich.services.container_inspection import ContainerInspectionService, DisclosureIntent
    from kuberich.services.exports import ExportChoices

type Section = Literal["environment", "image", "sources"]
type Selection = tuple[str, str]

_HIDDEN = "Values hidden · e environment · i image · s sources · r reveal · Ctrl+Y copy · R reload"
_RELOAD = "Container configuration changed; reload required."


class ContainerInspectionTable(FrameTable[Text]):
    BINDING_PROFILE = "container-inspection"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("container-inspection")

    def capture_viewport(self) -> Viewport:
        keys = tuple(row.key.value for row in self.ordered_rows)
        selected = keys[self.cursor_row] if 0 <= self.cursor_row < len(keys) else None
        top_index = min(int(self.scroll_y), max(0, len(keys) - 1))
        top = keys[top_index] if keys else None
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top)


class ContainerInspectionScreen(CommandWorkspace):
    """Metadata is exportable; disclosed text belongs only to the dedicated viewer."""

    sensitive: ClassVar[bool] = True
    AUTO_FOCUS = "#container-inspection-table"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("e", "section('environment')", "Environment"),
        Binding("i", "section('image')", "Image"),
        Binding("s", "section('sources')", "Sources"),
        Binding("r", "reveal", "Reveal / hide"),
        Binding("ctrl+y", "copy", "Copy selected", priority=True),
        Binding("R", "reload", "Reload", key_display="Shift+R"),
    ]
    DEFAULT_CSS = """
    ContainerInspectionScreen { layout: vertical; background: $background; }
    #container-inspection-title, #container-inspection-buttons,
    #container-inspection-status, #container-inspection-notice { height: 1; }
    #container-inspection-title { color: $accent; text-overflow: ellipsis; }
    #container-inspection-notice, #container-inspection-status { text-overflow: ellipsis; }
    #container-inspection-buttons Button { height: 1; border: none; min-width: 4; width: 1fr; }
    #container-inspection-table { height: 1fr; min-height: 1; }
    #container-inspection-value { height: 1fr; min-height: 1; border: none; }
    #container-inspection-value.hidden { display: none; }
    ContainerInspectionScreen.short #container-inspection-title { display: none; }
    ContainerInspectionScreen.short #container-inspection-notice { display: none; }
    """

    def __init__(
        self,
        service: ContainerInspectionService,
        *,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = ("pods", "containers"),
        stopped: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__()
        self.service, self.chrome = service, chrome
        self.trail = (*trail, "environment / image")
        self.invalidated = False
        self.reload_required = False
        self.snapshot: InspectionSnapshot | None = None
        self.section: Section = "environment"
        self.revealed = False
        self._generation = 0
        self._metadata_generation = 0
        self._selection_hint: Selection | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._stop_task: asyncio.Task[None] | None = None
        self._stopped, self._notify_stopped = False, stopped
        self.table = ContainerInspectionTable(
            id="container-inspection-table", cursor_type="row", zebra_stripes=True
        )
        self.viewer = TextArea(
            read_only=True, soft_wrap=False, id="container-inspection-value", classes="hidden"
        )
        self.status = Static(
            "Loading container metadata…", markup=False, id="container-inspection-status"
        )

    @property
    def operation_count(self) -> int:
        """Include service work even while a cancelled caller is draining."""
        return len(self._tasks) + self.service.operation_count

    def compose(self) -> ComposeResult:
        target, container = self.service.target, self.service.container
        if self.chrome is not None:
            yield WorkspaceHeader(
                self.chrome, CONTAINER_INSPECTION_SHORTCUTS, binding_profile="container-inspection"
            )
        with WorkspaceBars():
            yield Static(
                safe_text(f"{target.namespace}/{target.name} · {container.kind} {container.name}"),
                id="container-inspection-title",
            )
            with Horizontal(id="container-inspection-buttons"):
                for label, name in (
                    ("Env", "environment"),
                    ("Image", "image"),
                    ("Sources", "sources"),
                    ("Reveal", "reveal"),
                    ("Copy", "copy"),
                    ("Reload", "reload"),
                    ("Back", "back"),
                ):
                    yield Button(label, id="container-inspection-" + name, compact=True)
            yield from self.command_bar()
        with WorkspaceFrame(id="container-inspection-dialog"):
            yield self.table
            yield self.viewer
        yield Static(OBSERVATION_NOTICE, markup=False, id="container-inspection-notice")
        yield self.status
        yield Breadcrumbs(
            self.trail,
            "Containers",
            visible=self.chrome is None or not self.chrome.presentation.crumbsless,
        )

    def on_mount(self) -> None:
        self.action_reload()

    def hide_value(self) -> None:
        self._generation += 1
        self.service.cancel_disclosure()
        self.revealed = False
        self.viewer.load_text("")
        self.viewer.add_class("hidden")

    def _selected(self) -> EntryId | None:
        if self.snapshot is None or self.section != "environment" or not self.table.row_count:
            return None
        key = self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
        return next((entry.id for entry in self.snapshot.entries if str(entry.id) == key), None)

    def _hint(self) -> None:
        if self.reload_required:
            self.status.update(_RELOAD)
            return
        notice = (
            " · incomplete sources or declarations"
            if self.snapshot and not self.snapshot.complete
            else ""
        )
        self.status.update(_HIDDEN + notice)

    def _selection(self) -> Selection | None:
        selected = self._selected()
        if self.snapshot is not None and selected is not None:
            entry = next(entry for entry in self.snapshot.entries if entry.id == selected)
            return entry.path, entry.name
        return self._selection_hint

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None and not self._stopped:
            self.hide_value()
            self.status.update("Container inspection failed; reload required.")

    def _launch(self, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _ready(self) -> bool:
        if self._stopped or self.invalidated:
            self.status.update("Container inspection stopped; select the pod again.")
            return False
        return self.app.screen is self

    def action_reload(self) -> None:
        self.hide_value()
        if not self._ready():
            return
        self._metadata_generation += 1
        generation = self._metadata_generation
        selected = self._selection()
        self._selection_hint = selected
        self.snapshot = None
        self.table.disabled = True
        self.status.update("Loading container metadata…")
        self._launch(self._load(generation, selected))

    async def _load(self, generation: int, selected: Selection | None) -> None:
        try:
            snapshot = await self.service.index()
            if self._stopped or generation != self._metadata_generation or not self.is_attached:
                return
            self.service.require_current()
            self.snapshot = snapshot
            self.reload_required = False
            self.table.disabled = False
            self._render_metadata(selected)
            if not isinstance(self.focused, Input):
                self.set_focus(self.table)
        except (AppError, ConnectionProblem) as error:
            if generation == self._metadata_generation and not self._stopped:
                self.status.update(safe_text(read_error(error)))

    def _render_metadata(self, selected: Selection | None = None) -> None:
        if self.snapshot is None:
            return
        projection = metadata_table(self.snapshot, self.section)
        cells = tuple(tuple(safe_text(cell) for cell in row.cells) for row in projection.rows)
        self.table.clear(columns=True)
        for index, label in enumerate(projection.columns):
            width = max((row[index].cell_len for row in cells), default=0)
            self.table.add_column(label, key=str(index), width=max(len(label), width))
        for row, rendered in zip(projection.rows, cells, strict=True):
            self.table.add_row(*rendered, key=row.key)
        if selected is not None and self.section == "environment":
            matching = next(
                (entry for entry in self.snapshot.entries if (entry.path, entry.name) == selected),
                None,
            )
            if matching is not None:
                self.table.move_cursor(row=self.table.get_row_index(str(matching.id)))
        self.query_one("#container-inspection-dialog", WorkspaceFrame).border_title = safe_text(
            f"{self.section}[{len(projection.rows)}] · values hidden"
        )
        self._hint()

    def action_section(self, section: Section) -> None:
        self.hide_value()
        self.section = section
        self._render_metadata()
        self.set_focus(self.table)

    def _disclose(self, action: Literal["reveal", "copy"]) -> None:
        self.hide_value()
        if not self._ready():
            return
        if self.reload_required:
            self.status.update(_RELOAD)
            return
        snapshot, entry = self.snapshot, self._selected()
        if snapshot is None or entry is None:
            self.status.update("Select a current environment entry first.")
            return
        if any(not task.done() for task in self._tasks):
            self.status.update("A read is in progress; retry after it completes.")
            return
        try:
            intent = self.service.new_intent(snapshot.id, entry, action)
        except AppError as error:
            self.status.update(safe_text(str(error)))
            return
        self._launch(self._read(intent, snapshot, entry, self.section, self._generation))

    async def _read(
        self,
        intent: DisclosureIntent,
        snapshot: InspectionSnapshot,
        entry: EntryId,
        section: Section,
        generation: int,
    ) -> None:
        try:
            value = await self.service.disclose(intent)
            if (
                self._stopped
                or self.invalidated
                or not self.is_attached
                or self.app.screen is not self
                or generation != self._generation
                or self.snapshot is not snapshot
                or self.section != section
                or self._selected() != entry
                or not self.service.snapshot_current(snapshot.id)
            ):
                return
            if value.text is None:
                self.status.update("Selected entry is unresolved; no text value is available.")
                return
            if intent.action == "copy":
                if not value.complete:
                    self.status.update("Selected entry is incomplete; copying is unavailable.")
                    return
                if "\x00" in value.text:
                    self.status.update("Selected entry contains NUL; copying is unavailable.")
                    return
                text = clipboard_value(value.text)
                try:
                    self.app.copy_to_clipboard(text)
                except Exception:
                    self.status.update(
                        "Clipboard write failed; no value was included in the error."
                    )
                    return
                self.status.update(
                    "Selected value copied; external clipboard contents remain until replaced."
                )
            else:
                preview = escape_controls(value.text[:16384], allow_newlines=True)
                if len(value.text) > 16384:
                    preview += "\n[Preview limited to 16384 characters]"
                self.viewer.load_text(preview)
                self.viewer.remove_class("hidden")
                self.revealed = True
                self.status.update(
                    "Selected value revealed · r hide"
                    + (" · incomplete resolution" if not value.complete else "")
                )
        except (AppError, ConnectionProblem) as error:
            if generation == self._generation and not self._stopped:
                if self.snapshot is snapshot and not self.service.snapshot_current(snapshot.id):
                    self.reload_required = True
                    self.hide_value()
                    self._hint()
                else:
                    self.status.update(safe_text(read_error(error)))

    def action_reveal(self) -> None:
        if self.revealed:
            self.hide_value()
            self._hint()
        else:
            self._disclose("reveal")

    def action_copy(self) -> None:
        self._disclose("copy")

    def validate_target(self) -> None:
        try:
            self.service.require_current()
        except AppError:
            self.invalidated = True
            self.reload_required = False
            self.hide_value()
            self.snapshot = None
            self._selection_hint = None
            self.table.clear()
            self.table.disabled = True
            self.service.invalidate()
            for task in tuple(self._tasks):
                task.cancel()
            self.status.update("The container target changed; select the pod again.")

    def observe_pod(self, record: ResourceRecord) -> None:
        self.service.observe_pod(record)
        if self.snapshot is not None and not self.service.snapshot_current(self.snapshot.id):
            self.reload_required = True
            self._selection_hint = self._selection()
            self.hide_value()
            self.snapshot = None
            self.table.disabled = True
            self.status.update("Pod configuration changed; reload required.")
        self.validate_target()

    def on_screen_suspend(self, event: ScreenSuspend) -> None:
        self.hide_value()
        if self.snapshot is not None:
            self._hint()

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.validate_target()

    @on(DataTable.RowHighlighted, "#container-inspection-table")
    def selected_changed(self) -> None:
        self.hide_value()
        if self.snapshot is not None:
            self._hint()

    @on(DataTable.RowSelected, "#container-inspection-table")
    def selected_opened(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_reveal()

    @on(Button.Pressed, "#container-inspection-buttons Button")
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("container-inspection-")
        if name in {"environment", "image", "sources"}:
            self.action_section(
                "environment"
                if name == "environment"
                else "image"
                if name == "image"
                else "sources"
            )
        elif name == "reveal":
            self.action_reveal()
        elif name == "copy":
            self.action_copy()
        elif name == "reload":
            self.action_reload()
        elif name == "back":
            self.hide_value()
            self.dismiss()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if isinstance(self.focused, Input):
            return False
        if action in {"reveal", "copy"}:
            return (
                self.section == "environment"
                and self.snapshot is not None
                and not self.invalidated
                and not self.reload_required
            )
        return not self._stopped and not self.invalidated

    def capture_export(self, at: datetime) -> ExportChoices:
        # There is no section filter. Transient command input is not a table query.
        snapshot, section = self.snapshot, self.section
        query = ""
        if (
            snapshot is None
            or self.invalidated
            or not self.is_mounted
            or not self.service.snapshot_current(snapshot.id)
        ):
            return ()
        projection = metadata_table(snapshot, section)
        target = replace(self.service.target, container=snapshot.container.name)

        def current() -> bool:
            return (
                self.is_mounted
                and self in self.app.screen_stack
                and not self.invalidated
                and not self._stopped
                and self.snapshot is snapshot
                and self.section == section
                and self.service.snapshot_current(snapshot.id)
            )

        lease = captured_lease(
            target_scope(
                at,
                target,
                resource=self.service.resource,
                resource_version=snapshot.pod.resource_version,
                source_at=snapshot.observed_at,
                header=header_namespace(self.chrome),
            ),
            TableSource(
                columns=projection.columns,
                rows=tuple(row.cells for row in projection.rows),
                row_keys=tuple(row.key for row in projection.rows),
                concealed_columns=frozenset(),
            ),
            current,
            target=target,
            presentation=ExportPresentation(
                view="container-inspection/" + section,
                query=query,
                viewport=self.table.capture_viewport(),
            ),
            notices=(
                OBSERVATION_NOTICE,
                "All environment values are omitted.",
                "Sources may be partial; source states and omissions are retained.",
            ),
        )
        return (("screen", lease),)

    async def _stop(self) -> None:
        self._stopped = self.invalidated = True
        self.hide_value()
        self.snapshot = None
        self._selection_hint = None
        self.service.invalidate()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await self.service.close()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._tasks.clear()
        self.table.clear()
        self.table.disabled = True
        self._notify_stopped()

    async def stop_owned(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await finish_owned(self._stop_task)

    async def on_unmount(self) -> None:
        await self.stop_owned()
