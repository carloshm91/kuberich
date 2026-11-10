"""Inert local navigation, explicit rendering and redacted manifest inspection."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.events import ScreenResume
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Static

from kuberich.adapters.editing import file_worker
from kuberich.domain.manifests import (
    FrozenManifestSource,
    ManifestAction,
    ManifestEntry,
    ManifestListing,
    ManifestSourceKind,
    manifest_preview,
)
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.ui.manifest_editor import ManifestEditorScreen
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.presentation import FrameTable
from kuberich.ui.read_only_text import ReadOnlyText


class ManifestBrowserScreen(ModalScreen[None]):
    AUTO_FOCUS = "#manifests-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ManifestBrowserScreen { align: center middle; background: $background 80%; }
    #manifests-form { width: 98%; height: 96%; border: solid $primary; padding: 0 1;
        background: $surface; }
    #manifests-title, #manifests-location, #manifests-status, #manifests-page { height: 1; }
    #manifests-root { height: 3; }
    #manifests-files { height: 1fr; min-height: 3; }
    ManifestBrowserScreen.inspection #manifests-files { height: 5; }
    #manifests-resources { height: 4; }
    #manifests-preview { height: 1fr; min-height: 2; }
    #manifests-buttons { height: 3; layout: grid; grid-size: 4; grid-rows: 1 1 1; }
    #manifests-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    ManifestBrowserScreen.compact #manifests-root { height: 1; border: none; padding: 0 1; }
    ManifestBrowserScreen.compact.inspection #manifests-files { height: 3; }
    ManifestBrowserScreen.compact #manifests-resources { height: 3; }
    """

    def __init__(
        self,
        *,
        service: LocalManifestService,
        open_review: Callable[[FrozenManifestSource, ManifestAction], None],
        runner: ProcessRunner,
    ) -> None:
        super().__init__()
        self.service, self.open_review, self.runner = service, open_review, runner
        self.location = ForwardInput(
            id="manifests-root", placeholder="Allowed local root · Enter opens", max_length=4096
        )
        self.table: FrameTable[Text] = FrameTable(id="manifests-files", cursor_type="row")
        self.resources: FrameTable[Text] = FrameTable(id="manifests-resources", cursor_type="row")
        self.viewer = ReadOnlyText("", read_only=True, id="manifests-preview")
        self.status = Static("Reading local metadata…", markup=False, id="manifests-status")
        self.listing: ManifestListing | None = None
        self.source: FrozenManifestSource | None = None
        self.pages: tuple[str, ...] = ()
        self.page = 0
        self._inspected_entry: ManifestEntry | None = None
        self._document_row = -1
        self._root_value = ""
        self._generation = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._editors: list[ManifestEditorScreen] = []
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return len(self._tasks) + sum(screen.operation_count for screen in self._editors)

    def compose(self) -> ComposeResult:
        self._root_value = str(
            self.service.root.path if self.service.root else self.service.directory
        )
        self.location.value = self._root_value
        with Vertical(id="manifests-form"):
            yield Static(
                "Local manifests · inspect / edit / render / review",
                markup=False,
                id="manifests-title",
            )
            yield self.location
            yield Static(
                "Local root only · cluster destination is captured separately at Review",
                markup=False,
                id="manifests-location",
            )
            yield self.table
            yield self.resources
            yield self.viewer
            yield Static("", markup=False, id="manifests-page")
            yield self.status
            with Horizontal(id="manifests-buttons"):
                for label, name in (
                    ("Open root", "root"),
                    ("Parent", "parent"),
                    ("Inspect / open", "inspect"),
                    ("Preview directory", "directory"),
                    ("Render Kustomize", "render"),
                    ("Edit local", "edit"),
                    ("Previous page", "previous"),
                    ("Next page", "next"),
                    ("Review apply", "apply"),
                    ("Review delete", "delete"),
                    ("Refresh", "refresh"),
                    ("Back", "back"),
                ):
                    yield Button(label, compact=True, id="manifests-" + name)

    def on_resize(self) -> None:
        self.set_class(self.size.height < 28, "compact")

    def on_mount(self) -> None:
        self.on_resize()
        self.table.add_columns("Local entry", "Type", "Problem")
        self.resources.add_columns("#", "Kind", "Namespace", "Name")
        self._clear_source()
        self.action_open_root()

    def on_screen_resume(self, event: ScreenResume) -> None:
        if (
            self.is_mounted
            and self.source is not None
            and self.service.current_source is not self.source
        ):
            self._clear_source()
            self.status.update(
                "Local source changed · Refresh and inspect/render again before cluster review."
            )

    def _current(self, generation: int) -> bool:
        return not self._stopped and self.is_attached and generation == self._generation

    def _clear_source(self) -> None:
        self.source = None
        self._inspected_entry = None
        self._document_row = -1
        self.pages = ()
        self.page = 0
        self.resources.clear()
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text("")
        self._show_page()

    def _controls(self) -> None:
        if self._stopped or not self.viewer.is_attached:
            return
        for name in ("apply", "delete"):
            self.query_one("#manifests-" + name, Button).disabled = (
                self.source is None or bool(self._tasks) or self.service.policy.read_only
            )
        self.query_one("#manifests-edit", Button).disabled = self.service.policy.read_only
        self.query_one("#manifests-previous", Button).disabled = self.page <= 0
        self.query_one("#manifests-next", Button).disabled = self.page + 1 >= len(self.pages)
        inspecting = bool(self.pages or self.source)
        self.set_class(inspecting, "inspection")
        self.resources.display = self.source is not None
        self.viewer.display = inspecting
        self.query_one("#manifests-page").display = inspecting

    def _start(
        self, operation: Callable[[int], Awaitable[None]], *, invalidate: bool = True
    ) -> None:
        if self._stopped:
            return
        self._generation += 1
        if invalidate:
            self.service.invalidate()
            self._clear_source()
        previous = tuple(self._tasks)
        for task in previous:
            task.cancel()
        task = asyncio.create_task(self._run(previous, operation, self._generation))
        self._tasks.add(task)
        task.add_done_callback(self._retire)
        self._controls()

    async def _run(
        self,
        previous: tuple[asyncio.Task[None], ...],
        operation: Callable[[int], Awaitable[None]],
        generation: int,
    ) -> None:
        try:
            await finish_owned(asyncio.gather(*previous, return_exceptions=True))
            if self._current(generation):
                await operation(generation)
        except AppError as error:
            if self._current(generation):
                self.status.update(safe_text(str(error)))
        except Exception:
            if self._current(generation):
                self.status.update("Local manifest operation failed; file content was withheld.")

    def _retire(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()
        self._controls()
        if (
            not self._stopped
            and self.source is not None
            and not self._tasks
            and 0 <= self.resources.cursor_row < len(self.source.documents)
            and self.resources.cursor_row != self._document_row
        ):
            self._start(self._document, invalidate=False)

    def selected_entry(self) -> ManifestEntry | None:
        return (
            self.listing.entries[self.table.cursor_row]
            if self.listing is not None and 0 <= self.table.cursor_row < len(self.listing.entries)
            else None
        )

    def _listing(self, listing: ManifestListing) -> None:
        selected = self.selected_entry()
        identity = (
            (selected.relative_path, selected.identity.device, selected.identity.inode)
            if selected
            else None
        )
        row, x, y = self.table.cursor_row, self.table.scroll_x, self.table.scroll_y
        self.listing = listing
        self.table.clear()
        for entry in listing.entries:
            self.table.add_row(
                *(
                    safe_text(value)
                    for value in (
                        PurePosixPath(entry.relative_path).name,
                        entry.kind,
                        entry.problem or "",
                    )
                ),
                key=entry.relative_path,
            )
        position = next(
            (
                index
                for index, entry in enumerate(listing.entries)
                if (entry.relative_path, entry.identity.device, entry.identity.inode) == identity
            ),
            min(row, max(0, len(listing.entries) - 1)),
        )
        self.table.move_cursor(row=position, animate=False, scroll=False)
        self.table.scroll_to(x=x, y=y, animate=False, force=True)
        self._root_value = str(listing.root.path)
        self.location.value = self._root_value
        self.query_one("#manifests-location", Static).update(
            safe_text(f"Local: {listing.root.path} / {listing.relative_directory or '.'}")
        )
        self.status.update(
            f"{len(listing.entries)} entries · {listing.skipped} skipped"
            + (
                " · listing limit reached; split the directory"
                if listing.limited
                else " · no files or helpers executed"
            )
        )

    def action_open_root(self) -> None:
        path = Path(self.location.value)

        async def open_root(generation: int) -> None:
            listing = await self.service.open_root(path)
            if self._current(generation):
                self._listing(listing)

        self._start(open_root)

    def _navigate(self, relative: str) -> None:
        async def navigate(generation: int) -> None:
            listing = await self.service.list(relative)
            if self._current(generation):
                self._listing(listing)

        self._start(navigate)

    def action_refresh(self) -> None:
        if self.listing is not None:
            self._navigate(self.listing.relative_directory)
        else:
            self.action_open_root()

    def action_parent(self) -> None:
        if self.listing is not None:
            parent = str(PurePosixPath(self.listing.relative_directory).parent)
            self._navigate("" if parent == "." else parent)

    def _capture(self, relative: str, kind: ManifestSourceKind) -> None:
        entry = self.selected_entry()

        async def capture(generation: int) -> None:
            self.status.update(
                "Rendering local Kustomize with execution disabled…"
                if kind == "kustomize"
                else "Freezing and validating local source…"
            )
            source = await self.service.capture(relative, kind)
            if self._current(generation):
                self.source = source
                self.resources.clear()
                for document in source.documents:
                    self.resources.add_row(
                        *(
                            safe_text(value)
                            for value in (
                                str(document.ordinal),
                                document.kind,
                                document.namespace or "(captured at Review)",
                                document.name,
                            )
                        ),
                        key=str(document.ordinal),
                    )
                await self._document(generation)
                if self._current(generation):
                    self.status.update(
                        f"{len(source.documents)} frozen resources · Review captures the cluster destination; no writes sent."
                    )

        self._start(capture)
        self._inspected_entry = entry

    async def _document(self, generation: int) -> None:
        source = self.source
        index = self.resources.cursor_row
        if source is None or not 0 <= index < len(source.documents):
            return
        document = source.documents[index]
        pages = await file_worker(lambda: manifest_preview(None, document.body))
        if (
            self._current(generation)
            and self.source is source
            and self.resources.cursor_row == index
        ):
            self.pages, self.page = pages, 0
            self._document_row = index
            self._show_page()

    def _show_page(self) -> None:
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text(self.pages[self.page] if self.pages else "")
        if not self._stopped and self.viewer.is_attached:
            self.query_one("#manifests-page", Static).update(
                f"Redacted preview · page {self.page + 1 if self.pages else 0}/{len(self.pages)}"
            )
        self._controls()

    def action_inspect(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.status.update("Select a local entry first.")
        elif entry.kind == "directory":
            self._navigate(entry.relative_path)
        elif entry.kind == "manifest":
            self._capture(entry.relative_path, "file")
        elif entry.kind == "kustomization":

            async def inspect(generation: int) -> None:
                pages = await self.service.inspect_file(entry.relative_path)
                if self._current(generation):
                    self.pages, self.page = pages, 0
                    self._show_page()
                    self.status.update(
                        "Kustomization structure only; values hidden. Render Kustomize is a separate explicit action."
                    )

            self._start(inspect)
            self._inspected_entry = entry
        else:
            self.status.update(
                safe_text(
                    entry.problem or "This local entry is unavailable; symlinks are not followed."
                )
            )

    def action_edit(self) -> None:
        entry = self.selected_entry()
        if entry is None or entry.kind not in {"manifest", "kustomization"}:
            self.status.update("Select an ordinary YAML/JSON file to edit locally.")
            return
        if self.service.policy.read_only or self._tasks:
            self.status.update(
                "Local editing is unavailable in read-only mode or during a source operation."
            )
            return
        screen = ManifestEditorScreen(
            service=self.service, runner=self.runner, relative=entry.relative_path
        )
        self._editors.append(screen)
        self.app.push_screen(screen)

    @on(Input.Submitted, "#manifests-root")
    def root_submitted(self) -> None:
        self.action_open_root()

    @on(Input.Changed, "#manifests-root")
    def root_changed(self, event: Input.Changed) -> None:
        if not self.is_mounted or event.value == self._root_value:
            return
        self._generation += 1
        self.service.invalidate()
        for task in self._tasks:
            task.cancel()
        self._clear_source()
        self.listing = None
        self.table.clear()
        self.status.update(
            "Root changed · Open root or press Enter to capture the new allowed root."
        )

    @on(DataTable.RowSelected, "#manifests-files")
    def row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_inspect()

    @on(DataTable.RowHighlighted, "#manifests-files")
    def file_selection_changed(self) -> None:
        if self._inspected_entry is not None and self.selected_entry() != self._inspected_entry:
            self._generation += 1
            self.service.invalidate()
            for task in self._tasks:
                task.cancel()
            self._clear_source()
            self.status.update("Selected local source changed · inspect or render a fresh preview.")

    @on(DataTable.RowHighlighted, "#manifests-resources")
    def resource_selected(self) -> None:
        if self.source is not None and not self._tasks:
            self._start(self._document, invalidate=False)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("manifests-")
        actions = {
            "root": self.action_open_root,
            "parent": self.action_parent,
            "inspect": self.action_inspect,
            "edit": self.action_edit,
            "refresh": self.action_refresh,
        }
        if name in actions:
            actions[name]()
        elif name in {"directory", "render"} and self.listing is not None:
            self._capture(
                self.listing.relative_directory, "kustomize" if name == "render" else "directory"
            )
        elif name in {"previous", "next"} and self.pages:
            self.page = max(0, min(len(self.pages) - 1, self.page + (1 if name == "next" else -1)))
            self._show_page()
        elif name in {"apply", "delete"} and self.source is not None and not self._tasks:
            self.open_review(self.source, "delete" if name == "delete" else "apply")
        elif name == "back":
            self.run_worker(self.action_back())

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        self._generation += 1
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._tasks.clear()
        for editor in tuple(self._editors):
            await editor.stop_owned()
        self._editors.clear()
        self.service.invalidate()
        self._clear_source()

    async def on_unmount(self) -> None:
        await self.stop_owned()
