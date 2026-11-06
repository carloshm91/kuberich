"""Offline, literal local artifact browsing with explicit file actions."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static
from textual.widgets.data_table import RowKey

from kuberich.domain.exports import (
    ArtifactEntry,
    ArtifactListing,
    ArtifactRef,
    PreparedArtifact,
    SensitiveApproval,
    matches_entry,
)
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.exports import ExportService
from kuberich.services.ownership import finish_owned
from kuberich.ui.export_review import ArtifactConfirmation
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.presentation import FrameTable


class ArtifactTable(FrameTable[str | Text]):
    BINDING_PROFILE = "table"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("table")

    def _update_dimensions(self, new_rows: Iterable[RowKey]) -> None:
        widths = tuple(column.get_render_width(self) for column in self.ordered_columns)
        super()._update_dimensions(new_rows)
        if widths != tuple(column.get_render_width(self) for column in self.ordered_columns):
            # Native fixed-height sizing can grow widths after a row was painted.
            # Its render caches omit those widths; invalidate the earlier paint.
            self._clear_caches()
            self.refresh()


class ArtifactBrowserScreen(ModalScreen[None]):
    AUTO_FOCUS = "#artifacts-table"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+y", "copy", "Copy text", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ArtifactBrowserScreen { align: center middle; background: $background 80%; }
    #artifacts-form { width: 98%; height: 96%; border: solid $primary; padding: 0 1;
        background: $surface; }
    #artifacts-title { height: 1; }
    #artifacts-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #artifacts-directory, #artifacts-filter { height: 3; }
    #artifacts-table { height: 1fr; min-height: 2; }
    #artifacts-status { height: auto; max-height: 2; }
    #artifacts-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    ArtifactBrowserScreen.compact #artifacts-directory,
    ArtifactBrowserScreen.compact #artifacts-filter { height: 1; border: none; padding: 0 1; }
    ArtifactBrowserScreen.compact #artifacts-status { max-height: 1; }
    ArtifactBrowserScreen.compact #artifacts-table { min-height: 1; }
    """

    def __init__(
        self,
        *,
        service: ExportService,
        directory: Path,
        open_review: Callable[[ArtifactRef, Path], None],
        open_viewer: Callable[[ArtifactRef], None],
        copy_to_clipboard: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.service, self.open_review, self.open_viewer = service, open_review, open_viewer
        self.copy_to_clipboard = copy_to_clipboard
        self._initial_directory = str(directory)
        self._directory_value = str(directory)
        self.location = ForwardInput(id="artifacts-directory", max_length=4096)
        self.filter = ForwardInput(
            placeholder="Filter filename, format, context, namespace, sensitive",
            id="artifacts-filter",
            max_length=1024,
        )
        self.table = ArtifactTable(id="artifacts-table", cursor_type="row")
        self.status = Static(
            "Reading local artifact metadata…", markup=False, id="artifacts-status"
        )
        self.listing: ArtifactListing | None = None
        self.entries: tuple[ArtifactEntry, ...] = ()
        self._generation = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopped = False
        self._prepared: PreparedArtifact | None = None
        self._approval: SensitiveApproval | None = None
        self._confirmation: ArtifactConfirmation | None = None
        self._active_ref: ArtifactRef | None = None

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    @property
    def sensitive(self) -> bool:
        return self._prepared is not None and self._prepared.metadata.sensitive

    def compose(self) -> ComposeResult:
        self.location.value = self._initial_directory
        with Vertical(id="artifacts-form"):
            yield Static("Saved artifacts · local files only", markup=False, id="artifacts-title")
            yield self.location
            yield self.filter
            yield self.table
            yield self.status
            with Horizontal(id="artifacts-buttons"):
                for label, identifier in (
                    ("View", "view"),
                    ("Copy text", "copy"),
                    ("Save copy", "save-copy"),
                    ("Delete", "delete"),
                    ("Refresh", "refresh"),
                    ("Back", "back"),
                ):
                    yield Button(label, compact=True, id="artifacts-" + identifier)

    def on_resize(self) -> None:
        self.set_class(self.size.height < 18, "compact")

    def on_mount(self) -> None:
        self.on_resize()
        self.table.add_columns("Filename", "Format", "Context", "Namespace", "Sensitive", "Problem")
        self.action_refresh()

    def _current(self, generation: int) -> bool:
        return not self._stopped and self.is_attached and generation == self._generation

    def _discard(self) -> None:
        if self._prepared is not None:
            self.service.discard(self._prepared)
            self._prepared = None
        if self._approval is not None:
            self.service.discard(self._approval)
            self._approval = None

    def _start(
        self, operation: Callable[[int], Awaitable[None]], *, ref: ArtifactRef | None = None
    ) -> None:
        if self._stopped:
            return
        self._generation += 1
        self._active_ref = ref
        previous = tuple(self._tasks)
        for task in previous:
            task.cancel()
        task = asyncio.create_task(self._run(previous, operation, self._generation))
        self._tasks.add(task)
        task.add_done_callback(self._retire)

    async def _run(
        self,
        previous: tuple[asyncio.Task[None], ...],
        operation: Callable[[int], Awaitable[None]],
        generation: int,
    ) -> None:
        try:
            await finish_owned(asyncio.gather(*previous, return_exceptions=True))
            self._discard()
            if self._current(generation):
                await operation(generation)
        except AppError as error:
            if self._current(generation):
                self.status.update(safe_text(str(error)))
        except Exception:
            if self._current(generation):
                self.status.update(
                    "Local artifact operation failed; no file content was included in this error."
                )
        finally:
            self._discard()
            if generation == self._generation:
                self._active_ref = None

    def _retire(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def selected_entry(self) -> ArtifactEntry | None:
        return (
            self.entries[self.table.cursor_row]
            if 0 <= self.table.cursor_row < len(self.entries)
            else None
        )

    def _render_entries(self) -> None:
        selected = self.selected_entry()
        old_identity = (
            (selected.ref.name, selected.ref.identity.device, selected.ref.identity.inode)
            if selected
            else None
        )
        row, x, y = self.table.cursor_row, self.table.scroll_x, self.table.scroll_y
        self.entries = (
            tuple(
                entry for entry in self.listing.entries if matches_entry(entry, self.filter.value)
            )
            if self.listing
            else ()
        )
        self.table.clear()
        for entry in self.entries:
            metadata = entry.metadata
            self.table.add_row(
                *(
                    safe_text(value)
                    for value in (
                        entry.ref.name,
                        metadata.format if metadata else "unsupported",
                        metadata.scope.context or "unavailable" if metadata else "unavailable",
                        metadata.scope.collection_namespace
                        or metadata.scope.header_namespace
                        or metadata.scope.namespace_mode
                        if metadata
                        else "unavailable",
                        "yes" if metadata and metadata.sensitive else "no",
                        entry.problem or "",
                    )
                ),
                key=entry.ref.name,
            )
        position = next(
            (
                index
                for index, entry in enumerate(self.entries)
                if (entry.ref.name, entry.ref.identity.device, entry.ref.identity.inode)
                == old_identity
            ),
            min(row, max(0, len(self.entries) - 1)),
        )
        self.table.move_cursor(row=position, animate=False, scroll=False)
        self.table.scroll_to(x=x, y=y, animate=False, force=True)
        listing = self.listing
        self.status.update(
            safe_text(
                f"{len(self.entries)} shown · {len(listing.entries) if listing else 0} found · {listing.skipped if listing else 0} skipped"
                + (" · entry limit reached" if listing and listing.limited else "")
                + (f" · {listing.notice}" if listing and listing.notice else "")
            )
        )

    def action_refresh(self) -> None:
        directory = Path(self.location.value)

        async def scan(generation: int) -> None:
            self.status.update("Reading local metadata…")
            listing = await self.service.scan(directory)
            if self._current(generation):
                self.listing = listing
                self._render_entries()

        self._start(scan)

    @on(Input.Submitted, "#artifacts-directory")
    def directory_submitted(self) -> None:
        self.action_refresh()

    @on(Input.Changed, "#artifacts-directory")
    def directory_changed(self, event: Input.Changed) -> None:
        if event.value == self._directory_value:
            return
        self._directory_value = event.value
        if self.is_mounted:
            self._generation += 1
            for task in self._tasks:
                task.cancel()
            self.listing = None
            self._render_entries()
            self.status.update("Directory changed · press Enter or Refresh to scan it.")

    @on(Input.Changed, "#artifacts-filter")
    def filter_changed(self) -> None:
        if self.is_mounted:
            self._render_entries()

    def action_view(self) -> None:
        entry = self.selected_entry()
        if entry is not None and entry.metadata is not None:
            self.open_viewer(entry.ref)
        else:
            self.status.update("Select a recognized artifact first.")

    def action_save_copy(self) -> None:
        entry = self.selected_entry()
        if entry is not None and entry.metadata is not None:
            self.open_review(entry.ref, Path(self.location.value))
        else:
            self.status.update("Select a recognized artifact first.")

    async def _ask(self, *, message: str, label: str) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        confirmation = ArtifactConfirmation(message=message, label=label)
        self._confirmation = confirmation

        def answered(value: bool | None) -> None:
            if not future.done():
                future.set_result(bool(value))

        self.app.push_screen(confirmation, answered)
        try:
            return await future
        finally:
            if (
                confirmation.is_attached
                and self.app.screen_stack
                and self.app.screen is confirmation
            ):
                confirmation.dismiss(False)
            self._confirmation = None

    def action_copy(self) -> None:
        entry = self.selected_entry()
        if entry is None or entry.metadata is None:
            self.status.update("Select a recognized artifact first.")
            return

        async def copy(generation: int) -> None:
            if entry.metadata is not None and entry.metadata.sensitive:
                if not await self._ask(
                    message=f"Copy sensitive artifact text to the clipboard?\nDirectory: {entry.ref.directory.path}\nFilename: {entry.ref.name}\nThis is a separate one-use disclosure acknowledgement.",
                    label="Copy sensitive",
                ):
                    return
                self._approval = await self.service.approve_sensitive(
                    entry.ref, entry.metadata.format, intent="copy"
                )
            prepared = await self.service.read(entry.ref, intent="copy", approval=self._approval)
            self._prepared = prepared
            text = await self.service.copy_text(prepared)
            if self._current(generation):
                try:
                    self.copy_to_clipboard(text)
                except Exception:
                    self.status.update(
                        "Clipboard write failed; no artifact text was included in this error."
                    )
                else:
                    self.status.update("Clipboard write requested for this artifact.")

        self._start(copy, ref=entry.ref)

    def action_delete(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.status.update("Select a local artifact first.")
            return

        async def delete(generation: int) -> None:
            if not await self._ask(
                message=f"Delete this named local entry?\nDirectory: {entry.ref.directory.path}\nFilename: {entry.ref.name}\nThis cannot be undone.",
                label="Delete",
            ):
                return
            outcome = await self.service.delete(entry.ref, confirmed=True)
            if self._current(generation):
                self.status.update(safe_text(outcome.notice or "Local entry deleted."))
                listing = await self.service.scan(Path(self.location.value))
                if self._current(generation):
                    self.listing = listing
                    self._render_entries()

        self._start(delete, ref=entry.ref)

    @on(DataTable.RowHighlighted, "#artifacts-table")
    def selection_changed(self) -> None:
        selected = self.selected_entry()
        if self._active_ref is not None and (selected is None or selected.ref != self._active_ref):
            self._generation += 1
            self._active_ref = None
            for task in self._tasks:
                task.cancel()
            if (
                self._confirmation is not None
                and self.app.screen_stack
                and self.app.screen is self._confirmation
            ):
                self._confirmation.dismiss(False)

    @on(DataTable.RowSelected, "#artifacts-table")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_view()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        actions: dict[str, Callable[[], object]] = {
            "view": self.action_view,
            "copy": self.action_copy,
            "save-copy": self.action_save_copy,
            "delete": self.action_delete,
            "refresh": self.action_refresh,
        }
        name = (event.button.id or "").removeprefix("artifacts-")
        if name == "back":
            self.run_worker(self.action_back())
        elif name in actions:
            actions[name]()

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        self._generation += 1
        if (
            self._confirmation is not None
            and self._confirmation.is_attached
            and self.app.screen_stack
            and self.app.screen is self._confirmation
        ):
            self._confirmation.dismiss(False)
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._tasks.clear()
        self._discard()

    async def on_unmount(self) -> None:
        await self.stop_owned()
