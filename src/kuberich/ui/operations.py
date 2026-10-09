"""Explicit target selection, default-cancel review and retained per-item results."""

import asyncio
from typing import ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, SelectionList, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.mutations import MutationIntent
from kuberich.domain.operations import DeleteOptions, ResourceAction, ResourceIntent
from kuberich.domain.workloads import replica_count
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.mutations import MutationManager
from kuberich.services.operations import BatchDeleteService, BatchIntent, ResourceOperationService
from kuberich.services.processes import _finish_owned
from kuberich.ui.mutations import result_text
from kuberich.ui.port_forwards import ForwardInput


class ResourceOperationScreen(ModalScreen[None]):
    AUTO_FOCUS = "#operation-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ResourceOperationScreen { align: center middle; background: $background 80%; }
    #operation-form { width: 96%; max-width: 110; height: 94%; max-height: 36;
        border: round $primary; padding: 0 1; background: $surface; }
    #operation-fields { height: 1fr; }
    #operation-fields Static { height: auto; }
    #operation-targets { height: 8; min-height: 3; }
    #operation-feedback { height: auto; max-height: 3; }
    #operation-buttons { height: 1; }
    #operation-buttons Button { height: 1; border: none; min-width: 9; }
    #operation-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        sources: tuple[ResourceOperationService, ...],
        manager: MutationManager,
        *,
        batch: bool = False,
    ) -> None:
        super().__init__()
        self.sources, self.manager, self.is_batch = sources, manager, batch
        self.action = sources[0].action
        self.source: ResourceOperationService | BatchDeleteService | None = None
        self.intent: ResourceIntent | MutationIntent | BatchIntent | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._writing = False
        self._fields: tuple[tuple[int, ...], str, str] | None = None

    def compose(self) -> ComposeResult:
        target = self.sources[0].target
        with Vertical(id="operation-form"):
            yield Static(self.action.value + " · captured resources", markup=False)
            with VerticalScroll(id="operation-fields"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nAPI: {target.group or 'core'}/{target.resource}",
                        multiline=True,
                    ),
                    id="operation-context",
                    markup=False,
                )
                if self.is_batch:
                    yield Static(
                        "Space toggles exact targets; nothing is selected automatically.",
                        markup=False,
                    )
                    yield SelectionList[int](
                        *(
                            (
                                safe_text(
                                    f"{s.target.namespace or '(cluster)'}/{s.target.name} · UID {s.target.uid}"
                                ),
                                i,
                            )
                            for i, s in enumerate(self.sources)
                        ),
                        id="operation-targets",
                    )
                else:
                    yield Static(
                        safe_text(
                            f"Namespace: {target.namespace or '(cluster scoped)'}\nResource: {target.name}\nUID: {target.uid}",
                            multiline=True,
                        ),
                        id="operation-target",
                        markup=False,
                    )
                if self.action is ResourceAction.DELETE:
                    yield Static("Propagation: Foreground / Background / Orphan", markup=False)
                    yield ForwardInput("Foreground", max_length=10, id="operation-propagation")
                    yield Static(
                        "Grace seconds (blank = server default; 0 may stop pods immediately)",
                        markup=False,
                    )
                    yield ForwardInput(max_length=10, id="operation-grace")
                    yield Static(
                        "Confirm the reviewed count by typing DELETE <count>", markup=False
                    )
                    yield ForwardInput(max_length=10, id="operation-count")
                yield Static("", id="operation-preview", markup=False)
            yield Static(
                "Review identities and consequences before confirming.",
                id="operation-feedback",
                markup=False,
            )
            with Horizontal(id="operation-buttons"):
                yield Button("Review", id="operation-review", compact=True)
                yield Button(
                    "Confirm",
                    id="operation-confirm",
                    compact=True,
                    disabled=True,
                    variant="warning",
                )
                yield Button("Cancel", id="operation-cancel", compact=True)

    def _status(self, text: str) -> None:
        self.query_one("#operation-feedback", Static).update(safe_text(text))

    def _capture_fields(self) -> tuple[tuple[int, ...], str, str]:
        indices = tuple(sorted(self.query_one(SelectionList).selected)) if self.is_batch else (0,)
        propagation, grace = "Foreground", ""
        if self.action is ResourceAction.DELETE:
            propagation = self.query_one("#operation-propagation", Input).value
            grace = self.query_one("#operation-grace", Input).value
        return indices, propagation, grace

    @on(SelectionList.SelectedChanged)
    @on(Input.Changed)
    def changed(self, event: SelectionList.SelectedChanged[int] | Input.Changed) -> None:
        if isinstance(event, Input.Changed) and event.input.id == "operation-count":
            return
        self.intent = None
        self.query_one("#operation-confirm", Button).disabled = True
        self.query_one("#operation-preview", Static).update("")

    @on(Button.Pressed, "#operation-review")
    def review(self) -> None:
        if self._operation_task is not None and not self._operation_task.done():
            return
        self.intent = None
        self.query_one("#operation-confirm", Button).disabled = True
        fields = self._capture_fields()
        self._operation_task = asyncio.create_task(self._prepare(fields))

    async def _prepare(self, fields: tuple[tuple[int, ...], str, str]) -> None:
        indices, propagation, grace = fields
        self._status("Reading selected identities and versions…")
        try:
            options = DeleteOptions(propagation, replica_count(grace) if grace else None)
            source: ResourceOperationService | BatchDeleteService = (
                BatchDeleteService(tuple(self.sources[i] for i in indices))
                if self.is_batch
                else self.sources[0]
            )
            intent = await source.prepare(options)
        except (AppError, ConnectionProblem):
            self._status(
                "Review failed. Check selection, options, identity and permissions; no write started."
            )
            return
        if fields != self._capture_fields():
            self._status("Selection/options changed. Review again; no write started.")
            return
        self.source, self.intent, self._fields = source, intent, fields
        count = len(indices)
        notes = {
            ResourceAction.DELETE: f"Delete {count} captured target(s). Controllers may recreate pods; storage/namespaces may cascade. Finalizers are never removed. Batch writes are independent.",
            ResourceAction.TRIGGER: "Creates an independent manual Job from the reviewed template, even when the CronJob is suspended. Schedule/concurrency policies are not enforced for this manual run. Source revalidation and Job creation are separate API requests.",
            ResourceAction.SUSPEND: "CronJob: stops future scheduling, not existing Jobs. Job: Kubernetes terminates its active pods.",
            ResourceAction.RESUME: "CronJob: missed schedules may run immediately. Job: resumes execution and may reset its start time.",
        }
        self.query_one("#operation-preview", Static).update(
            safe_text(notes[self.action] + "\n" + "\n".join(intent.effects), multiline=True)
        )
        self.query_one("#operation-confirm", Button).disabled = False
        self.set_focus(self.query_one("#operation-cancel", Button))
        self._status(f"Review this exact operation; {count} target(s). Cancel is the default.")
        self.call_after_refresh(
            self.query_one("#operation-preview", Static).scroll_visible, animate=False
        )

    @on(Button.Pressed, "#operation-confirm")
    def confirm(self) -> None:
        if (
            self.intent is None
            or self.source is None
            or self._writing
            or (self._operation_task is not None and not self._operation_task.done())
        ):
            return
        if self._fields != self._capture_fields():
            self._status("Selection/options changed. Review again.")
            return
        if (
            self.action is ResourceAction.DELETE
            and self.query_one("#operation-count", Input).value != f"DELETE {len(self._fields[0])}"
        ):
            self._status(f"Type DELETE {len(self._fields[0])} to confirm the exact reviewed count.")
            return
        try:
            if isinstance(self.source, BatchDeleteService):
                assert isinstance(self.intent, BatchIntent)
                proof = self.source.confirm(self.intent)
            else:
                assert isinstance(self.intent, (ResourceIntent, MutationIntent))
                proof = self.source.confirm(self.intent)
            identity = self.manager.start(self.source, proof)
        except AppError:
            self._status(
                "Captured identity or policy changed. Select/review again; no write started."
            )
            return
        self._writing, self.intent = True, None
        for selector in (
            "#operation-review",
            "#operation-confirm",
            "#operation-targets",
            "#operation-propagation",
            "#operation-grace",
            "#operation-count",
        ):
            for widget in self.query(selector):
                widget.disabled = True
        self._status("Sending reviewed operation(s) once. Results remain in :writes.")
        self._operation_task = asyncio.create_task(self._result(identity))

    async def _result(self, identity: UUID) -> None:
        result = await self.manager.wait(identity)
        self._status(result.state.value + ": " + result.message)
        self.query_one("#operation-preview", Static).update(result_text(result))
        self.query_one("#operation-cancel", Button).label = "Back"
        self._writing = False

    @on(Button.Pressed, "#operation-cancel")
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
