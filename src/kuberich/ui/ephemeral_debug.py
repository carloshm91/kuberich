"""Explicit append-only debug reviews, remote sessions and separate local attachment."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from typing import Any, ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.ephemeral_debug import (
    DebugSessionRow,
    EphemeralDebugOptions,
    new_debug_name,
)
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from kuberich.security.presentation import MAX_DISPLAY_CHARACTERS, safe_text
from kuberich.services.ephemeral_debug import (
    EphemeralDebugObservation,
    EphemeralDebugReview,
    EphemeralDebugService,
)
from kuberich.services.mutations import MutationManager
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.terminal import ShellScreen


class EphemeralDebugScreen(ModalScreen[None]):
    AUTO_FOCUS = "#debug-close"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Cancel", show=False, priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    EphemeralDebugScreen { align: center middle; background: $background 80%; }
    #debug-form { width: 98%; max-width: 120; height: 100%;
        border: round $warning; padding: 0 1; background: $surface; }
    #debug-title { height: 1; text-overflow: ellipsis; }
    #debug-scroll { height: 1fr; min-height: 1; }
    #debug-scroll Static { height: auto; }
    #debug-scroll Input { width: 100%; height: 3; }
    #debug-scroll Checkbox { width: 100%; height: auto; min-height: 1; }
    #debug-sessions { height: 8; min-height: 3; }
    #debug-feedback { height: auto; max-height: 2; }
    #debug-buttons { grid-size: 2 2; grid-columns: 1fr 1fr; grid-rows: 1 1; height: 2; }
    #debug-buttons Button { width: 100%; height: 1; border: none;
        min-width: 0; padding: 0 1; }
    #debug-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        owner: EphemeralDebugService,
        mutations: MutationManager,
        processes: ProcessRunner,
        *,
        shell: tuple[str, ...],
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.owner, self.mutations, self.processes = owner, mutations, processes
        self.shell, self.stopped = shell, stopped
        self.review: EphemeralDebugReview | None = None
        self.rows: tuple[DebugSessionRow, ...] = ()
        self.terminal: ShellScreen | None = None
        self._worker: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._write: UUID | None = None
        self._stopping = False
        self._draft = 0
        self._read_only = owner.policy.read_only
        self._failure: Exception | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self.table: DataTable[object] = DataTable(
            id="debug-sessions", cursor_type="row", zebra_stripes=True
        )
        self.summary = Static("Reading debug sessions…", id="debug-observation", markup=False)
        self.preview = Static("", id="debug-preview", markup=False)
        self.outcomes = Static("No local addition attempted.", id="debug-outcomes", markup=False)
        self.feedback = Static(
            "Select an explicit image digest, then Review. Opening this screen adds nothing.",
            id="debug-feedback",
            markup=False,
        )
        self.review_button = Button("Review", id="debug-review", compact=True)
        self.add_button = Button(
            "Add permanently", id="debug-add", compact=True, variant="warning", disabled=True
        )
        self.attach_button = Button("Attach", id="debug-attach", compact=True, disabled=True)
        self.attach_button.tooltip = (
            "Fresh identity and profile validation is required. Append success alone does not "
            "authorize attachment."
        )
        self.cancel_button = Button("Cancel", id="debug-close", compact=True)

    @property
    def busy(self) -> bool:
        return self._worker is not None and not self._worker.done()

    def compose(self) -> ComposeResult:
        target = self.owner.target
        with Vertical(id="debug-form"):
            yield Static("Ephemeral debugging · permanent Pod additions", id="debug-title")
            with VerticalScroll(id="debug-scroll"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nPod: {target.namespace}/{target.name}\n"
                        f"Pod UID: {target.uid}",
                        multiline=True,
                    ),
                    id="debug-target-detail",
                    markup=False,
                )
                yield self.summary
                yield self.table
                yield self.outcomes
                yield Static("New session · explicit image@sha256 digest", markup=False)
                yield ForwardInput("", id="debug-image", max_length=1024)
                yield Static("Unique debug container name", markup=False)
                yield ForwardInput(new_debug_name(), id="debug-name", max_length=63)
                yield Static("Literal command argv · JSON string array", markup=False)
                yield ForwardInput(json.dumps(self.shell), id="debug-command", max_length=16384)
                yield Static("Target: blank = Pod namespaces; or running regular/init name")
                yield ForwardInput("", id="debug-target", max_length=63)
                yield Static("Positive runAsUser / runAsGroup (1-2147483647)", markup=False)
                yield ForwardInput("1000", id="debug-user", type="integer", max_length=10)
                yield ForwardInput("1000", id="debug-group", type="integer", max_length=10)
                yield Checkbox("Read-only root filesystem", value=True, id="debug-root-readonly")
                yield Static(
                    "Add permanently to this Pod's spec. Entries cannot be individually removed "
                    "or restarted, including completed entries. No resource reservations or limits; "
                    "debugging can pressure this Pod. Detach may leave the remote process running.\n"
                    "Nonprivileged Linux profile: non-root, no privilege escalation, drop ALL "
                    "capabilities, RuntimeDefault seccomp. No workload environment, mounts or token "
                    "mounts are copied. Inherited Pod namespaces, security and image-pull context "
                    "are shown in the review. Tools requiring root, ptrace or writable filesystems "
                    "may fail. Named-target process visibility depends on the runtime; fresh "
                    "checks cannot eliminate the final name-based attach race. "
                    "Startup waiting stops after 60s; the addition remains permanent.",
                    id="debug-limits",
                    markup=False,
                )
                yield self.preview
            yield self.feedback
            with Grid(id="debug-buttons"):
                yield self.review_button
                yield self.add_button
                yield self.attach_button
                yield self.cancel_button

    def on_mount(self) -> None:
        if self._stopping:
            return
        for key, label in (
            ("name", "Name"),
            ("state", "Remote state"),
            ("reason", "Reason / exit"),
            ("origin", "Local outcome"),
            ("image", "Image"),
        ):
            self.table.add_column(label, key=key)
        self._unsubscribe = self.owner.subscribe(self._receive)
        self._receive(self.owner.observation)
        self.set_interval(0.2, self.validate_target)
        try:
            self.owner.start()
        except AppError as error:
            self.status(str(error))
            self.request_stop()
        if self._read_only:
            self.status("Read-only inspection. Review, permanent additions and attach are blocked.")

    def status(self, value: str) -> None:
        if self.feedback.is_attached:
            self.feedback.update(safe_text(value))

    def _start_work(self, work: Coroutine[Any, Any, None]) -> None:
        self._worker = asyncio.create_task(work)
        self._worker.add_done_callback(self._work_finished)
        self._buttons()

    def _work_finished(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and isinstance(error := task.exception(), Exception):
            self._fail(error)

    def _receive(self, observation: EphemeralDebugObservation) -> None:
        try:
            self.observed(observation)
        except Exception as error:
            self._fail(error)

    def _fail(self, error: Exception) -> None:
        if self._failure is None:
            self._failure = error
        self.request_stop()

    def selected(self) -> DebugSessionRow | None:
        name = (
            self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
            if self.table.row_count
            else None
        )
        return next((row for row in self.rows if row.name == name), None)

    def _buttons(self, *, finishing: bool = False) -> None:
        blocked = self._stopping or self.owner.policy.read_only or (self.busy and not finishing)
        self.review_button.disabled = blocked
        self.add_button.disabled = blocked or self.review is None
        if blocked:
            self.attach_button.disabled = True
            return
        row, observation = self.selected(), self.owner.observation
        unverified = row is not None and any(
            item.name == row.name and item.result.state is not MutationState.SUCCEEDED
            for item in observation.outcomes
        )
        self.attach_button.disabled = (
            blocked
            or self.terminal is not None
            or observation.stale
            or row is None
            or row.state != "running"
            or unverified
        )

    def observed(self, observation: EphemeralDebugObservation) -> None:
        if not self.is_mounted or self._stopping:
            return
        table, remote = self.table, observation.remote
        selected = self.selected()
        x, y = table.scroll_x, table.scroll_y
        if remote is not None:
            self.rows = remote.rows
            names = {row.name for row in self.rows}
            for key in tuple(table.rows):
                if key.value not in names:
                    table.remove_row(key)
            for row in self.rows:
                outcome = next(
                    (item for item in reversed(observation.outcomes) if item.name == row.name), None
                )
                values = (
                    row.name,
                    row.state,
                    " · ".join(
                        value
                        for value in (
                            row.reason or "",
                            f"exit {row.exit_code}" if row.exit_code is not None else "",
                        )
                        if value
                    ),
                    outcome.result.state.value if outcome is not None else "Observed existing",
                    row.image,
                )
                cells = tuple(safe_text(value) for value in values)
                if row.name not in table.rows:
                    table.add_row(*cells, key=row.name)
                else:
                    for column, cell in zip(table.columns, cells, strict=True):
                        if table.get_cell(row.name, column) != cell:
                            table.update_cell(row.name, column, cell, update_width=True)
            if selected is not None and selected.name in names:
                table.move_cursor(row=table.get_row_index(selected.name), scroll=False)
            table.scroll_to(x=x, y=y, animate=False, immediate=True, force=True)
        freshness = "STALE — prior rows retained" if observation.stale else "current"
        age = (
            f" · observed {max(0, time.time() - observation.observed_at):.0f}s ago"
            if observation.observed_at is not None
            else " · no successful observation"
        )
        count = "unknown" if remote is None else str(len(remote.rows))
        incomplete = " · INCOMPLETE (first 256 sessions)" if remote and remote.incomplete else ""
        self.summary.update(
            safe_text(
                f"Observation: {freshness} · {observation.code}{age}\n"
                f"Debug sessions: {count}{incomplete} · Local attachment: "
                f"{observation.attaching or 'none'}. Remote completion requires terminated status. "
                "Append success alone does not authorize attachment.",
                multiline=True,
            )
        )
        if observation.outcomes:
            self.outcomes.update(
                safe_text(
                    "\n".join(
                        f"{item.name}: append {item.result.state.value} · {item.result.message}"
                        for item in observation.outcomes
                    ),
                    multiline=True,
                )
            )
        self._buttons()

    @on(DataTable.RowHighlighted, "#debug-sessions")
    def selection_changed(self) -> None:
        self._buttons()

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def changed(self) -> None:
        self._draft += 1
        self.review = None
        self.add_button.disabled = True
        if self.preview.is_attached:
            self.preview.update("Options changed. A new server dry-run is required.")

    def options(self) -> EphemeralDebugOptions:
        try:
            command = json.loads(self.query_one("#debug-command", Input).value)
            if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
                raise ValueError
            user = int(self.query_one("#debug-user", Input).value)
            group = int(self.query_one("#debug-group", Input).value)
        except (ValueError, RecursionError):
            raise AppError(
                "Use a JSON string-array command and positive integer user/group."
            ) from None
        return EphemeralDebugOptions(
            self.query_one("#debug-name", Input).value,
            self.query_one("#debug-image", Input).value,
            tuple(command),
            self.query_one("#debug-target", Input).value or None,
            user,
            group,
            self.query_one("#debug-root-readonly", Checkbox).value,
        )

    @on(Button.Pressed, "#debug-review")
    def prepare(self) -> None:
        if self.busy or self._stopping or self.owner.policy.read_only:
            return
        self.review = None
        self.add_button.disabled = True
        self._start_work(self._prepare(self._draft))

    async def _prepare(self, draft: int) -> None:
        self.status(
            "Checking fresh Pod identity and strict server dry-run; no addition is persisted…"
        )
        try:
            review = await self.owner.prepare(self.options())
            if self._stopping or draft != self._draft or review.intent.options != self.options():
                self.status("Options changed during preparation. Review the current options again.")
                return
            intent, target = review.intent, review.intent.target
            instance = intent.target_instance
            content = (
                f"Add permanently to this Pod's spec\nContext: {target.session.context}\n"
                f"Pod: {target.namespace}/{target.name} · UID {target.uid}\n"
                f"Reviewed resourceVersion: {intent.resource_version}\n"
                f"Target instance: {instance if instance is not None else 'Pod namespaces'}\n"
                "Admitted profile (strict dry-run; ordinary defaults included):\n"
                + json.dumps(json.loads(review.profile), ensure_ascii=False, indent=2)
                + "\nInherited Pod context (metadata only):\n"
                + json.dumps(json.loads(intent.inherited), ensure_ascii=False, indent=2)
            )
            if len(content) > MAX_DISPLAY_CHARACTERS:
                raise AppError(
                    "Complete debug review exceeds the 16384-character display limit. "
                    "Shorten the command or choose a Pod with less inherited metadata."
                )
            self.preview.update(safe_text(content, multiline=True))
            self.review = review
            self.cancel_button.focus()
            self.status(
                "Server dry-run admitted. Review the profile; Add permanently requires a separate action."
            )
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError) as error:
            self.status("Review unavailable: " + (str(error) or "The request timed out."))
        finally:
            self._buttons(finishing=True)

    @on(Button.Pressed, "#debug-add")
    def add(self) -> None:
        review = self.review
        if self.busy or self._stopping or review is None:
            return
        self.review = None
        self.add_button.disabled = True
        try:
            if review.intent.options != self.options():
                raise AppError("Options changed.")
            self._write = self.mutations.start(self.owner, self.owner.confirm(review))
        except AppError:
            self.status("The options, target or policy changed. Prepare a fresh review.")
            return
        self.cancel_button.focus()
        self.status("Adding once permanently; startup waiting is separate from the append outcome…")
        self._start_work(self._result(self._write))

    async def _result(self, identity: UUID) -> None:
        try:
            result = await self.mutations.wait(identity)
            if not self._stopping:
                self.status(f"Append/startup result: {result.state.value} · {result.message}")
                self.observed(self.owner.observation)
        finally:
            self._buttons(finishing=True)

    @on(Button.Pressed, "#debug-attach")
    def attach(self) -> None:
        row = self.selected()
        if self.busy or self._stopping or self.attach_button.disabled or row is None:
            return
        self._start_work(self._open_terminal(row.name))

    async def _open_terminal(self, name: str) -> None:
        try:
            shell, request = await self.owner.prepare_shell(name)
            if self._stopping:
                return
            self.terminal = ShellScreen(
                shell,
                self.processes,
                request,
                heading="KubeRich · Ephemeral debug attach · existing remote process",
            )
            self.app.push_screen(self.terminal, self._returned)
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError) as error:
            self.status("Attach unavailable: " + (str(error) or "The request timed out."))
        finally:
            self._buttons(finishing=True)

    def _returned(self, result: str | None) -> None:
        self.terminal = None
        self.status(
            (result or "Terminal returned.")
            + " Local closure does not establish remote completion; inspect the remote state."
        )
        if self.is_mounted and not self._stopping:
            self.cancel_button.focus()
            self._buttons()

    def validate_target(self) -> None:
        if self._stopping:
            return
        try:
            self.owner.require_observable()
            if self.owner.policy.read_only and not self._read_only:
                raise AppError("Policy tightened; local debug work is closing.")
        except AppError:
            self.request_stop()
        self._buttons()

    def request_stop(self) -> None:
        self._stopping = True
        self.review = None
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        try:
            if self.terminal is not None:
                self.terminal.close_shell()
            self._buttons()
        except Exception as error:
            if self._failure is None:
                self._failure = error

    async def _stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self.terminal is not None:
            await self.terminal.stop_owned()
        if self._write is not None:
            await self.mutations.cancel(self._write)
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            await finish_owned(asyncio.gather(self._worker, return_exceptions=True))
        await self.owner.stop_owned()
        try:
            self.status(
                "Closed locally. No debug entry was removed; a remote process may remain running."
            )
        except Exception as error:
            if self._failure is None:
                self._failure = error
        self.stopped()
        if self._failure is not None:
            try:
                raise self._failure
            except Exception as error:
                self.app._handle_exception(error)

    async def stop_owned(self) -> None:
        self.request_stop()
        assert self._stop_task is not None
        await finish_owned(self._stop_task)

    @on(Button.Pressed, "#debug-close")
    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_mounted and self.app.screen is self:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()
