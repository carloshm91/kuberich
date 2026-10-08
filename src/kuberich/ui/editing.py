"""Deliberate editor disclosure, redacted diff, server validation and separate Apply."""

import asyncio
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.mutations import MutationState
from kuberich.domain.processes import ProcessStatus
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.editing import EditingService
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner, _finish_owned
from kuberich.ui.handoff import terminal_handoff


class DisclosureCheckbox(Checkbox):
    # Apply disclosure before the next priority focus binding. A bubbled toggle
    # otherwise uses the newer focus when keys arrive in one terminal packet.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter,space", "toggle_button", "Toggle", show=False, priority=True),
    ]


class EditingScreen(ModalScreen[None]):
    AUTO_FOCUS = "#edit-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    EditingScreen { align: center middle; background: $background 80%; }
    #edit-form { width: 98%; height: 96%; border: round $primary; padding: 0 1;
        background: $surface; }
    #edit-title, #edit-feedback, #edit-buttons { height: 1; text-overflow: ellipsis; }
    #edit-scroll { height: 1fr; }
    #edit-scroll Static { height: auto; }
    #edit-disclosure { height: auto; }
    #edit-buttons Button { height: 1; border: none; min-width: 7;
        background: $surface; color: $text; }
    #edit-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        source: EditingService,
        manager: MutationManager,
        runner: ProcessRunner,
        environment: dict[str, str],
        directory: Path,
    ) -> None:
        super().__init__()
        self.source, self.manager, self.runner = source, manager, runner
        self.environment, self.directory = dict(environment), directory
        self._operation_task: asyncio.Task[None] | None = None
        self._writing = False

    def compose(self) -> ComposeResult:
        target = self.source.target
        with Vertical(id="edit-form"):
            yield Static("Edit manifest · review / validate / apply", id="edit-title", markup=False)
            with VerticalScroll(id="edit-scroll"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nNamespace: {target.namespace or '(cluster)'}\nResource: {target.resource}/{target.name}\nUID: {target.uid}",
                        multiline=True,
                    ),
                    id="edit-target",
                )
                yield DisclosureCheckbox(
                    "I allow my trusted local editor to receive the full manifest, including sensitive values.",
                    id="edit-disclosure",
                )
                yield Static(
                    "Status/managedFields are omitted. Identity is immutable. Preview hides sensitive values. Draft is deleted on close.",
                    id="edit-diff",
                    markup=False,
                )
            yield Static(
                "No server changes until separate Apply.", id="edit-feedback", markup=False
            )
            with Horizontal(id="edit-buttons"):
                yield Button("Editor", id="edit-open", compact=True)
                yield Button("Validate", id="edit-validate", disabled=True, compact=True)
                yield Button("Apply", id="edit-apply", disabled=True, compact=True)
                yield Button("Cancel", id="edit-cancel", compact=True)

    def _status(self, text: str) -> None:
        self.query_one("#edit-feedback", Static).update(safe_text(text))

    def on_mount(self) -> None:
        self.set_focus(self.query_one("#edit-cancel", Button))
        self._status("Ready · allow local disclosure, then open your configured editor.")

    def _busy(self) -> bool:
        return self._writing or (
            self._operation_task is not None and not self._operation_task.done()
        )

    @on(Button.Pressed, "#edit-open")
    def open_editor(self) -> None:
        if self._busy():
            return
        if not self.query_one("#edit-disclosure", Checkbox).value:
            self._status("Allow local disclosure above before opening your editor.")
            return
        self.query_one("#edit-apply", Button).disabled = True
        self.query_one("#edit-validate", Button).disabled = True
        self._operation_task = asyncio.create_task(self._edit())

    async def _edit(self) -> None:
        self._status("Opening the captured manifest in your configured editor…")
        try:
            await self.source.open()
            command = self.source.command(self.environment, self.directory)
            result = await terminal_handoff(
                self.app, self.runner, command, guard=self.source.require_current
            )
            if result.status is not ProcessStatus.SUCCEEDED:
                self._status(
                    "Editor cancelled or failed; no PATCH sent. Reopen or close the draft."
                )
                return
            intent, preview = await self.source.prepare()
            version = (
                self.source.snapshot.resource_version if self.source.snapshot else "unavailable"
            )
            self.query_one("#edit-diff", Static).update(
                safe_text(f"Resource version: {version}\n{preview}", multiline=True)
            )
            self.call_after_refresh(
                self.query_one("#edit-diff", Static).scroll_visible, animate=False
            )
            self.query_one("#edit-validate", Button).disabled = intent is None
            self.set_focus(self.query_one("#edit-cancel", Button))
            self._status(
                "No semantic changes; no PATCH sent."
                if intent is None
                else "Review the redacted diff. Validate sends a non-persisting server dry-run."
            )
        except (AppError, ConnectionProblem) as error:
            self._status(f"Edit refused: {error}")

    @on(Button.Pressed, "#edit-validate")
    def validate(self) -> None:
        if not self._busy() and self.source.intent is not None:
            self.query_one("#edit-apply", Button).disabled = True
            self._operation_task = asyncio.create_task(self._validate())

    async def _validate(self) -> None:
        self._status("Requesting strict server dry-run; no persistence…")
        result = await self.source.validate()
        self.query_one("#edit-apply", Button).disabled = result.state is not MutationState.SUCCEEDED
        self.set_focus(self.query_one("#edit-cancel", Button))
        self._status(f"{result.state.value}: {result.message}")

    @on(Button.Pressed, "#edit-apply")
    def apply(self) -> None:
        intent = self.source.intent
        if self._busy() or intent is None:
            return
        try:
            proof = self.source.confirm(intent)
            identity = self.manager.start(self.source, proof)
        except AppError:
            self._status("This exact target/change needs a fresh successful validation.")
            return
        self._writing = True
        for name in ("open", "validate", "apply", "disclosure"):
            self.query_one(f"#edit-{name}").disabled = True
        self._operation_task = asyncio.create_task(self._result(identity))

    async def _result(self, identity: UUID) -> None:
        result = await self.manager.wait(identity)
        self._status(f"{result.state.value}: {result.message}")
        self.query_one("#edit-cancel", Button).label = "Back"
        self._writing = False

    @on(Button.Pressed, "#edit-cancel")
    async def cancel(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        if self._operation_task is not None:
            if not self._operation_task.done() and not self._operation_task.cancelling():
                self._operation_task.cancel()
            await _finish_owned(asyncio.gather(self._operation_task, return_exceptions=True))
        await self.source.close_file()

    async def on_unmount(self) -> None:
        await self.stop_owned()
