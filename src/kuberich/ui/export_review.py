"""Explicit save review, safe previews and separate destination/disclosure consent."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, cast
from uuid import UUID, uuid4

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.exports import (
    ArtifactRef,
    ExportKind,
    FileOutcome,
    PreparedArtifact,
    ResourceSource,
    SensitiveApproval,
    SupportSource,
)
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.exports import ExportChoices, ExportLease, ExportService
from kuberich.services.ownership import finish_owned
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.read_only_text import ReadOnlyText


class ArtifactConfirmation(ModalScreen[bool]):
    """A distinct, literal, default-cancel acknowledgement for one named action."""

    AUTO_FOCUS = "#artifact-confirm-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel", priority=True)]
    DEFAULT_CSS = """
    ArtifactConfirmation { align: center middle; background: $background 80%; }
    #artifact-confirm-form { width: 94%; max-width: 90; height: 85%; max-height: 24;
        border: solid $warning; padding: 0 1; background: $surface; }
    #artifact-confirm-message { height: 1fr; }
    #artifact-confirm-message Static { height: auto; }
    #artifact-confirm-buttons { height: 1; }
    #artifact-confirm-buttons Button { height: 1; border: none; min-width: 9; }
    """

    def __init__(self, *, message: str, label: str) -> None:
        super().__init__()
        self.message, self.label = message, label

    def compose(self) -> ComposeResult:
        with Vertical(id="artifact-confirm-form"):
            with VerticalScroll(id="artifact-confirm-message"):
                yield Static(safe_text(self.message, multiline=True))
            with Horizontal(id="artifact-confirm-buttons"):
                yield Button(self.label, variant="warning", compact=True, id="artifact-confirm-yes")
                yield Button("Cancel", compact=True, id="artifact-confirm-cancel")

    @on(Button.Pressed, "#artifact-confirm-yes")
    def confirm(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#artifact-confirm-cancel")
    def action_cancel(self) -> None:
        self.dismiss(False)


class ExportReviewScreen(ModalScreen[None]):
    AUTO_FOCUS = "#export-format"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ExportReviewScreen { align: center middle; background: $background 80%; }
    #export-form { width: 98%; height: 96%; border: solid $primary; padding: 0 1;
        background: $surface; }
    #export-title, #export-buttons { height: 1; }
    #export-fields { height: 1fr; min-height: 2; }
    #export-fields Static { height: auto; }
    #export-fields Input, #export-fields Select { height: 3; }
    #export-fields Checkbox { height: 3; border: none; }
    #export-preview { height: 1fr; min-height: 3; }
    #export-status { height: auto; max-height: 2; }
    #export-buttons Button { height: 1; border: none; min-width: 8; }
    """

    def __init__(
        self,
        *,
        subject: ExportChoices | ArtifactRef,
        service: ExportService,
        directory: Path,
        preferred: ExportKind | None = None,
        on_finish: Callable[[FileOutcome | None], None],
    ) -> None:
        super().__init__()
        self.subject, self.service, self.on_finish = subject, service, on_finish
        self._choices = dict(subject) if isinstance(subject, tuple) else {}
        self._kind: ExportKind = (
            preferred if preferred in self._choices else next(iter(self._choices), "screen")
        )
        self._resolved: dict[UUID, ExportLease] = {}
        self._lease: ExportLease | None = None
        self.prepared: PreparedArtifact | None = None
        self._publication: PreparedArtifact | None = None
        self._approval: SensitiveApproval | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._generation = 0
        self._stopped = False
        self._saving = False
        self._confirmation: ArtifactConfirmation | None = None
        self._source_sensitive = False
        self._outcome: FileOutcome | None = None
        self._finished = False
        self.format = Select[ExportKind](
            [(kind, kind) for kind in self._choices] or [("Saved copy", "screen")],
            value=self._kind,
            allow_blank=False,
            disabled=not self._choices,
            id="export-format",
        )
        self._initial_directory = str(directory)
        self.location = ForwardInput(max_length=4096, id="export-directory")
        self.filename = ForwardInput(max_length=255, id="export-filename")
        self.sensitive_choice = Checkbox(
            "Include sensitive values (private file)", id="export-sensitive"
        )
        self.resource_choice = Checkbox(
            "Include selected resource (redacted)", id="export-resource"
        )
        self.logs_choice = Checkbox("Include retained logs (redacted)", id="export-logs")
        self.metadata = Static("", markup=False, id="export-metadata")
        self.viewer = ReadOnlyText(read_only=True, soft_wrap=False, id="export-preview")
        self.status = Static("Preparing a redacted preview…", markup=False, id="export-status")
        self._last_inputs = (str(directory), self._suggest_name(), False, False, False)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def operation_count(self) -> int:
        return len(self._tasks)

    @property
    def sensitive(self) -> bool:
        return any(
            value is not None and value.metadata.sensitive
            for value in (self.prepared, self._publication)
        )

    @property
    def ready_to_save(self) -> bool:
        """The visible fields were processed and all dependent jobs have drained."""
        return (
            self.prepared is not None
            and not self._stopped
            and not self._saving
            and self._input_values() == self._last_inputs
            and not any(not task.done() for task in self._tasks)
        )

    def _suggest_name(self) -> str:
        if isinstance(self.subject, ArtifactRef):
            return "copy-" + self.subject.name
        extension = {"resource-yaml": "yaml", "diagnostics": "json", "support": "json"}.get(
            self._kind, "txt"
        )
        return f"kuberich-{self._kind}.{extension}"

    def compose(self) -> ComposeResult:
        self.location.value = self._initial_directory
        self.filename.value = self._suggest_name()
        with Vertical(id="export-form"):
            yield Static(
                "Save copy"
                if isinstance(self.subject, ArtifactRef)
                else "Export · review frozen source",
                markup=False,
                id="export-title",
            )
            with VerticalScroll(id="export-fields"):
                yield Static("Format", markup=False)
                yield self.format
                yield self.metadata
                yield Static(
                    "Directory · created only by Save for the default location", markup=False
                )
                yield self.location
                yield Static("Filename · one local entry", markup=False)
                yield self.filename
                yield self.resource_choice
                yield self.logs_choice
                yield self.sensitive_choice
            yield self.viewer
            yield self.status
            with Horizontal(id="export-buttons"):
                yield Button(
                    "Save", variant="primary", compact=True, id="export-save", disabled=True
                )
                yield Button("Cancel", compact=True, id="export-cancel")

    def on_mount(self) -> None:
        self._update_options()
        self._start(self._preview)

    def _update_options(self) -> None:
        lease = self._choices.get(self._kind)
        source = lease.capture.source if lease is not None else None
        support = source if isinstance(source, SupportSource) else None
        self.resource_choice.display = support is not None and support.resource is not None
        self.logs_choice.display = support is not None and support.logs is not None
        self.sensitive_choice.disabled = (
            not isinstance(source, ResourceSource) and not self._source_sensitive
        )
        if self.sensitive_choice.disabled:
            self.sensitive_choice.value = False

    def _discard(self) -> None:
        if self.prepared is not None:
            self.service.discard(self.prepared)
            self.prepared = None
        if self._publication is not None:
            self.service.discard(self._publication)
            self._publication = None
        if self._approval is not None:
            self.service.discard(self._approval)
            self._approval = None

    def _start(
        self, operation: Callable[[int], Awaitable[None]], *, retain_preview: bool = False
    ) -> None:
        if self._stopped:
            return
        self._generation += 1
        previous = tuple(self._tasks)
        for task in previous:
            task.cancel()
        generation = self._generation
        task = asyncio.create_task(self._run(previous, operation, generation, retain_preview))
        self._tasks.add(task)
        task.add_done_callback(self._retire)

    async def _run(
        self,
        previous: tuple[asyncio.Task[None], ...],
        operation: Callable[[int], Awaitable[None]],
        generation: int,
        retain_preview: bool,
    ) -> None:
        try:
            await finish_owned(asyncio.gather(*previous, return_exceptions=True))
            if self._current(generation):
                if not retain_preview:
                    self._discard()
                await operation(generation)
        except (AppError, ConnectionProblem) as error:
            if self._current(generation):
                self.status.update(safe_text(str(error)))
        except Exception:
            if self._current(generation):
                self.status.update(
                    "Export operation failed; no artifact content was included in this error."
                )
        finally:
            if self._current(generation):
                self._saving = False
                if self._approval is not None:
                    self.service.discard(self._approval)
                    self._approval = None
                self.query_one("#export-save", Button).disabled = self.prepared is None

    def _retire(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()

    def _current(self, generation: int) -> bool:
        return not self._stopped and self.is_attached and generation == self._generation

    async def _selected_lease(self) -> ExportLease:
        original = self._choices[self._kind]
        lease = self._resolved.get(original.id)
        if lease is None:
            lease = await self.service.resolve(original)
            self._resolved[original.id] = lease
        source = lease.capture.source
        if isinstance(source, SupportSource):
            omissions = (
                *source.omissions,
                *(
                    ("Selected resource omitted by choice",)
                    if source.resource is not None and not self.resource_choice.value
                    else ()
                ),
                *(
                    ("Retained logs omitted by choice",)
                    if source.logs is not None and not self.logs_choice.value
                    else ()
                ),
            )
            lease = replace(
                lease,
                id=uuid4(),
                capture=replace(
                    lease.capture,
                    source=replace(
                        source,
                        resource=source.resource if self.resource_choice.value else None,
                        logs=source.logs if self.logs_choice.value else None,
                        omissions=omissions,
                    ),
                ),
            )
        return lease

    async def _preview(self, generation: int) -> None:
        self.query_one("#export-save", Button).disabled = True
        self.viewer.load_text("")
        self.status.update("Preparing a redacted preview; nothing has been saved.")
        if isinstance(self.subject, ArtifactRef):
            listing = await self.service.scan(self.subject.directory.path)
            self._source_sensitive = any(
                entry.ref.name == self.subject.name
                and entry.metadata is not None
                and entry.metadata.format == "resource-yaml"
                for entry in listing.entries
            )
            prepared = await self.service.read(self.subject, intent="save")
            self._lease = None
        else:
            lease = await self._selected_lease()
            prepared = await self.service.prepare(lease, self._kind)
            self._lease = lease
        if not self._current(generation):
            self.service.discard(prepared)
            return
        self.prepared = prepared
        self._update_options()
        metadata, scope = prepared.metadata, prepared.metadata.scope
        self.metadata.update(
            safe_text(
                f"Context: {scope.context or 'unavailable'}\nHeader namespace: {scope.header_namespace or 'unavailable'} · collection: {scope.collection_namespace or 'unavailable'} ({scope.namespace_mode})\nSource: {scope.source_at.isoformat() if scope.source_at else 'unavailable'}\nRequested: {scope.export_at.isoformat() if scope.export_at else 'unavailable'}\nScope: {scope.kind or scope.resource or 'local'} / {scope.name or 'retained snapshot'}\nFormat: {metadata.format} · default redacted · {prepared.size_bytes} bytes\nInspect before sharing: pattern checks cannot classify arbitrary confidential prose.",
                multiline=True,
            )
        )
        self.viewer.load_text(prepared.preview)
        self.status.update("Redacted preview · inspect before sharing · Save local / Cancel.")

    @on(Select.Changed, "#export-format")
    def format_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK or event.value == self._kind:
            return
        self._kind = cast(ExportKind, event.value)
        self.filename.value = self._suggest_name()
        self._update_options()
        self._last_inputs = self._input_values()
        if self.is_mounted:
            self._start(self._preview)

    def _input_values(self) -> tuple[str, str, bool, bool, bool]:
        return (
            self.location.value,
            self.filename.value,
            self.sensitive_choice.value,
            self.resource_choice.value,
            self.logs_choice.value,
        )

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def input_changed(self) -> None:
        values = self._input_values()
        if values == self._last_inputs:
            return
        destination_only = values[2:] == self._last_inputs[2:]
        self._last_inputs = values
        if self.is_mounted:
            if self._approval is not None:
                self.service.discard(self._approval)
                self._approval = None
            if (
                self._confirmation is not None
                and self._confirmation.is_attached
                and self.app.screen_stack
                and self.app.screen is self._confirmation
            ):
                self._confirmation.dismiss(False)
            self._start(
                self._destination_changed if destination_only else self._preview,
                retain_preview=destination_only,
            )

    async def _destination_changed(self, generation: int) -> None:
        if self.prepared is None or self.prepared.metadata.sensitive:
            self._discard()
            await self._preview(generation)
            return
        if self._lease is not None and not self._lease.current():
            self._discard()
            self.viewer.load_text("")
            raise AppError("Export source changed; close this review and capture it again.")
        self.status.update(
            "Destination changed · redacted source preview retained · Save reviews this destination."
        )

    async def _ask(self, *, message: str, label: str) -> bool:
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        confirmation = ArtifactConfirmation(message=message, label=label)
        self._confirmation = confirmation

        def answered(value: bool | None) -> None:
            if not future.done():
                future.set_result(bool(value))

        self.app.push_screen(confirmation, answered)
        try:
            return await future
        finally:
            if (
                confirmation.is_attached
                and self.app.screen_stack
                and self.app.screen is confirmation
            ):
                confirmation.dismiss(False)
            self._confirmation = None

    @on(Button.Pressed, "#export-save")
    def save(self) -> None:
        if not self.ready_to_save:
            return
        self._saving = True
        self._start(self._save, retain_preview=True)

    async def _save(self, generation: int) -> None:
        self.query_one("#export-save", Button).disabled = True
        if self.prepared is None:
            return
        scope = self.prepared.metadata.scope
        directory, name = Path(self.location.value), self.filename.value
        include_sensitive = self.sensitive_choice.value
        review = await self.service.review_destination(directory, name)
        if review.expected is not None:
            if not await self._ask(
                message=f"Replace this existing local entry?\nDirectory: {review.directory.path}\nFilename: {review.name}\nOnly this named entry is replaced; no automatic retry.",
                label="Replace",
            ):
                self.status.update("Replacement cancelled. No file was written.")
                return
            replacement = await self.service.review_destination(directory, name, replace=True)
            if replacement.directory != review.directory or replacement.expected != review.expected:
                raise AppError("Destination changed after review; review and save again.")
            review = replacement
        if not self._current(generation):
            return
        if include_sensitive:
            if not await self._ask(
                message=f"Save sensitive values in a private local file?\nThis includes the selected object's configuration values, credentials and base64 data.\nContext: {scope.context or 'unavailable'}\nResource: {scope.kind or scope.resource or 'unavailable'} / {scope.collection_namespace or 'cluster'} / {scope.name or 'unavailable'}\nUID: {scope.uid or 'unavailable'} · version: {scope.resource_version or 'unavailable'}\nDirectory: {review.directory.path}\nFilename: {review.name}\nThis one-use acknowledgement applies only to this frozen source and destination. Inspect before sharing.",
                label="Save sensitive",
            ):
                self.status.update("Sensitive save cancelled. No file was written.")
                return
            subject = self.subject if isinstance(self.subject, ArtifactRef) else self._lease
            if subject is None:
                raise AppError("Export source is unavailable; review again.")
            self._approval = await self.service.approve_sensitive(
                subject,
                self._kind if self._lease else "resource-yaml",
                intent="save",
                destination=review,
            )
        if isinstance(self.subject, ArtifactRef):
            prepared = await self.service.read(
                self.subject, intent="save", approval=self._approval, destination=review
            )
        else:
            if self._lease is None:
                raise AppError("Export source is unavailable; review again.")
            prepared = await self.service.prepare(
                self._lease, self._kind, approval=self._approval, destination=review
            )
        self._publication = prepared
        try:
            if not self._current(generation):
                return
            self.status.update("Saving the reviewed local entry…")
            previous_outcome = self.service.last_outcome
            try:
                outcome = await self.service.publish(prepared, review)
            except asyncio.CancelledError:
                late_outcome = self.service.last_outcome
                if (
                    late_outcome is not previous_outcome
                    and late_outcome is not None
                    and late_outcome.ref is not None
                    and late_outcome.ref.directory == review.directory
                    and late_outcome.ref.name == review.name
                ):
                    self._outcome = late_outcome
                raise
            self._outcome = outcome
            if self._current(generation):
                self.status.update(safe_text(outcome.notice or "Export saved locally."))
                await self.action_cancel()
        finally:
            self.service.discard(prepared)
            if self._publication is prepared:
                self._publication = None

    @on(Button.Pressed, "#export-cancel")
    async def action_cancel(self) -> None:
        await self.stop_owned()
        if not self._finished:
            self._finished = True
            self.on_finish(self._outcome)
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        self._generation += 1
        if (
            self._confirmation is not None
            and self._confirmation.is_attached
            and self.app.screen_stack
            and self.app.screen is self._confirmation
        ):
            self._confirmation.dismiss(False)
        current = asyncio.current_task()
        tasks = tuple(task for task in self._tasks if task is not current)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._tasks.difference_update(tasks)
        self._discard()
        self._resolved.clear()
        self._choices.clear()
        if isinstance(self.subject, tuple):
            self.subject = ()
        self._lease = None
        if self.viewer.text:
            if self.app.screen_stack:
                self.viewer.load_text("")
            else:
                self.viewer.document.replace_range((0, 0), self.viewer.document.end, "")

    async def on_unmount(self) -> None:
        await self.stop_owned()
