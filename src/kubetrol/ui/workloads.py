"""Default-cancel workload review and independently owned progress monitoring."""

import asyncio
from typing import ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kubetrol.domain.connections import ConnectionProblem
from kubetrol.domain.mutations import MutationIntent, MutationState
from kubetrol.domain.workloads import WorkloadAction
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.mutations import MutationManager
from kubetrol.services.processes import _finish_owned
from kubetrol.services.workloads import WorkloadService
from kubetrol.ui.port_forwards import ForwardInput


class WorkloadScreen(ModalScreen[None]):
    AUTO_FOCUS = "#workload-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    WorkloadScreen { align: center middle; background: $background 80%; }
    #workload-form { width: 96%; max-width: 100; height: 94%; max-height: 28;
        border: round $primary; padding: 0 1; background: $surface; }
    #workload-fields { height: 1fr; }
    #workload-fields Static { height: auto; }
    #workload-feedback { height: auto; max-height: 3; }
    #workload-buttons { height: 1; }
    #workload-buttons Button { height: 1; border: none; min-width: 9; }
    #workload-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        source: WorkloadService,
        manager: MutationManager,
        operation: WorkloadAction,
        argument: str = "",
    ) -> None:
        super().__init__()
        self.source, self.manager, self.operation, self.argument = (
            source,
            manager,
            operation,
            argument,
        )
        self.intent: MutationIntent | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._writing = False

    def compose(self) -> ComposeResult:
        target = self.source.target
        with Vertical(id="workload-form"):
            yield Static(self.operation.value + " · captured workload", markup=False)
            with VerticalScroll(id="workload-fields"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nNamespace: {target.namespace}\nResource: {target.resource}/{target.name}\nUID: {target.uid}",
                        multiline=True,
                    ),
                    id="workload-target",
                    markup=False,
                )
                if self.operation in {WorkloadAction.SCALE, WorkloadAction.ROLLBACK}:
                    yield Static(
                        "Replicas (0 stops pods)"
                        if self.operation is WorkloadAction.SCALE
                        else "Explicit retained revision",
                        markup=False,
                    )
                    yield ForwardInput(self.argument, max_length=10, id="workload-argument")
                yield Static("", id="workload-preview", markup=False)
            yield Static(
                "Review before writing. Cancel stops monitoring; it does not undo a server change.",
                id="workload-feedback",
                markup=False,
            )
            with Horizontal(id="workload-buttons"):
                if self.operation is not WorkloadAction.STATUS:
                    yield Button("Review", id="workload-review", compact=True)
                    yield Button(
                        "Confirm",
                        id="workload-confirm",
                        compact=True,
                        disabled=True,
                        variant="warning",
                    )
                yield Button("Cancel", id="workload-cancel", compact=True)

    def on_mount(self) -> None:
        self.set_focus(self.query_one("#workload-cancel", Button))
        if self.operation is WorkloadAction.STATUS:
            self._operation_task = asyncio.create_task(self._monitor())

    def _status(self, text: str) -> None:
        self.query_one("#workload-feedback", Static).update(safe_text(text))

    @on(Input.Changed)
    def changed(self) -> None:
        self.intent = None
        self.query_one("#workload-confirm", Button).disabled = True
        self.query_one("#workload-preview", Static).update("")

    @on(Input.Submitted)
    @on(Button.Pressed, "#workload-review")
    def review(self) -> None:
        if self._writing or (self._operation_task is not None and not self._operation_task.done()):
            return
        self.intent = None
        self.query_one("#workload-confirm", Button).disabled = True
        fields = self.query("#workload-argument")
        argument = fields.first(Input).value if fields else ""
        self._operation_task = asyncio.create_task(self._prepare(argument))

    async def _prepare(self, argument: str) -> None:
        self._status("Reading workload, policy and retained history…")
        try:
            intent = await self.source.prepare(self.operation, argument)
        except (AppError, ConnectionProblem) as error:
            self._status(str(error))
            return
        fields = self.query("#workload-argument")
        if fields and fields.first(Input).value != argument:
            self._status("Input changed during preparation. Review again.")
            return
        self.intent = intent
        self.query_one("#workload-preview", Static).update(
            safe_text(
                f"Version: {intent.resource_version}\n{self.source.preview}\nConfirm sends one conditional patch.",
                multiline=True,
            )
        )
        self.query_one("#workload-confirm", Button).disabled = False
        self.set_focus(self.query_one("#workload-cancel", Button))
        self._status("Review this exact target and effect. Cancel remains the default.")
        self.call_after_refresh(
            self.query_one("#workload-preview", Static).scroll_visible, animate=False
        )

    @on(Button.Pressed, "#workload-confirm")
    def confirm(self) -> None:
        if (
            self.intent is None
            or self._writing
            or (self._operation_task is not None and not self._operation_task.done())
        ):
            return
        try:
            identity = self.manager.start(self.source, self.source.confirm(self.intent))
        except AppError as error:
            self._status(str(error))
            return
        self._writing = True
        self.intent = None
        for field in self.query("Input, #workload-review, #workload-confirm"):
            field.disabled = True
        self._operation_task = asyncio.create_task(self._result(identity))

    async def _result(self, identity: UUID) -> None:
        result = await self.manager.wait(identity)
        self._status(result.state.value + ": " + result.message)
        self._writing = False
        if result.state is MutationState.SUCCEEDED and self.source.resource.name != "replicasets":
            await self._monitor()

    async def _monitor(self) -> None:
        try:
            await self.source.monitor(
                lambda progress: self._status(f"{progress.state}: {progress.message}")
            )
        except (AppError, ConnectionProblem) as error:
            self._status(str(error))

    @on(Button.Pressed, "#workload-cancel")
    async def cancel(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        if self._operation_task is not None:
            if not self._operation_task.done() and not self._operation_task.cancelling():
                self._operation_task.cancel()
            await _finish_owned(asyncio.gather(self._operation_task, return_exceptions=True))

    async def on_unmount(self) -> None:
        await self.stop_owned()
