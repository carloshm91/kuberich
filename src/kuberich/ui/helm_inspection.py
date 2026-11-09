"""Owned Helm inspection, deliberate disclosure and one-use rollback review."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.events import ScreenSuspend
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Static

from kuberich.domain.helm import (
    HelmDisclosureIntent,
    HelmDocumentKind,
    HelmInspection,
    HelmRollbackIntent,
    HelmRollbackOptions,
)
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.ui.chrome import WorkspaceBars, WorkspaceFrame
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.read_only_text import ReadOnlyText

if TYPE_CHECKING:
    from kuberich.services.helm import HelmService


class _OwnedHelmScreen(CommandWorkspace):
    sensitive: ClassVar[bool] = True

    def __init__(self, service: HelmService) -> None:
        super().__init__()
        self.service = service
        self.invalidated = False
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopping: asyncio.Task[None] | None = None

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    def launch(self, operation: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(operation)
        self._tasks.add(task)

        def finished(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            if not done.cancelled() and done.exception() is not None:
                self.show_problem("Helm operation failed; refresh the release before retrying.")

        task.add_done_callback(finished)

    def show_problem(self, message: str) -> None:
        self.query_one(".helm-status", Static).update(safe_text(message))

    def clear_sensitive(self) -> None:
        pass

    async def stop_owned(self) -> None:
        self.invalidated = True
        self.clear_sensitive()
        if self._stopping is None:
            for task in tuple(self._tasks):
                task.cancel()
            self._stopping = asyncio.create_task(self._drain())
        await finish_owned(self._stopping)

    async def _drain(self) -> None:
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self.clear_sensitive()

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()


class HelmInspectionScreen(_OwnedHelmScreen):
    """The service owns targets; revealed text exists only in this viewer."""

    AUTO_FOCUS = "#helm-document"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("1", "page('status')", "Status"),
        Binding("2", "page('notes')", "Notes"),
        Binding("3", "page('values')", "Supplied values"),
        Binding("4", "page('all-values')", "Computed values"),
        Binding("5", "page('manifest')", "Manifest"),
        Binding("6", "page('history')", "History"),
        Binding("r", "reveal", "Reveal / hide"),
    ]
    DEFAULT_CSS = """
    HelmInspectionScreen { layout: vertical; background: $background; }
    #helm-inspection-title, #helm-inspection-buttons, .helm-status { height: 1; }
    #helm-inspection-title { color: $accent; text-overflow: ellipsis; }
    #helm-inspection-buttons Button { height: 1; border: none; min-width: 4; width: 1fr; }
    #helm-document, #helm-revision-history { height: 1fr; min-height: 1; border: none; }
    #helm-revision-history { display: none; }
    .helm-status { text-overflow: ellipsis; }
    """

    def __init__(self, service: HelmService, inspection: HelmInspection) -> None:
        super().__init__(service)
        self.inspection = inspection
        self.page = "status"
        self.revealed = False
        self.selected_revision: int | None = None
        self._document_generation = 0
        self._disclosure_review: HelmDisclosureReviewScreen | None = None
        self.viewer = ReadOnlyText(read_only=True, soft_wrap=False, id="helm-document")
        self.history: DataTable[Text] = DataTable(id="helm-revision-history", cursor_type="row")

    def compose(self) -> ComposeResult:
        key = self.inspection.release.key
        with WorkspaceBars():
            yield Static(
                safe_text(
                    f"Helm · {key.namespace}/{key.name} · revision {self.inspection.release.revision}"
                ),
                id="helm-inspection-title",
            )
            with Horizontal(id="helm-inspection-buttons"):
                for label, page in (
                    ("Status", "status"),
                    ("Notes", "notes"),
                    ("Values", "values"),
                    ("All values", "all-values"),
                    ("Manifest", "manifest"),
                    ("History", "history"),
                    ("Reveal", "reveal"),
                    ("Rollback", "rollback"),
                    ("Back", "back"),
                ):
                    yield Button(label, id="helm-" + page, compact=True)
            yield from self.command_bar()
        with WorkspaceFrame():
            yield self.viewer
            yield self.history
        yield Static(
            "Redacted defaults · 1-6 sections · r deliberate reveal / hide · Esc releases",
            markup=False,
            classes="helm-status",
        )

    def on_mount(self) -> None:
        self.history.add_columns(
            "REVISION", "STATUS", "CHART", "APP VERSION", "UPDATED", "DESCRIPTION"
        )
        for revision in self.inspection.history.revisions:
            self.history.add_row(
                *(
                    safe_text(str(value))
                    for value in (
                        revision.revision,
                        revision.status,
                        revision.chart,
                        revision.app_version,
                        revision.updated or "unavailable",
                        "withheld" if revision.description_present else "none",
                    )
                ),
                key=str(revision.revision),
            )
        self.query_one("#helm-rollback", Button).disabled = True
        self._show_status()

    def _show_status(self) -> None:
        inspection, status = self.inspection, self.inspection.status
        self.viewer.load_text(
            escape_controls(
                "\n".join(
                    (
                        f"Context: {inspection.target.request.scope.session.context}",
                        f"Namespace: {status.key.namespace}",
                        f"Release: {status.key.name}",
                        f"Revision: {status.revision}",
                        f"State: {status.status}",
                        f"Chart: {inspection.release.chart}",
                        f"App version: {inspection.release.app_version}",
                        f"First deployed: {status.first_deployed or 'unavailable'}",
                        f"Last deployed: {status.last_deployed or 'unavailable'}",
                        f"Notes: {'withheld' if status.notes_present else 'none'}",
                        f"Description: {'withheld' if status.description_present else 'none'}",
                        "Hook metadata:",
                        *(
                            f"  {hook.kind}/{hook.name} · {', '.join(hook.events)}"
                            for hook in status.hooks
                        ),
                        "",
                        "Storage identity is checked before reads and operations.",
                        "Rollback revalidation is not atomic compare-and-swap; races and partial effects remain possible.",
                    )
                ),
                allow_newlines=True,
            )
        )

    def clear_sensitive(self) -> None:
        self._document_generation += 1
        self._disclosure_review = None
        self.service.cancel_review()
        self.revealed = False
        self.viewer.load_text("")

    def validate_target(self) -> None:
        if not self.service.current(self.inspection.target.request):
            self.invalidated = True
            self.clear_sensitive()
            self.show_problem(
                "Helm scope changed; close this inspection and select the release again."
            )

    def on_screen_suspend(self, event: ScreenSuspend) -> None:
        # The deliberate review is the only cover that can retain this pending
        # disclosure generation. Any other cover retires even an unfinished read,
        # so returning before its completion cannot restore disclosed content.
        if self.app.screen is self._disclosure_review:
            return
        self.clear_sensitive()
        self.show_problem("Disclosure cleared. Open the section again for its redacted default.")

    def action_page(self, page: str) -> None:
        if self.invalidated:
            return
        self.clear_sensitive()
        self.page = page
        self.history.display = page == "history"
        self.viewer.display = page != "history"
        self.query_one("#helm-reveal", Button).disabled = page in {"status", "history"}
        if page == "status":
            self._show_status()
        elif page == "history":
            self.set_focus(self.history)
            self.show_problem(
                "Select a positive prior revision with Enter before reviewing rollback."
                + (" Older revisions omitted." if not self.inspection.history.complete else "")
            )
        else:
            self.set_focus(self.viewer)
            self.launch(self._load_document(HelmDocumentKind(page), self._document_generation))

    async def _load_document(self, kind: HelmDocumentKind, generation: int) -> None:
        try:
            document = await self.service.document(
                self.inspection.target, self.inspection.release.revision, kind
            )
        except AppError as error:
            if generation == self._document_generation and not self.invalidated:
                self.show_problem(str(error))
            return
        if generation == self._document_generation and not self.invalidated:
            self.viewer.load_text(escape_controls(document.text, allow_newlines=True))
            self.show_problem(
                "Redacted default · r deliberately reveals a fresh read; no export or clipboard integration."
            )

    def action_reveal(self) -> None:
        if self.invalidated or self.page in {"status", "history"}:
            return
        if self.revealed:
            self.action_page(self.page)
            return
        self.launch(
            self._prepare_disclosure(HelmDocumentKind(self.page), self._document_generation)
        )

    async def _prepare_disclosure(self, kind: HelmDocumentKind, generation: int) -> None:
        try:
            intent = await self.service.prepare_disclosure(
                self.inspection.target, self.inspection.release.revision, kind
            )
        except AppError as error:
            self.show_problem(str(error))
            return
        if (
            generation == self._document_generation
            and not self.invalidated
            and self.app.screen is self
        ):
            review = HelmDisclosureReviewScreen(self.service, intent)
            self._disclosure_review = review
            self.app.push_screen(
                review,
                lambda approved: self._disclosure_approved(intent, approved, generation),
            )

    def _disclosure_approved(
        self, intent: HelmDisclosureIntent, approved: bool | None, generation: int
    ) -> None:
        self._disclosure_review = None
        if (
            approved
            and generation == self._document_generation
            and not self.invalidated
            and self.app.screen is self
        ):
            self.launch(self._disclose(intent, generation))

    async def _disclose(self, intent: HelmDisclosureIntent, generation: int) -> None:
        try:
            document = await self.service.disclose(self.service.confirm(intent))
        except AppError as error:
            self.show_problem(str(error))
            return
        if (
            generation == self._document_generation
            and not self.invalidated
            and self.app.screen is self
        ):
            self.viewer.load_text(escape_controls(document.text, allow_newlines=True))
            self.revealed = True
            self.show_problem(
                "REVEALED · r hides · changing section, leaving or switching context clears this text."
            )

    @on(DataTable.RowSelected, "#helm-revision-history")
    def revision_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        revision = int(event.row_key.value or "0")
        item = next(
            (item for item in self.inspection.history.revisions if item.revision == revision), None
        )
        eligible = (
            item is not None
            and 0 < revision < self.inspection.release.revision
            and item.status in {"deployed", "superseded"}
            and self.inspection.status.status in {"deployed", "failed"}
        )
        self.selected_revision = revision if eligible else None
        self.query_one("#helm-rollback", Button).disabled = not eligible
        self.show_problem(
            f"Selected revision {revision}; review rollback options and effects."
            if eligible
            else "This revision is not eligible for rollback; select a positive prior deployed/superseded revision."
        )

    def action_rollback(self) -> None:
        if self.selected_revision is not None and not self.invalidated:
            self.app.push_screen(
                HelmRollbackReviewScreen(self.service, self.inspection, self.selected_revision)
            )

    @on(Button.Pressed)
    async def button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("helm-")
        if name == "back":
            await self.action_back()
        elif name == "reveal":
            self.action_reveal()
        elif name == "rollback":
            self.action_rollback()
        else:
            self.action_page(name)


class HelmDisclosureReviewScreen(ModalScreen[bool]):
    sensitive: ClassVar[bool] = True
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel", priority=True)]
    DEFAULT_CSS = """
    HelmDisclosureReviewScreen { align: center middle; background: $background 80%; }
    #helm-disclosure-review { width: 90%; max-width: 70; height: auto; max-height: 90%; border: solid $warning; padding: 1; }
    #helm-disclosure-review Static { height: auto; }
    #helm-disclosure-review Horizontal { height: 3; }
    """

    def __init__(self, service: HelmService, intent: HelmDisclosureIntent) -> None:
        super().__init__()
        self.service, self.intent = service, intent
        self.approved = False

    def compose(self) -> ComposeResult:
        head, request = self.intent.target.head, self.intent.target.request
        with VerticalScroll(id="helm-disclosure-review"):
            yield Static(
                safe_text(
                    f"Reveal {self.intent.kind.value}\nContext: {request.scope.session.context}\nRelease: {head.key.namespace}/{head.key.name}\nRevision: {self.intent.selected.revision}",
                    multiline=True,
                )
            )
            yield Static(
                "This fresh read may show chart credentials, notes and arbitrary sensitive values. Content is local to this viewer and terminal controls remain escaped.",
                markup=False,
            )
            with Horizontal():
                yield Button("Reveal once", id="helm-disclosure-confirm", variant="warning")
                yield Button("Cancel", id="helm-disclosure-cancel")

    @on(Button.Pressed, "#helm-disclosure-confirm")
    def confirm(self) -> None:
        self.approved = True
        self.dismiss(True)

    @on(Button.Pressed, "#helm-disclosure-cancel")
    def action_cancel(self) -> None:
        self.service.cancel_review()
        self.dismiss(False)

    def on_unmount(self) -> None:
        if not self.approved:
            self.service.cancel_review()


class HelmRollbackReviewScreen(_OwnedHelmScreen):
    AUTO_FOCUS = "#helm-prepare-rollback"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "back", "Cancel", priority=True)]
    DEFAULT_CSS = """
    HelmRollbackReviewScreen { align: center middle; background: $background 80%; }
    #helm-rollback-review { width: 90%; max-width: 84; height: 90%; border: solid $warning; padding: 1; }
    #helm-rollback-review Static { height: auto; }
    #helm-rollback-options { height: auto; }
    #helm-rollback-timeout { height: 3; }
    #helm-rollback-review Horizontal { height: 3; }
    """

    def __init__(self, service: HelmService, inspection: HelmInspection, revision: int) -> None:
        super().__init__(service)
        self.inspection, self.revision = inspection, revision
        self.intent: HelmRollbackIntent | None = None
        self._review_generation = 0

    def compose(self) -> ComposeResult:
        head, request = self.inspection.target.head, self.inspection.target.request
        with VerticalScroll(id="helm-rollback-review"):
            yield Static(
                safe_text(
                    f"Review Helm rollback\nContext: {request.scope.session.context}\nNamespace: {head.key.namespace}\nRelease: {head.key.name}\nCurrent revision: {head.revision}\nSelected target revision: {self.revision}",
                    multiline=True,
                )
            )
            yield Static(
                "Revalidation is not atomic compare-and-swap. Concurrent changes and partial chart resource writes remain possible. Cancellation or timeout after launch may have started is UNKNOWN; never retry automatically. History is retained without pruning.",
                markup=False,
            )
            with VerticalScroll(id="helm-rollback-options"):
                yield Checkbox(
                    "Run rollback hooks (explicit opt-in)", value=False, id="helm-rollback-hooks"
                )
                yield Checkbox("Wait for resources and Jobs", value=True, id="helm-rollback-wait")
                yield Static("Per-operation timeout in seconds (1-600):", markup=False)
                yield Input("300", id="helm-rollback-timeout", type="integer")
            yield Static(
                "Prepare a fresh review before confirming.", classes="helm-status", markup=False
            )
            yield Static("", id="helm-rollback-effects", markup=False)
            with Horizontal():
                yield Button("Prepare review", id="helm-prepare-rollback")
                yield Button(
                    "Confirm rollback", id="helm-confirm-rollback", variant="warning", disabled=True
                )
                yield Button("Cancel", id="helm-cancel-rollback")

    def clear_sensitive(self) -> None:
        self.intent = None
        self.service.cancel_review()
        self._review_generation += 1

    @on(Checkbox.Changed)
    @on(Input.Changed, "#helm-rollback-timeout")
    def options_changed(self) -> None:
        self.clear_sensitive()
        self.query_one("#helm-confirm-rollback", Button).disabled = True
        self.show_problem("Options changed; prepare a fresh review.")

    @on(Button.Pressed, "#helm-prepare-rollback")
    def prepare(self) -> None:
        self.clear_sensitive()
        self.query_one("#helm-confirm-rollback", Button).disabled = True
        self.launch(self._prepare(self._review_generation))

    async def _prepare(self, generation: int) -> None:
        try:
            raw = self.query_one("#helm-rollback-timeout", Input).value
            if not raw.isascii() or not raw.isdigit() or len(raw) > 3:
                raise AppError("Enter a whole-number timeout from 1 to 600 seconds.")
            options = HelmRollbackOptions(
                run_hooks=self.query_one("#helm-rollback-hooks", Checkbox).value,
                wait=self.query_one("#helm-rollback-wait", Checkbox).value,
                timeout_seconds=int(raw),
            )
            intent = await self.service.prepare_rollback(
                self.inspection.target, self.revision, options
            )
        except AppError as error:
            self.show_problem(str(error))
            return
        if not self.invalidated and generation == self._review_generation:
            self.intent = intent
            self.query_one("#helm-rollback-effects", Static).update(
                safe_text("\n".join(intent.effects), multiline=True)
            )
            self.query_one("#helm-confirm-rollback", Button).disabled = False
            self.show_problem(
                "Review prepared. Confirm once to execute the captured target and options."
            )

    @on(Button.Pressed, "#helm-confirm-rollback")
    def confirm(self) -> None:
        intent, self.intent = self.intent, None
        if intent is not None and not self.invalidated:
            self.query_one("#helm-confirm-rollback", Button).disabled = True
            self.query_one("#helm-prepare-rollback", Button).disabled = True
            self.query_one("#helm-rollback-options").disabled = True
            self.launch(self._execute(intent))

    async def _execute(self, intent: HelmRollbackIntent) -> None:
        try:
            result = await self.service.rollback(self.service.confirm(intent))
        except AppError as error:
            self.show_problem(str(error))
            return
        self.show_problem(f"{result.outcome.value.upper()} · {result.message}")
        self.query_one("#helm-prepare-rollback", Button).disabled = True

    @on(Button.Pressed, "#helm-cancel-rollback")
    async def cancel(self) -> None:
        await self.action_back()
