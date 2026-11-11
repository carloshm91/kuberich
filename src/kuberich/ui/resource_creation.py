"""Explicit offline source capture and private editor before separate cluster review."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from kuberich.adapters.editing import file_worker
from kuberich.domain.manifests import FrozenDraftSource, manifest_preview
from kuberich.domain.processes import ProcessStatus
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.services.resource_creation import DraftDisclosureIntent, ResourceCreationService
from kuberich.ui.editing import DisclosureCheckbox
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.read_only_text import ReadOnlyText


class ResourceCreationScreen(ModalScreen[None]):
    AUTO_FOCUS = "#creation-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ResourceCreationScreen { align: center middle; background: $background 80%; }
    #creation-form { width: 98%; height: 96%; border: solid $primary;
        padding: 0 1; background: $surface; }
    #creation-title, #creation-source, #creation-status, #creation-page { height: 1; }
    #creation-file { height: 3; }
    #creation-disclosure { height: auto; }
    #creation-preview { height: 1fr; min-height: 2; }
    #creation-buttons { height: 2; layout: grid; grid-size: 4; grid-rows: 1 1; }
    #creation-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    ResourceCreationScreen.compact #creation-file { height: 1; border: none; padding: 0 1; }
    """

    def __init__(
        self,
        *,
        service: ResourceCreationService,
        runner: ProcessRunner,
        open_review: Callable[[FrozenDraftSource], None],
    ) -> None:
        super().__init__()
        self.service, self.runner, self.open_review = service, runner, open_review
        self.file = ForwardInput(
            placeholder="Explicit local manifest file path", id="creation-file", max_length=4096
        )
        self.viewer = ReadOnlyText("", read_only=True, id="creation-preview")
        self.status = Static(
            "Import is offline. No cluster validation or clipboard read occurs automatically.",
            markup=False,
            id="creation-status",
        )
        self.pages: tuple[str, ...] = ()
        self.page = 0
        self.disclosure: DraftDisclosureIntent | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return (
            int(self._operation_task is not None and not self._operation_task.done())
            + self.service.operation_count
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="creation-form"):
            yield Static("Create resources · offline source", markup=False, id="creation-title")
            yield Static("No source captured", markup=False, id="creation-source")
            yield self.file
            yield DisclosureCheckbox(
                "I allow my trusted editor to receive the full draft, including sensitive values.",
                id="creation-disclosure",
            )
            yield self.viewer
            yield Static("Redacted draft preview", markup=False, id="creation-page")
            yield self.status
            with Horizontal(id="creation-buttons"):
                for label, name in (
                    ("Import file", "import"),
                    ("Edit draft", "edit"),
                    ("Review Create", "review"),
                    ("Stop", "stop"),
                    ("Previous page", "previous"),
                    ("Next page", "next"),
                    ("Back", "back"),
                ):
                    yield Button(label, compact=True, id="creation-" + name)

    def on_mount(self) -> None:
        self.on_resize()
        self._controls()

    def on_resize(self) -> None:
        self.set_class(self.size.height < 28, "compact")

    def _current(self) -> bool:
        return not self._stopped and self.is_attached

    def _controls(self) -> None:
        if not self.viewer.is_attached:
            return
        busy = self._operation_task is not None and not self._operation_task.done()
        source = self.service.current_source
        self.file.disabled = busy or self._stopped
        self.query_one("#creation-import", Button).disabled = busy or self._stopped
        self.query_one("#creation-edit", Button).disabled = (
            busy or self._stopped or self.service.policy.read_only or self.disclosure is None
        )
        self.query_one("#creation-review", Button).disabled = (
            busy or self._stopped or source is None or self.service.policy.read_only
        )
        self.query_one("#creation-disclosure", Checkbox).disabled = (
            busy or self._stopped or self.service.policy.read_only or source is None
        )
        self.query_one("#creation-stop", Button).disabled = not busy
        self.query_one("#creation-previous", Button).disabled = self.page <= 0
        self.query_one("#creation-next", Button).disabled = self.page + 1 >= len(self.pages)

    def _start(self, operation: Callable[[], Awaitable[str]]) -> None:
        if self._stopped or (self._operation_task is not None and not self._operation_task.done()):
            return
        self._operation_task = asyncio.create_task(self._run(operation))
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    async def _run(self, operation: Callable[[], Awaitable[str]]) -> None:
        feedback = ""
        try:
            feedback = await operation()
        except AppError as error:
            feedback = str(error)
        except Exception:
            feedback = "Creation source operation failed; private details withheld."
        finally:
            if self._current():
                self._operation_task = None
                self._controls()
                self.set_focus(self.query_one("#creation-back", Button))
                if feedback:
                    self.status.update(safe_text(feedback))

    def _retired(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        if self._operation_task is task:
            self._operation_task = None
        self._controls()

    async def _show_source(self) -> None:
        source = self.service.current_source
        self.pages = (
            await file_worker(lambda: manifest_preview(None, source.body)) if source else ()
        )
        self.page = 0
        if self._current():
            self.query_one("#creation-source", Static).update(
                safe_text(
                    f"{source.kind.title()} · {len(source.documents)} resources · local syntax passed; server validation not requested"
                    if source
                    else "No source captured"
                )
            )
            self._page()
        self.disclosure = (
            await self.service.prepare_editor()
            if source is not None and not self.service.policy.read_only
            else None
        )

    def _page(self) -> None:
        if self._current():
            self.viewer.load_text(self.pages[self.page] if self.pages else "")
            self.query_one("#creation-page", Static).update(
                f"Redacted draft preview · page {self.page + 1 if self.pages else 0}/{len(self.pages)}"
            )
            self._controls()

    async def _import_file(self) -> str:
        self.disclosure = None
        await self.service.capture_file(Path(self.file.value))
        await self._show_source()
        return "File captured offline · allow fresh editor disclosure or explicitly Review Create."

    async def _edit(self) -> str:
        disclosure, self.disclosure = self.disclosure, None
        if disclosure is None:
            raise AppError("Capture a valid draft before editing.")
        self.query_one("#creation-disclosure", Checkbox).value = False
        command = await self.service.open_editor(self.service.confirm_disclosure(disclosure))
        try:
            result = await terminal_handoff(
                self.app, self.runner, command, guard=self.service.require_editor_current
            )
            changed = await self.service.finish_editor(
                succeeded=result.status is ProcessStatus.SUCCEEDED
            )
            await self._show_source()
            return (
                "Editor cancelled or failed; prior draft retained."
                if result.status is not ProcessStatus.SUCCEEDED
                else "Draft updated · review the redacted preview; validation must be fresh."
                if changed is not None
                else "No changes; prior draft retained."
            )
        finally:
            await self.service.close_draft()
            if self._current() and self.service.current_source is not None:
                self.disclosure = await self.service.prepare_editor()

    @on(Input.Changed, "#creation-file")
    def file_changed(self) -> None:
        if self.is_mounted and self._current():
            self.service.invalidate()
            self.disclosure = None
            self.pages = ()
            self._page()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("creation-")
        if name == "import":
            self._start(self._import_file)
        elif name == "edit":
            if not self.query_one("#creation-disclosure", Checkbox).value:
                self.status.update("Allow fresh editor disclosure before opening the draft.")
            else:
                self._start(self._edit)
        elif name == "review" and self.service.current_source is not None:
            self.open_review(self.service.current_source)
        elif name in {"previous", "next"} and self.pages:
            self.page = max(0, min(len(self.pages) - 1, self.page + (1 if name == "next" else -1)))
            self._page()
        elif name == "stop":
            self.run_worker(self.action_stop())
        elif name == "back":
            self.run_worker(self.action_back())

    async def action_stop(self) -> None:
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        await self.service.close_draft()
        self.disclosure = None
        self._controls()

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        await self.action_stop()
        await self.service.close()
        self.pages = ()
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text("")

    async def on_unmount(self) -> None:
        await self.stop_owned()
