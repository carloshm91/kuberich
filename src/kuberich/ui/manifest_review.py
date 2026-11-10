"""Exact cluster destinations, strict dry-run/diff and explicit batch confirmation."""

import asyncio
from typing import ClassVar, Literal, cast
from uuid import UUID

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Select, Static

from kuberich.domain.manifests import ManifestAction, ManifestPlan
from kuberich.domain.mutations import MutationResult
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from kuberich.services.ownership import finish_owned
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.presentation import FrameTable
from kuberich.ui.read_only_text import ReadOnlyText


class ManifestReviewScreen(ModalScreen[None]):
    AUTO_FOCUS = "#manifest-review-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ManifestReviewScreen { align: center middle; background: $background 80%; }
    #manifest-review-form { width: 98%; height: 96%; border: solid $primary;
        padding: 0 1; background: $surface; }
    #manifest-review-title, #manifest-review-context, #manifest-review-fallback-label,
    #manifest-review-status, #manifest-review-page { height: 1; }
    #manifest-review-fields { height: 3; }
    #manifest-review-action { width: 22; }
    #manifest-review-namespace { width: 1fr; }
    #manifest-review-resources { height: 6; min-height: 3; }
    #manifest-review-preview { height: 1fr; min-height: 2; }
    #manifest-review-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #manifest-review-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    ManifestReviewScreen.compact #manifest-review-fields { height: 1; }
    ManifestReviewScreen.compact #manifest-review-fields Input,
    ManifestReviewScreen.compact #manifest-review-fields Select { height: 1; border: none; padding: 0 1; }
    ManifestReviewScreen.compact #manifest-review-resources { height: 4; }
    """

    def __init__(
        self,
        *,
        service: ManifestMutationService,
        manager: MutationManager,
        action: ManifestAction = "apply",
    ) -> None:
        super().__init__()
        self.service, self.manager = service, manager
        self.action: ManifestAction = action
        self.plan: ManifestPlan | None = None
        self.result: MutationResult | None = None
        self.pages: tuple[str, ...] = ()
        self.page = 0
        self.table: FrameTable[Text] = FrameTable(id="manifest-review-resources", cursor_type="row")
        self.viewer = ReadOnlyText("", read_only=True, id="manifest-review-preview")
        self.namespace = ForwardInput(
            placeholder="Required fallback when workspace is all namespaces",
            id="manifest-review-namespace",
            max_length=63,
        )
        self.action_field: Select[str] = Select(
            (("Apply", "apply"), ("Delete", "delete")),
            value=action,
            allow_blank=False,
            id="manifest-review-action",
        )
        self.status = Static(
            "Validate requests a strict server dry-run; no writes until separate confirmation.",
            markup=False,
            id="manifest-review-status",
        )
        self._generation = 0
        self._operation_task: asyncio.Task[None] | None = None
        self._write: UUID | None = None
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
        scope = self.service.scope
        self.namespace.value = scope.namespace or ""
        with Vertical(id="manifest-review-form"):
            yield Static(
                "Manifest cluster review · Validate / explicit Apply or Delete",
                markup=False,
                id="manifest-review-title",
            )
            yield Static(
                safe_text(
                    f"Context: {scope.session.context} · captured namespace: {scope.namespace or '(all namespaces)'} · {len(self.service.source.documents)} frozen resources"
                ),
                id="manifest-review-context",
            )
            yield Static(
                "Fallback namespace applies only to documents without metadata.namespace",
                markup=False,
                id="manifest-review-fallback-label",
            )
            with Horizontal(id="manifest-review-fields"):
                yield self.action_field
                yield self.namespace
            yield self.table
            yield self.viewer
            yield Static(
                "Redacted preview · select a resource after validation",
                markup=False,
                id="manifest-review-page",
            )
            yield self.status
            with Horizontal(id="manifest-review-buttons"):
                for label, name in (
                    ("Validate", "validate"),
                    ("Confirm " + self.action.title(), "confirm"),
                    ("Stop", "stop"),
                    ("Previous page", "previous"),
                    ("Next page", "next"),
                    ("Back", "back"),
                ):
                    yield Button(
                        label,
                        id="manifest-review-" + name,
                        disabled=name in {"confirm", "stop", "previous", "next"},
                        compact=True,
                    )

    def on_resize(self) -> None:
        self.set_class(self.size.height < 28, "compact")

    def on_mount(self) -> None:
        self.on_resize()
        self.table.add_columns(
            "#",
            "GVR / Kind",
            "Namespace",
            "Name",
            "Action",
            "UID",
            "Version",
            "Validation / outcome",
        )
        self._show_items()
        self._controls()

    def _current(self, generation: int) -> bool:
        return not self._stopped and self.is_attached and generation == self._generation

    def _controls(self) -> None:
        if not self.viewer.is_attached:
            return
        busy = self._operation_task is not None and not self._operation_task.done()
        writing = self._write is not None
        self.action_field.disabled = writing
        self.namespace.disabled = writing
        self.query_one("#manifest-review-validate", Button).disabled = (
            busy or self.service.policy.read_only or self._stopped
        )
        self.query_one("#manifest-review-confirm", Button).disabled = (
            busy
            or self.plan is None
            or not self.plan.ready
            or self.result is not None
            or self.service.policy.read_only
            or self._stopped
        )
        self.query_one("#manifest-review-confirm", Button).label = "Confirm " + self.action.title()
        self.query_one("#manifest-review-stop", Button).disabled = not busy
        self.query_one("#manifest-review-previous", Button).disabled = self.page <= 0
        self.query_one("#manifest-review-next", Button).disabled = self.page + 1 >= len(self.pages)

    def _show_items(self) -> None:
        row, x, y = self.table.cursor_row, self.table.scroll_x, self.table.scroll_y
        self.table.clear()
        plan = self.plan
        results = dict(self.result.items if self.result is not None else self.service.results)
        if plan is None:
            for document in self.service.source.documents:
                self.table.add_row(
                    *(
                        safe_text(value)
                        for value in (
                            str(document.ordinal),
                            document.api_version + " / " + document.kind,
                            document.namespace or self.namespace.value or "(fallback required)",
                            document.name,
                            self.action,
                            "not read",
                            "not read",
                            "Not validated",
                        )
                    ),
                    key=str(document.ordinal),
                )
        else:
            for item in plan.items:
                outcome = results.get(item.target)
                validation = outcome or item.validation
                self.table.add_row(
                    *(
                        safe_text(value)
                        for value in (
                            str(item.document.ordinal),
                            item.resource.api_version
                            + "/"
                            + item.resource.name
                            + " · "
                            + item.resource.kind,
                            item.target.namespace or "(cluster)",
                            item.target.name,
                            item.change,
                            item.target.uid or "new name / no UID captured",
                            item.resource_version
                            or (
                                "absent at review"
                                if item.change == "absent"
                                else "assigned by server on create"
                                if item.change == "create"
                                else "not captured"
                            ),
                            validation.state.value + ": " + validation.message,
                        )
                    ),
                    key=str(item.document.ordinal),
                )
        self.table.move_cursor(
            row=min(row, max(0, self.table.row_count - 1)), animate=False, scroll=False
        )
        self.table.scroll_to(x=x, y=y, animate=False, force=True)
        self._preview()

    def _preview(self) -> None:
        plan, index = self.plan, self.table.cursor_row
        self.pages = (
            plan.items[index].preview_pages
            if plan is not None and 0 <= index < len(plan.items)
            else ()
        )
        self.page = 0
        if plan is not None and 0 <= index < len(plan.items):
            item = plan.items[index]
            outcome = next(
                (
                    result
                    for target, result in (
                        self.result.items if self.result else self.service.results
                    )
                    if target == item.target
                ),
                item.validation,
            )
            self.pages = (
                f"{item.change}: {outcome.state.value}: {outcome.message}\n\n"
                + (
                    self.pages[0]
                    if self.pages
                    else "No object diff; no request body is hidden from the target list."
                ),
                *self.pages[1:],
            )
        self._page()

    def _page(self) -> None:
        self.viewer.load_text(self.pages[self.page] if self.pages else "")
        if not self._stopped and self.viewer.is_attached:
            self.query_one("#manifest-review-page", Static).update(
                f"Redacted server preview / diff · page {self.page + 1 if self.pages else 0}/{len(self.pages)}"
            )
        self._controls()

    def _invalidate(self) -> None:
        self._generation += 1
        self.service.invalidate()
        self.plan = self.result = None
        self.pages = ()
        self.viewer.load_text("")
        if self._operation_task is not None:
            self._operation_task.cancel()
        self._show_items()
        self.status.update("Review fields changed · fresh validation is required.")
        self._controls()

    @on(Input.Changed, "#manifest-review-namespace")
    def namespace_changed(self) -> None:
        if self.is_mounted:
            self._invalidate()

    @on(Select.Changed, "#manifest-review-action")
    def action_changed(self, event: Select.Changed) -> None:
        if event.value in {"apply", "delete"}:
            action = cast(Literal["apply", "delete"], event.value)
            if action != self.action:
                self.action = action
                if self.is_mounted:
                    self._invalidate()

    @on(DataTable.RowHighlighted, "#manifest-review-resources")
    def selected(self) -> None:
        self._preview()

    def action_validate(self) -> None:
        if self._stopped or (self._operation_task is not None and not self._operation_task.done()):
            return
        self._generation += 1
        self.plan = self.result = None
        self._operation_task = asyncio.create_task(self._validate(self._generation))
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    def _retired(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        if self._operation_task is task:
            self._operation_task = None
        self._controls()

    async def _validate(self, generation: int) -> None:
        try:
            self.status.update(
                "Requesting strict server dry-run and redacted diff; no persistence…"
            )
            self.service.set_namespace(self.namespace.value or None)
            plan = await self.service.prepare(self.action)
            if self._current(generation):
                self.plan = plan
                self._show_items()
                self.status.update(
                    "All resources validated · review every destination/diff, then explicitly Confirm "
                    + self.action.title()
                    + "."
                    if plan.ready
                    else "Validation refused one or more resources; no writes are enabled."
                )
        except AppError as error:
            if self._current(generation):
                self.status.update(safe_text(str(error)))
        except Exception:
            if self._current(generation):
                self.status.update("Manifest validation failed; response content was withheld.")
        finally:
            if self._current(generation):
                self._operation_task = None
                self._controls()
                self.set_focus(self.query_one("#manifest-review-back", Button))

    def action_confirm(self) -> None:
        if (
            self._stopped
            or self.plan is None
            or not self.plan.ready
            or self.result is not None
            or (self._operation_task is not None and not self._operation_task.done())
        ):
            return
        try:
            self._write = self.manager.start(self.service, self.service.confirm(self.plan))
        except AppError as error:
            self._invalidate()
            self.status.update(safe_text(str(error)))
            return
        self._operation_task = asyncio.create_task(self._result(self._write, self._generation))
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    async def _result(self, identity: UUID, generation: int) -> None:
        result = await self.manager.wait(identity)
        self.result = result
        if self._current(generation):
            self._show_items()
            self.status.update(safe_text(result.state.value + ": " + result.message))
        self._write = None
        self._operation_task = None
        self._controls()

    async def action_stop(self) -> None:
        self._generation += 1
        identity = self._write
        if identity is not None:
            self.result = await self.manager.cancel(identity)
            self._write = None
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        self.service.invalidate()
        if not self._stopped and self.viewer.is_attached:
            self._show_items()
            self.status.update(
                safe_text(self.result.state.value + ": " + self.result.message)
                if self.result
                else "Validation stopped; fresh validation is required."
            )
            self._controls()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("manifest-review-")
        if name == "validate":
            self.action_validate()
        elif name == "confirm":
            self.action_confirm()
        elif name in {"previous", "next"} and self.pages:
            self.page = max(0, min(len(self.pages) - 1, self.page + (1 if name == "next" else -1)))
            self._page()
        elif name == "stop":
            self.run_worker(self.action_stop())
        elif name == "back":
            self.run_worker(self.action_back())

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        await self.action_stop()
        await self.service.close()
        self.plan = None
        self.pages = ()
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text("")
            self.status.update("Review closed · retained write outcomes remain in :writes.")
            self._controls()

    async def on_unmount(self) -> None:
        await self.stop_owned()
