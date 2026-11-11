"""Public Helm lifecycle review with owned preparation, editor and execution work."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import ScreenSuspend
from textual.widgets import Button, Checkbox, Input, Select, Static

from kuberich.domain.helm_lifecycle import HelmLifecycleKind, HelmLifecycleOptions
from kuberich.domain.processes import ProcessStatus
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.ui.editing import DisclosureCheckbox
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.read_only_text import ReadOnlyText

if TYPE_CHECKING:
    from kuberich.domain.helm import HelmReleaseKey, HelmRequest
    from kuberich.domain.helm_catalog import ChartSnapshot
    from kuberich.domain.helm_lifecycle import (
        HelmLifecycleIntent,
        HelmOperationObservation,
        HelmValuesLease,
    )
    from kuberich.services.helm import HelmService
    from kuberich.services.processes import ProcessRunner


class HelmLifecycleScreen(CommandWorkspace):
    """Every confirmation belongs to one current service review, never a button state."""

    sensitive: ClassVar[bool] = True
    AUTO_FOCUS = "#helm-lifecycle-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    HelmLifecycleScreen { align: center middle; background: $background 80%; }
    #helm-lifecycle-form { width: 98%; height: 96%; border: solid $warning;
        background: $surface; padding: 0 1; }
    #helm-lifecycle-heading { height: auto; max-height: 4; }
    #helm-lifecycle-options { height: 1fr; min-height: 1; max-height: 12; }
    #helm-lifecycle-options Checkbox { height: auto; }
    #helm-lifecycle-options Input, #helm-lifecycle-options Select { height: 3; }
    #helm-lifecycle-preview { height: 1fr; min-height: 1; }
    #helm-lifecycle-status { height: 1; }
    #helm-lifecycle-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #helm-lifecycle-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    HelmLifecycleScreen .nested-command-bar { height: 1; border-top: none; border-bottom: none; }
    """

    def __init__(
        self,
        *,
        service: HelmService,
        request: HelmRequest,
        address: HelmReleaseKey,
        operation: HelmLifecycleKind,
        chart: ChartSnapshot | None = None,
        values: HelmValuesLease | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        super().__init__()
        self.service, self.request, self.address = service, request, address
        self.operation, self.chart, self.values, self.runner = operation, chart, values, runner
        self.intent: HelmLifecycleIntent | None = None
        self.observation: HelmOperationObservation | None = None
        self.invalidated = False
        self.viewer = ReadOnlyText("", read_only=True, soft_wrap=False, id="helm-lifecycle-preview")
        self.status = Static(
            "Prepare native Helm dry-run and a live-state diff before confirming.",
            markup=False,
            id="helm-lifecycle-status",
        )
        self._generation = 0
        self._operation_task: asyncio.Future[Any] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._submitted = False
        self._executing = False

    @property
    def operation_count(self) -> int:
        return int(self._operation_task is not None and not self._operation_task.done())

    def compose(self) -> ComposeResult:
        with Vertical(id="helm-lifecycle-form"):
            yield Static(
                safe_text(
                    f"Review Helm {self.operation.value}\n"
                    f"Context: {self.request.scope.session.context} · "
                    f"Release: {self.address.namespace}/{self.address.name}",
                    multiline=True,
                ),
                id="helm-lifecycle-heading",
            )
            with VerticalScroll(id="helm-lifecycle-options"):
                yield DisclosureCheckbox(
                    "Run lifecycle hooks (explicit opt-in)", id="helm-lifecycle-hooks"
                )
                yield DisclosureCheckbox(
                    "Wait for resources and Jobs", value=True, id="helm-lifecycle-wait"
                )
                yield Input(
                    "300",
                    type="integer",
                    placeholder="Timeout (1-600 seconds)",
                    id="helm-lifecycle-timeout",
                )
                if self.operation is HelmLifecycleKind.UNINSTALL:
                    yield DisclosureCheckbox(
                        "Keep release history", value=True, id="helm-lifecycle-history"
                    )
                    yield Select(
                        [
                            ("Background cascade", "background"),
                            ("Foreground cascade", "foreground"),
                            ("Orphan dependents", "orphan"),
                        ],
                        value="background",
                        allow_blank=False,
                        id="helm-lifecycle-cascade",
                    )
                else:
                    if self.operation is HelmLifecycleKind.UPGRADE:
                        yield DisclosureCheckbox(
                            "Start from fresh current supplied values (otherwise chart defaults)",
                            value=self.values is not None and self.values.source == "supplied",
                            id="helm-lifecycle-supplied",
                        )
                    yield DisclosureCheckbox(
                        "Allow my trusted local editor to receive full values once, including credentials.",
                        id="helm-lifecycle-disclosure",
                    )
            yield self.viewer
            yield self.status
            with Horizontal(id="helm-lifecycle-buttons"):
                if self.operation is not HelmLifecycleKind.UNINSTALL:
                    yield Button("Edit values", id="helm-lifecycle-edit", compact=True)
                yield Button("Prepare review", id="helm-lifecycle-prepare", compact=True)
                yield Button(
                    f"Confirm {self.operation.value}",
                    id="helm-lifecycle-confirm",
                    variant="warning",
                    disabled=True,
                    compact=True,
                )
                yield Button("Stop", id="helm-lifecycle-stop", disabled=True, compact=True)
                yield Button("Back", id="helm-lifecycle-back", compact=True)
            yield from self.command_bar()

    def on_mount(self) -> None:
        self._controls()

    def _controls(self) -> None:
        if not self.viewer.is_attached:
            return
        busy = bool(self.operation_count)
        blocked = self.invalidated or self.service.policy.read_only or self._submitted
        self.query_one("#helm-lifecycle-prepare", Button).disabled = busy or blocked
        self.query_one("#helm-lifecycle-confirm", Button).disabled = (
            busy or blocked or self.intent is None
        )
        self.query_one("#helm-lifecycle-stop", Button).disabled = not busy
        self.query_one("#helm-lifecycle-options").disabled = busy or blocked
        if self.operation is not HelmLifecycleKind.UNINSTALL:
            self.query_one("#helm-lifecycle-edit", Button).disabled = (
                busy or blocked or self.runner is None
            )

    def _message(self, message: str) -> None:
        if self.status.is_attached:
            self.status.update(safe_text(message))

    def _clear_review(self) -> None:
        self._generation += 1
        self.intent = None
        self.service.cancel_review()
        self.viewer.load_text("")

    @on(Checkbox.Changed, "#helm-lifecycle-hooks")
    @on(Checkbox.Changed, "#helm-lifecycle-wait")
    @on(Checkbox.Changed, "#helm-lifecycle-history")
    @on(Input.Changed, "#helm-lifecycle-timeout")
    @on(Select.Changed, "#helm-lifecycle-cascade")
    def options_changed(self) -> None:
        self._clear_review()
        self._controls()
        self._message("Options changed; prepare a fresh review.")

    @on(Checkbox.Changed, "#helm-lifecycle-supplied")
    def values_source_changed(self) -> None:
        self.values = None
        self.options_changed()

    def _options(self) -> HelmLifecycleOptions:
        raw = self.query_one("#helm-lifecycle-timeout", Input).value
        if not raw.isascii() or not raw.isdigit() or len(raw) > 3:
            raise AppError("Enter a whole-number timeout from 1 to 600 seconds.")
        uninstall = self.operation is HelmLifecycleKind.UNINSTALL
        cascade = (
            self.query_one("#helm-lifecycle-cascade", Select).value if uninstall else "background"
        )
        if cascade not in {"background", "foreground", "orphan"}:
            raise AppError("Select an explicit deletion cascade.")
        return HelmLifecycleOptions(
            run_hooks=self.query_one("#helm-lifecycle-hooks", Checkbox).value,
            wait=self.query_one("#helm-lifecycle-wait", Checkbox).value,
            timeout_seconds=int(raw),
            keep_history=self.query_one("#helm-lifecycle-history", Checkbox).value
            if uninstall
            else True,
            cascade=str(cascade),
        )

    async def _values(self) -> HelmValuesLease | None:
        if self.operation is HelmLifecycleKind.UNINSTALL:
            return None
        if self.values is None:
            if self.chart is None:
                raise AppError("Select an exact chart version before preparing Helm values.")
            supplied = (
                self.operation is HelmLifecycleKind.UPGRADE
                and self.query_one("#helm-lifecycle-supplied", Checkbox).value
            )
            self.values = await self.service.create_values(
                self.request,
                self.address,
                self.chart,
                source="supplied" if supplied else "defaults",
            )
        return self.values

    def _launch(self, operation: Awaitable[Any], *, executing: bool = False) -> None:
        self._executing = executing
        self._operation_task = asyncio.ensure_future(operation)
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    def _retired(self, task: asyncio.Future[Any]) -> None:
        if self._operation_task is not task:
            if not task.cancelled():
                task.exception()
            return
        if not self.invalidated:
            if task.cancelled():
                self._message(
                    "Operation stopped. A launched release may have partial effects; refresh before another review."
                )
            elif (error := task.exception()) is not None:
                self._message(
                    str(error)
                    if isinstance(error, AppError)
                    else "Helm operation failed; private chart and values details were withheld."
                )
            elif self._executing:
                self.observation = cast("HelmOperationObservation", task.result())
                self._message(
                    f"{self.observation.outcome.value.upper()} · {self.observation.message}"
                )
        elif not task.cancelled():
            task.exception()
        if self._operation_task is task:
            self._operation_task = None
        self._controls()
        if not self.invalidated and self.viewer.is_attached and self.app.screen is self:
            self.set_focus(self.query_one("#helm-lifecycle-back", Button))

    @on(Button.Pressed, "#helm-lifecycle-prepare")
    def prepare(self) -> None:
        if self.invalidated or self.operation_count or self._submitted:
            return
        self._clear_review()
        self._launch(self._prepare(self._generation))

    async def _prepare(self, generation: int) -> None:
        options = self._options()
        values = await self._values()
        intent = await self.service.prepare_lifecycle(
            self.request,
            self.address,
            self.operation,
            chart=self.chart,
            values=values,
            options=options,
        )
        if generation == self._generation and not self.invalidated and self.app.screen is self:
            self.intent = intent
            self.viewer.load_text(
                escape_controls(
                    "\n".join(
                        (
                            "Native Helm dry-run: " + intent.dry_run,
                            "",
                            *intent.effects,
                            "",
                            intent.preview_text,
                        )
                    ),
                    allow_newlines=True,
                )
            )
            self._message(
                "Review the native dry-run, effects and live-state diff; Confirm applies this review once."
            )

    @on(Button.Pressed, "#helm-lifecycle-confirm")
    def confirm(self) -> None:
        intent, self.intent = self.intent, None
        if intent is None or self.invalidated or self.operation_count or self._submitted:
            return
        self._submitted = True
        try:
            approval = self.service.confirm_lifecycle(intent)
            # Admission consumes authority before any task or await is created.
            operation = self.service.execute_lifecycle(approval)
        except AppError as error:
            self._submitted = False
            self._message(str(error))
            self._controls()
            return
        self._launch(operation, executing=True)

    @on(Button.Pressed, "#helm-lifecycle-edit")
    def edit_values(self) -> None:
        if self.invalidated or self.operation_count or self._submitted or self.runner is None:
            return
        allowed = self.query_one("#helm-lifecycle-disclosure", Checkbox)
        if not allowed.value:
            self._message("Allow one fresh values disclosure before opening your trusted editor.")
            return
        allowed.value = False
        self._clear_review()
        self._message("Opening private Helm values editor…")
        self._launch(self._edit_values(self._generation))

    async def _edit_values(self, generation: int) -> None:
        values = await self._values()
        assert values is not None and self.runner is not None
        edited: HelmValuesLease | None = None
        try:
            intent = await self.service.prepare_values_editor(values)
            command = await self.service.open_values_editor(
                self.service.confirm_values_editor(intent)
            )
            # Native suspension restores the last painted alternate screen.
            # Commit the in-progress state before handing the terminal away.
            await self.wait_for_refresh()
            if generation != self._generation or self.invalidated or self.app.screen is not self:
                raise AppError("Helm values review expired; allow a fresh editor disclosure.")
            result = await terminal_handoff(
                self.app,
                self.runner,
                command,
                guard=self.service.require_values_editor_current,
            )
            if result.status is not ProcessStatus.SUCCEEDED:
                feedback = (
                    "Editor stopped or failed; values were not accepted. Prepare a new review."
                )
            else:
                edited = await self.service.finish_values_editor()
                feedback = (
                    "Edited values accepted privately; prepare a new dry-run and live-state diff."
                )
        finally:
            await self.service.close_values_editor()
        if generation == self._generation and not self.invalidated and self.app.screen is self:
            if edited is not None:
                self.values = edited
            self._message(feedback)

    def validate_target(self) -> None:
        if not self.invalidated and not self.service.current(self.request):
            self.invalidated = True
            self._clear_review()
            if self._operation_task is not None:
                self._operation_task.cancel()
            self._message("Helm scope changed; close this review and select the release again.")
        self._controls()

    async def on_screen_suspend(self, event: ScreenSuspend) -> None:
        self._clear_review()
        await self._stop_operation()
        self._message("Review expired while covered; prepare a fresh review.")

    async def _stop_operation(self) -> None:
        self._clear_review()
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        await self.service.close_values_editor()
        self._controls()

    @on(Button.Pressed, "#helm-lifecycle-stop")
    async def stop(self) -> None:
        await self._stop_operation()

    @on(Button.Pressed, "#helm-lifecycle-back")
    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self.invalidated = True
        if self._stopping is None:
            self._stopping = asyncio.create_task(self._stop_operation())
        await finish_owned(self._stopping)
        self.values = None
        self.chart = None

    async def on_unmount(self) -> None:
        await self.stop_owned()
