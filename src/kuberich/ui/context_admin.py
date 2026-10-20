"""Review and save one kubeconfig context rename or deletion."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kuberich.adapters.kubeconfig_files import read_documents, save_plan
from kuberich.domain.kubeconfig_edit import ContextChange, ContextEditPlan, plan_context_edit
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text


@dataclass(frozen=True)
class ContextEditResult:
    plan: ContextEditPlan
    backup: Path


class ContextEditScreen(ModalScreen[ContextEditResult | None]):
    """Review first, then save once. Cancel is the default action."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ContextEditScreen { align: center middle; background: $background 80%; }
    #context-edit-form { width: 96%; max-width: 100; height: auto; max-height: 26;
        border: round $primary; padding: 0 1; background: $surface; }
    #context-edit-fields { height: auto; max-height: 18; }
    #context-edit-fields Static { height: auto; }
    #context-edit-buttons { height: 1; }
    #context-edit-buttons Button { height: 1; border: none; min-width: 9; }
    #context-edit-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        paths: list[Path],
        change: ContextChange,
        name: str,
        *,
        new_name: str = "",
        connected: str | None = None,
    ) -> None:
        super().__init__()
        self.paths, self.change, self.context = paths, change, name
        self.new_name, self.connected = new_name, connected
        self.plan: ContextEditPlan | None = None
        self._edit_task: asyncio.Task[None] | None = None
        self._saving = False

    def compose(self) -> ComposeResult:
        with Vertical(id="context-edit-form"):
            yield Static(f"{self.change.value} context", markup=False)
            with VerticalScroll(id="context-edit-fields"):
                yield Static(safe_text(f"Context: {self.context}"), markup=False)
                if self.change is ContextChange.RENAME:
                    yield Static("New name", markup=False)
                    yield Input(self.new_name, max_length=253, id="context-edit-name")
                yield Static("", id="context-edit-preview", markup=False)
                yield Static("", id="context-edit-prompt", markup=False)
                yield Input(max_length=16, id="context-edit-confirmation")
            yield Static(
                "Review shows exactly which file changes. Nothing is saved before Confirm.",
                id="context-edit-feedback",
                markup=False,
            )
            with Horizontal(id="context-edit-buttons"):
                yield Button("Review", id="context-edit-review", compact=True)
                yield Button(
                    "Confirm",
                    id="context-edit-confirm",
                    compact=True,
                    disabled=True,
                    variant="warning",
                )
                yield Button("Cancel", id="context-edit-cancel", compact=True)

    def on_mount(self) -> None:
        self.query_one("#context-edit-confirmation", Input).display = False
        if self.change is ContextChange.RENAME:
            self.set_focus(self.query_one("#context-edit-name", Input))
        else:
            self.set_focus(self.query_one("#context-edit-review", Button))

    def _status(self, text: str) -> None:
        self.query_one("#context-edit-feedback", Static).update(safe_text(text))

    def _requested_name(self) -> str | None:
        if self.change is ContextChange.DELETE:
            return None
        return self.query_one("#context-edit-name", Input).value

    @on(Input.Changed, "#context-edit-name")
    def name_changed(self) -> None:
        self.plan = None
        self.query_one("#context-edit-confirm", Button).disabled = True
        self.query_one("#context-edit-preview", Static).update("")

    @on(Input.Submitted, "#context-edit-name")
    @on(Button.Pressed, "#context-edit-review")
    def review(self) -> None:
        if self._edit_task is not None and not self._edit_task.done():
            return
        self.plan = None
        self.query_one("#context-edit-confirm", Button).disabled = True
        self._edit_task = asyncio.create_task(self._prepare(self._requested_name()))

    async def _prepare(self, requested: str | None) -> None:
        self._status("Reading kubeconfig files…")
        try:
            documents = await asyncio.to_thread(read_documents, self.paths)
            plan = plan_context_edit(
                documents, self.change, self.context, requested, connected=self.connected
            )
        except AppError as error:
            self._status(f"{error} Nothing was saved.")
            return
        if requested != self._requested_name():
            self._status("The name changed during review. Review again.")
            return
        self.plan = plan
        self.query_one("#context-edit-preview", Static).update(
            safe_text("\n".join(plan.summary), multiline=True)
        )
        confirmation = self.query_one("#context-edit-confirmation", Input)
        prompt = self.query_one("#context-edit-prompt", Static)
        if plan.confirmation is None:
            confirmation.display = False
            prompt.update("")
        else:
            confirmation.value = ""
            confirmation.display = True
            prompt.update(f"Type {plan.confirmation} to confirm")
        self.query_one("#context-edit-confirm", Button).disabled = False
        self._status("Check the file and changes, then Confirm. Cancel keeps everything.")

    @on(Button.Pressed, "#context-edit-confirm")
    def confirm(self) -> None:
        plan = self.plan
        if (
            plan is None
            or self._saving
            or (self._edit_task is not None and not self._edit_task.done())
        ):
            return
        if plan.confirmation is not None and (
            self.query_one("#context-edit-confirmation", Input).value != plan.confirmation
        ):
            self._status(f"Type {plan.confirmation} exactly to confirm.")
            return
        self._saving = True
        for selector in (
            "#context-edit-review",
            "#context-edit-confirm",
            "#context-edit-cancel",
            "#context-edit-name",
            "#context-edit-confirmation",
        ):
            for widget in self.query(selector):
                widget.disabled = True
        self._status("Saving…")
        self._edit_task = asyncio.create_task(self._save(plan))

    async def _save(self, plan: ContextEditPlan) -> None:
        try:
            backup = await asyncio.to_thread(save_plan, plan, datetime.now())
        except AppError as error:
            self._saving = False
            for selector in ("#context-edit-review", "#context-edit-cancel", "#context-edit-name"):
                for widget in self.query(selector):
                    widget.disabled = False
            self.plan = None
            self._status(str(error))
            return
        self.dismiss(ContextEditResult(plan, backup))

    @on(Button.Pressed, "#context-edit-cancel")
    async def action_cancel(self) -> None:
        if self._saving:
            return
        await self.stop_owned()
        self.dismiss(None)

    async def stop_owned(self) -> None:
        task = self._edit_task
        if task is not None and not self._saving:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def on_unmount(self) -> None:
        await self.stop_owned()
