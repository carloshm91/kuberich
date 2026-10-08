"""Explicit annotation form, captured confirmation and owned write feedback."""

import asyncio
from typing import ClassVar
from uuid import UUID

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.mutations import MutationIntent, MutationResult
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.mutations import MutationManager, MutationService
from kuberich.services.processes import _finish_owned
from kuberich.ui.port_forwards import ForwardInput


def result_text(result: MutationResult) -> Text:
    """Bound each item independently so large batches do not hide later outcomes."""
    content = safe_text(
        result.message.split("\n", 1)[0] if result.items else result.message, multiline=True
    )
    for target, item in result.items:
        content.append_text(
            safe_text(
                f"\n{target.namespace or '(cluster)'}/{target.name} · UID {target.uid}\n"
                + item.state.value
                + ": "
                + item.message,
                multiline=True,
            )
        )
    return content


class AnnotationScreen(ModalScreen[None]):
    AUTO_FOCUS = "#annotation-key"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    AnnotationScreen { align: center middle; background: $background 80%; }
    #annotation-form { width: 96%; max-width: 100; height: 94%; max-height: 27;
        border: round $primary; padding: 0 1; background: $surface; }
    #annotation-title { height: 1; text-overflow: ellipsis; }
    #annotation-fields { height: 1fr; }
    #annotation-fields Static { height: auto; }
    #annotation-feedback { height: auto; max-height: 3; }
    #annotation-buttons { height: 1; }
    #annotation-buttons Button { height: 1; border: none; min-width: 9;
        background: $surface; color: $text; }
    #annotation-buttons Button:focus { background: $primary; color: $background;
        text-style: bold; }
    AnnotationScreen.short #annotation-feedback { height: 1; text-overflow: ellipsis; }
    """

    def __init__(self, source: MutationService, manager: MutationManager) -> None:
        super().__init__()
        self.source, self.manager = source, manager
        self.intent: MutationIntent | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._writing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="annotation-form"):
            yield Static(
                "Set annotation · review before writing", id="annotation-title", markup=False
            )
            with VerticalScroll(id="annotation-fields"):
                target = self.source.target
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nNamespace: {target.namespace or '(cluster scoped)'}\nResource: {target.resource}/{target.name}\nUID: {target.uid}",
                        multiline=True,
                    ),
                    id="annotation-target",
                )
                yield Static("Annotation key", markup=False)
                yield ForwardInput(
                    placeholder="example.io/key", max_length=317, id="annotation-key"
                )
                yield Static("Annotation value", markup=False)
                yield ForwardInput(max_length=65536, id="annotation-value")
                yield Static("", id="annotation-preview", markup=False)
            yield Static(
                "Read-only, UID and version guards apply. Values are omitted from history.",
                id="annotation-feedback",
                markup=False,
            )
            with Horizontal(id="annotation-buttons"):
                yield Button("Review", id="annotation-review", variant="primary", compact=True)
                yield Button(
                    "Confirm",
                    id="annotation-confirm",
                    variant="warning",
                    compact=True,
                    disabled=True,
                )
                yield Button("Cancel", id="annotation-cancel", compact=True)

    def _status(self, text: str) -> None:
        self.query_one("#annotation-feedback", Static).update(safe_text(text))

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.height < 20, "short")

    @on(Input.Changed)
    def changed(self) -> None:
        self.intent = None
        self.query_one("#annotation-confirm", Button).disabled = True
        self.query_one("#annotation-preview", Static).update("")

    @on(Input.Submitted)
    @on(Button.Pressed, "#annotation-review")
    def review(self) -> None:
        if self._operation_task is not None and not self._operation_task.done():
            return
        self.intent = None
        self.query_one("#annotation-confirm", Button).disabled = True
        key = self.query_one("#annotation-key", Input).value
        value = self.query_one("#annotation-value", Input).value
        self._operation_task = asyncio.create_task(self._prepare(key, value))

    async def _prepare(self, key: str, value: str) -> None:
        self._status("Reading the captured object before confirmation…")
        try:
            intent = await self.source.prepare_annotation(key, value)
        except (AppError, ConnectionProblem):
            self._status(
                "Cannot prepare this change. Check key, size, connection and target permissions; no write started."
            )
            return
        if (
            key != self.query_one("#annotation-key", Input).value
            or value != self.query_one("#annotation-value", Input).value
        ):
            self._status("Fields changed during preparation. Review the current fields again.")
            return
        self.intent = intent
        self.query_one("#annotation-preview", Static).update(
            safe_text(
                f"Version: {intent.resource_version}\nEffect: set {key} = {value}\nExisting annotations are retained. Click Confirm to send one conditional patch.",
                multiline=True,
            )
        )
        self.query_one("#annotation-confirm", Button).disabled = False
        # Review/Enter never performs a write. Cancel remains the default focus.
        self.set_focus(self.query_one("#annotation-cancel", Button))
        self._status("Review the captured context, identity, version and effect above.")
        self.call_after_refresh(
            self.query_one("#annotation-preview", Static).scroll_visible, animate=False
        )

    @on(Button.Pressed, "#annotation-confirm")
    def confirm(self) -> None:
        if (
            self.intent is None
            or self._writing
            or (self._operation_task is not None and not self._operation_task.done())
        ):
            return
        try:
            proof = self.source.confirm(self.intent)
            identity = self.manager.start(self.source, proof)
        except AppError:
            self._status(
                "The captured target or policy changed. Select and review again; no write started."
            )
            return
        self._writing = True
        self.intent = None
        for selector in (
            "#annotation-key",
            "#annotation-value",
            "#annotation-review",
            "#annotation-confirm",
        ):
            self.query_one(selector).disabled = True
        self._status("Sending one guarded patch… leaving this view does not repeat it.")
        self._operation_task = asyncio.create_task(self._result(identity))

    async def _result(self, identity: UUID) -> None:
        result = await self.manager.wait(identity)
        self._status(f"{result.state.value}: {result.message}")
        self.query_one("#annotation-cancel", Button).label = "Back"
        self._writing = False

    @on(Button.Pressed, "#annotation-cancel")
    async def cancel(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        """Drain preparation/result waiters before their captured client closes."""
        if self._operation_task is not None:
            if not self._operation_task.done() and not self._operation_task.cancelling():
                self._operation_task.cancel()
            await _finish_owned(asyncio.gather(self._operation_task, return_exceptions=True))

    async def on_unmount(self) -> None:
        await self.stop_owned()


class MutationHistoryScreen(ModalScreen[None]):
    AUTO_FOCUS = "#write-history-scroll"
    DEFAULT_CSS = """
    MutationHistoryScreen { layout: vertical; background: $background; }
    #write-history-title, #write-history-back { height: 1; }
    #write-history-scroll { height: 1fr; border: round $primary; padding: 0 1; }
    #write-history-content { height: auto; }
    #write-history-back { border: none; }
    """

    def __init__(self, manager: MutationManager) -> None:
        super().__init__()
        self.manager = manager

    def compose(self) -> ComposeResult:
        yield Static(
            "Writes · last 32 operations · uncertain results require inspection",
            id="write-history-title",
            markup=False,
        )
        with VerticalScroll(id="write-history-scroll"):
            yield Static("", id="write-history-content", markup=False)
        yield Button("Back", id="write-history-back", compact=True)

    def on_mount(self) -> None:
        self.refresh_records()
        self.set_interval(0.2, self.refresh_records)

    def refresh_records(self) -> None:
        content = Text()
        for record in reversed(self.manager.records):
            target = record.target
            state = (
                record.result.state.value if record.result is not None else "Sending / revalidating"
            )
            content.append_text(
                safe_text(
                    f"{target.session.context} · {target.namespace or '(cluster)'} · {target.resource}/{target.name}\nUID {target.uid}\n{state}: ",
                    multiline=True,
                )
            )
            content.append_text(
                result_text(record.result)
                if record.result is not None
                else Text("Waiting for one request outcome.")
            )
            for effect in record.effects:
                content.append_text(safe_text("\n" + effect, multiline=True))
            content.append("\n\n")
        self.query_one("#write-history-content", Static).update(
            content if content else Text("No writes in this application session.")
        )

    @on(Button.Pressed, "#write-history-back")
    def back(self) -> None:
        self.dismiss()
