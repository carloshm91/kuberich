"""Bounded full-content paging and explicit local artifact disclosure/copy."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from kuberich.domain.exports import (
    ArtifactRef,
    ExportKind,
    PreparedArtifact,
    SensitiveApproval,
    TextPage,
)
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.exports import ExportService
from kuberich.services.ownership import finish_owned
from kuberich.ui.export_review import ArtifactConfirmation
from kuberich.ui.read_only_text import ReadOnlyText


class ArtifactViewerScreen(ModalScreen[None]):
    AUTO_FOCUS = "#artifact-content"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+y", "copy", "Copy text", priority=True),
        Binding("ctrl+right", "next_page", "Next page", priority=True),
        Binding("ctrl+left", "previous_page", "Previous page", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ArtifactViewerScreen { align: center middle; background: $background 80%; }
    #artifact-form { width: 98%; height: 96%; border: solid $primary; padding: 0 1;
        background: $surface; }
    #artifact-title { height: 1; }
    #artifact-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #artifact-title { text-overflow: ellipsis; }
    #artifact-content { height: 1fr; min-height: 2; }
    #artifact-status { height: auto; max-height: 2; }
    #artifact-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    """

    def __init__(
        self,
        *,
        ref: ArtifactRef,
        service: ExportService,
        copy_to_clipboard: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.ref, self.service, self.copy_to_clipboard = ref, service, copy_to_clipboard
        self.viewer = ReadOnlyText(read_only=True, soft_wrap=False, id="artifact-content")
        self.status = Static(
            "Reading and validating this local artifact…", markup=False, id="artifact-status"
        )
        self.prepared: PreparedArtifact | None = None
        self.page: TextPage | None = None
        self._kind: ExportKind = "screen"
        self._tasks: set[asyncio.Task[None]] = set()
        self._generation = 0
        self._stopped = False
        self._approval: SensitiveApproval | None = None
        self._copy_prepared: PreparedArtifact | None = None
        self._confirmation: ArtifactConfirmation | None = None

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    @property
    def sensitive(self) -> bool:
        return self.prepared is not None and self.prepared.metadata.sensitive

    def compose(self) -> ComposeResult:
        with Vertical(id="artifact-form"):
            yield Static(
                safe_text(f"Local artifact · {self.ref.name} · {self.ref.directory.path}"),
                id="artifact-title",
            )
            yield self.viewer
            yield self.status
            with Horizontal(id="artifact-buttons"):
                for label, identifier in (
                    ("Previous", "previous"),
                    ("Next", "next"),
                    ("Copy text", "copy"),
                    ("View sensitive", "sensitive"),
                    ("Back", "back"),
                ):
                    yield Button(label, compact=True, id="artifact-" + identifier)

    def on_mount(self) -> None:
        self._start(lambda generation: self._load(generation, sensitive=False))

    def _current(self, generation: int) -> bool:
        return not self._stopped and self.is_attached and generation == self._generation

    def _discard_transient(self) -> None:
        if self._copy_prepared is not None:
            self.service.discard(self._copy_prepared)
            self._copy_prepared = None
        if self._approval is not None:
            self.service.discard(self._approval)
            self._approval = None

    def _clear(self) -> None:
        self._discard_transient()
        if self.prepared is not None:
            self.service.discard(self.prepared)
            self.prepared = None
        self.page = None
        if self.viewer.text:
            if self.app.screen_stack:
                self.viewer.load_text("")
            else:
                self.viewer.document.replace_range((0, 0), self.viewer.document.end, "")

    def _start(self, operation: Callable[[int], Awaitable[None]]) -> None:
        if self._stopped:
            return
        self._generation += 1
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
            if self._current(generation):
                await operation(generation)
        except AppError as error:
            if self._current(generation):
                self.status.update(safe_text(str(error)))
        except Exception:
            if self._current(generation):
                self.status.update(
                    "Artifact read failed; no file content was included in this error."
                )
        finally:
            self._discard_transient()

    def _retire(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _ask(self, *, intent: str) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        confirmation = ArtifactConfirmation(
            message=f"{intent} sensitive local resource YAML?\nDirectory: {self.ref.directory.path}\nFilename: {self.ref.name}\nThis one-use acknowledgement is limited to this action and unchanged private file.",
            label=intent + " sensitive",
        )
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

    async def _load(self, generation: int, *, sensitive: bool) -> None:
        self._clear()
        if sensitive:
            if not await self._ask(intent="View"):
                self.status.update("Sensitive view cancelled. Reopen for a redacted view.")
                return
            self._approval = await self.service.approve_sensitive(
                self.ref, "resource-yaml", intent="view"
            )
        prepared = await self.service.read(self.ref, intent="view", approval=self._approval)
        if not self._current(generation):
            self.service.discard(prepared)
            return
        self.prepared = prepared
        self._kind = prepared.metadata.format
        self.query_one("#artifact-sensitive", Button).display = self._kind == "resource-yaml"
        self.query_one("#artifact-sensitive", Button).label = (
            "Hide sensitive" if self.sensitive else "View sensitive"
        )
        await self._page(generation, 0)
        if self._current(generation):
            self.set_focus(self.viewer)

    async def _page(self, generation: int, index: int) -> None:
        prepared = self.prepared
        if prepared is None:
            return
        page = await self.service.page(prepared, index)
        if not self._current(generation) or prepared is not self.prepared:
            return
        self.page = page
        self.viewer.load_text(page.text)
        self.query_one("#artifact-previous", Button).disabled = page.index <= 0
        self.query_one("#artifact-next", Button).disabled = page.index + 1 >= page.total
        self.status.update(
            f"Page {page.index + 1}/{page.total} · 256 KiB maximum per page · {'sensitive values visible' if self.sensitive else 'redacted read-only view'} · Copy is explicit"
        )

    def action_next_page(self) -> None:
        if self.page is not None and self.page.index + 1 < self.page.total:
            index = self.page.index + 1
            self._start(lambda generation: self._page(generation, index))

    def action_previous_page(self) -> None:
        if self.page is not None and self.page.index > 0:
            index = self.page.index - 1
            self._start(lambda generation: self._page(generation, index))

    def action_sensitive(self) -> None:
        if self._kind == "resource-yaml":
            sensitive = not self.sensitive
            self._start(lambda generation: self._load(generation, sensitive=sensitive))

    def action_copy(self) -> None:
        if self.prepared is None:
            self.status.update("Open a validated artifact first.")
            return
        include_sensitive = self.sensitive

        async def copy(generation: int) -> None:
            if include_sensitive:
                if not await self._ask(intent="Copy"):
                    return
                self._approval = await self.service.approve_sensitive(
                    self.ref, self._kind, intent="copy"
                )
            prepared = await self.service.read(self.ref, intent="copy", approval=self._approval)
            self._copy_prepared = prepared
            text = await self.service.copy_text(prepared)
            if self._current(generation):
                try:
                    self.copy_to_clipboard(text)
                except Exception:
                    self.status.update(
                        "Clipboard write failed; no artifact text was included in this error."
                    )
                else:
                    self.status.update("Clipboard write requested for the full artifact text.")

        self._start(copy)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        actions: dict[str, Callable[[], object]] = {
            "previous": self.action_previous_page,
            "next": self.action_next_page,
            "copy": self.action_copy,
            "sensitive": self.action_sensitive,
        }
        name = (event.button.id or "").removeprefix("artifact-")
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
        self._clear()

    async def on_unmount(self) -> None:
        await self.stop_owned()
