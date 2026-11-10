"""Fresh local-editor disclosure and a separate exact local save."""

import asyncio
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from kuberich.domain.manifests import ManifestDisclosureIntent, ManifestSaveIntent
from kuberich.domain.processes import ProcessStatus
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.ui.editing import DisclosureCheckbox
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.read_only_text import ReadOnlyText


class ManifestEditorScreen(ModalScreen[None]):
    AUTO_FOCUS = "#manifest-editor-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ManifestEditorScreen { align: center middle; background: $background 80%; }
    #manifest-editor-form { width: 98%; height: 96%; border: solid $primary;
        padding: 0 1; background: $surface; }
    #manifest-editor-heading, #manifest-editor-file, #manifest-editor-status { height: 1; }
    #manifest-editor-disclosure { height: auto; }
    #manifest-editor-preview { height: 1fr; }
    #manifest-editor-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #manifest-editor-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    """

    def __init__(
        self, *, service: LocalManifestService, runner: ProcessRunner, relative: str
    ) -> None:
        super().__init__()
        self.service, self.runner, self.relative = service, runner, relative
        self.intent: ManifestSaveIntent | None = None
        self.disclosure: ManifestDisclosureIntent | None = None
        self.pages: tuple[str, ...] = ()
        self.page = 0
        self.viewer = ReadOnlyText("", read_only=True, id="manifest-editor-preview")
        self.status = Static("", markup=False, id="manifest-editor-status")
        self._operation_task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return int(self._operation_task is not None and not self._operation_task.done())

    def compose(self) -> ComposeResult:
        with Vertical(id="manifest-editor-form"):
            yield Static(
                "Edit local manifest · Save local is separate from Apply",
                markup=False,
                id="manifest-editor-heading",
            )
            yield Static(safe_text(self.relative), id="manifest-editor-file")
            yield DisclosureCheckbox(
                "I allow my trusted local editor to receive full source bytes, including sensitive values.",
                id="manifest-editor-disclosure",
            )
            yield self.viewer
            yield self.status
            with Horizontal(id="manifest-editor-buttons"):
                for label, name in (
                    ("Open editor", "open"),
                    ("Save local", "save"),
                    ("Previous page", "previous"),
                    ("Next page", "next"),
                    ("Stop", "stop"),
                    ("Back", "back"),
                ):
                    yield Button(
                        label, id="manifest-editor-" + name, disabled=name == "save", compact=True
                    )

    def on_mount(self) -> None:
        self._start("disclose")

    def _controls(self) -> None:
        if self._stopped or not self.viewer.is_attached:
            return
        busy = bool(self.operation_count)
        for name in ("open", "disclosure"):
            self.query_one("#manifest-editor-" + name).disabled = (
                busy or self.service.policy.read_only or self.disclosure is None
            )
        self.query_one("#manifest-editor-save", Button).disabled = (
            busy or self.intent is None or self.service.policy.read_only
        )
        self.query_one("#manifest-editor-stop", Button).disabled = not busy
        self.query_one("#manifest-editor-previous", Button).disabled = self.page <= 0
        self.query_one("#manifest-editor-next", Button).disabled = self.page + 1 >= len(self.pages)

    def _start(self, operation: str) -> None:
        if self._stopped or self.operation_count:
            return
        self._operation_task = asyncio.create_task(self._run(operation))
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    def _retired(self, task: asyncio.Task[None]) -> None:
        if (
            not task.cancelled()
            and task.exception() is not None
            and not self._stopped
            and self.status.is_attached
        ):
            self.status.update("Local editor/save failed; source bytes were withheld.")
        if self._operation_task is task:
            self._operation_task = None
        self._controls()

    async def _run(self, operation: str) -> None:
        feedback = ""
        try:
            if operation == "disclose":
                self.disclosure = await self.service.prepare_editor(self.relative)
                self.query_one("#manifest-editor-file", Static).update(
                    safe_text(f"{self.relative} · SHA256 {self.disclosure.source.sha256}")
                )
                feedback = "Ready · allow fresh disclosure, then open your configured editor."
            elif operation == "open":
                self.intent = None
                self.pages = ()
                self.viewer.load_text("")
                self.status.update("Opening a private local draft…")
                disclosure, self.disclosure = self.disclosure, None
                if self._stopped or disclosure is None:
                    return
                proof = self.service.confirm_disclosure(disclosure)
                self.query_one("#manifest-editor-disclosure", Checkbox).value = False
                command = await self.service.open_editor(proof)
                result = await terminal_handoff(
                    self.app, self.runner, command, guard=self.service.require_editor_current
                )
                if result.status is not ProcessStatus.SUCCEEDED:
                    feedback = "Editor cancelled or failed; local source and cluster are unchanged."
                    return
                self.intent = await self.service.prepare_save()
                self.pages = self.intent.preview_pages if self.intent is not None else ()
                self.page = 0
                self._page()
                feedback = (
                    "Review the redacted diff; Save local replaces only the reviewed file."
                    if self.intent is not None
                    else "No changes; nothing saved locally or sent to the cluster."
                )
            else:
                intent = self.intent
                if intent is None:
                    return
                self.intent = None
                outcome = await self.service.save(self.service.confirm_save(intent))
                feedback = (
                    outcome.notice or "Local source saved; Refresh before cluster validation."
                )
                self.pages = ()
                self.viewer.load_text("")
                self.disclosure = await self.service.prepare_editor(self.relative)
        except asyncio.CancelledError:
            if not self._stopped and self.is_attached:
                cancelled_outcome = self.service.last_file_outcome if operation == "save" else None
                feedback = (
                    cancelled_outcome.notice
                    or "Local source saved; Refresh before cluster validation."
                    if cancelled_outcome is not None and cancelled_outcome.effect == "published"
                    else "Operation stopped; no local save was confirmed."
                )
            raise
        except AppError as error:
            if not self._stopped and self.is_attached:
                feedback = str(error)
        except Exception:
            if not self._stopped and self.is_attached:
                feedback = "Local editor/save failed; source bytes were withheld."
        finally:
            if not self._stopped and self.is_attached:
                task = asyncio.current_task()
                if operation == "open" and task is not None and not task.cancelling():
                    try:
                        self.disclosure = await self.service.prepare_editor(self.relative)
                    except AppError:
                        self.disclosure = None
                self._operation_task = None
                self._controls()
                self.set_focus(self.query_one("#manifest-editor-back", Button))
                if feedback:
                    self.status.update(safe_text(feedback))

    def _page(self) -> None:
        self.viewer.load_text(self.pages[self.page] if self.pages else "")
        self._controls()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("manifest-editor-")
        if name == "open":
            if not self.query_one("#manifest-editor-disclosure", Checkbox).value:
                self.status.update("Allow fresh local disclosure before opening the editor.")
            else:
                self._start("open")
        elif name == "save":
            self._start("save")
        elif name in {"previous", "next"} and self.pages:
            self.page = max(0, min(len(self.pages) - 1, self.page + (1 if name == "next" else -1)))
            self._page()
        elif name == "stop":
            self.run_worker(self._stop_task())
        elif name == "back":
            self.run_worker(self.action_back())

    async def _stop_task(self) -> None:
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        self.intent = None
        self.disclosure = None
        await self.service.close_draft()
        self._controls()

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        await self._stop_task()
        self.pages = ()
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text("")

    async def on_unmount(self) -> None:
        await self.stop_owned()
