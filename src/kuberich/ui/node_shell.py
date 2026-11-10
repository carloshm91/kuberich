"""Deliberate node diagnostic review and retained, drained terminal ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.mutations import MutationResult
from kuberich.domain.node_shell import NodeShellIntent
from kuberich.domain.node_shell_journal import JournalRecord
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import MutationManager
from kuberich.services.node_shell import NodeShellManager, NodeShellService, NodeShellState
from kuberich.services.node_shell_recovery import NodeShellRecovery, RecoveryReview
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.ui.terminal import ShellScreen


class NodeShellScreen(ModalScreen[None]):
    AUTO_FOCUS = "#node-shell-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Cancel", show=False, priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    NodeShellScreen { align: center middle; background: $background 80%; }
    #node-shell-form { width: 96%; max-width: 112; height: 94%; max-height: 38;
        border: round $warning; padding: 0 1; background: $surface; }
    #node-shell-scroll { height: 1fr; }
    #node-shell-scroll Static { height: auto; }
    #node-shell-feedback { height: auto; max-height: 4; }
    #node-shell-buttons { height: 1; }
    #node-shell-buttons Button { height: 1; border: none; min-width: 8; }
    #node-shell-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        owner: NodeShellService,
        mutations: MutationManager,
        processes: ProcessRunner,
        *,
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.owner, self.mutations, self.processes = owner, mutations, processes
        self.stopped = stopped
        self.intent: NodeShellIntent | None = None
        self.started = False
        self.terminal: ShellScreen | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._write: UUID | None = None
        self._stopping = False
        self.feedback = Static(
            "Checking the captured Node, existing namespace and server dry-run…",
            id="node-shell-feedback",
            markup=False,
        )
        self.preview = Static("", id="node-shell-preview", markup=False)
        self.create_button = Button(
            "Create and open",
            id="node-shell-create",
            variant="warning",
            compact=True,
            disabled=True,
        )
        self.cancel_button = Button("Cancel", id="node-shell-cancel", compact=True)
        self._failure_reported = False

    @property
    def busy(self) -> bool:
        return not self.is_mounted or self._worker_task is None or not self._worker_task.done()

    def compose(self) -> ComposeResult:
        node, settings = self.owner.node, self.owner.settings
        with Vertical(id="node-shell-form"):
            yield Static("Node shell · privileged Linux diagnostic container", markup=False)
            with VerticalScroll(id="node-shell-scroll"):
                yield Static(
                    safe_text(
                        f"Context: {node.session.context}\nNode: {node.name}\nNode UID: {node.uid}\n"
                        f"Namespace: {settings.namespace}\nImage: {settings.image}\n"
                        f"Requests: CPU {settings.requests.cpu}, memory {settings.requests.memory}\n"
                        f"Limits: CPU {settings.limits.cpu}, memory {settings.limits.memory}\n"
                        "Privileges: root UID/GID 0, privileged, host PID / IPC / network\n"
                        "Host mount: / → /host, read-write, no mount propagation\n"
                        "Service account token: not mounted; service links: disabled\n"
                        f"Startup deadline: {settings.startup_timeout_seconds}s · "
                        f"Session deadline: {settings.session_timeout_seconds}s\n"
                        f"Container PID 1: /bin/sleep {settings.session_timeout_seconds}\n"
                        "Shell: /bin/sh in the diagnostic container; no automatic chroot\n"
                        "Scheduling: required Node affinity; no taint or cordon bypass\n"
                        "This grants host root access. Resource limits do not sandbox host activity.\n"
                        "Cleanup deletes only the Pod UID returned by this create. "
                        "An unreachable Node can leave cleanup pending.",
                        multiline=True,
                    ),
                    id="node-shell-profile",
                    markup=False,
                )
                yield self.preview
            yield self.feedback
            with Horizontal(id="node-shell-buttons"):
                yield self.create_button
                yield self.cancel_button

    def on_mount(self) -> None:
        self._worker_task = asyncio.create_task(self._prepare())

    def status(self, text: str) -> None:
        if self.feedback.is_attached:
            self.feedback.update(safe_text(text))

    def outcome(self) -> str:
        observation = self.owner.observation
        return f"Node shell: {observation.state.value} · {observation.code}."

    async def _prepare(self) -> None:
        try:
            intent = await self.owner.prepare()
            if self._stopping:
                return
            self.intent = intent
            self.preview.update(
                safe_text(
                    f"Pod: {intent.settings.namespace}/{intent.pod_name}\n"
                    f"Namespace UID: {intent.namespace_uid}\n"
                    f"Profile SHA-256: {intent.profile_digest}\nServer dry-run: admitted unchanged.",
                    multiline=True,
                )
            )
            self.create_button.disabled = False
            self.status("Review the exact profile. Create and open requires a deliberate action.")
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError) as error:
            self.status("Node-shell review failed: " + (str(error) or "The request timed out."))
            await self._close_owner()
        except Exception as error:
            await self._close_owner()
            self.app._handle_exception(error)

    @on(Button.Pressed, "#node-shell-create")
    def create(self) -> None:
        if self.started or self._stopping or self.busy or self.intent is None:
            return
        self.started = True
        self.create_button.disabled = True
        try:
            self._write = self.mutations.start(self.owner, self.owner.confirm(self.intent))
        except AppError:
            self.status("The reviewed target or policy changed. Cancel and review again.")
            return
        self.status("Creating one diagnostic Pod; waiting for its admitted container…")
        self._worker_task = asyncio.create_task(self._open(self._write))

    async def _open(self, identity: UUID) -> None:
        try:
            result = await self.mutations.wait(identity)
            try:
                self.owner.raise_failure()
            except AppError as error:
                self._report_failure(error)
                return
            if self._stopping:
                return
            if self.owner.observation.state is not NodeShellState.READY:
                self.status(
                    f"{result.message} {self.outcome()} Use :node-shell-recover for pending records."
                )
                return
            shell, request = await self.owner.shell()
            if self._stopping:
                await self._close_owner()
                return
            node, intent = self.owner.node, self.intent
            assert intent is not None
            self.terminal = ShellScreen(
                shell,
                self.processes,
                request,
                heading="KubeRich · Node diagnostic shell · no automatic chroot",
                target_detail=(
                    f"Node: {node.name} · Diagnostic Pod: {intent.settings.namespace}/{intent.pod_name}"
                ),
            )
            self.app.push_screen(self.terminal, self._returned)
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError) as error:
            await self._close_owner()
            self.status(
                self.outcome()
                + " "
                + (str(error) or "Shell preparation timed out.")
                + " Review pending cleanup locally."
            )
        except Exception as error:
            await self._close_owner()
            self.app._handle_exception(error)

    def _report_failure(self, error: Exception) -> None:
        if not self._failure_reported:
            self._failure_reported = True
            self.app._handle_exception(error)

    async def _close_owner(self) -> None:
        try:
            await self.owner.close()
        except Exception as error:
            self._report_failure(error)

    def _returned(self, result: str | None) -> None:
        self.terminal = None
        try:
            self.owner.raise_failure()
        except AppError as error:
            self._report_failure(error)
            return
        self.status((result or "Terminal returned.") + " " + self.outcome())
        if self.is_mounted:
            button = self.cancel_button
            button.label = "Close"
            button.focus()

    def validate_target(self) -> None:
        if self._stopping or self.owner.observation.state in {
            NodeShellState.CLOSED,
            NodeShellState.PENDING,
        }:
            return
        try:
            self.owner.require_current()
        except AppError:
            self.request_stop()

    def request_stop(self) -> None:
        """Stop input synchronously, then retain the screen through owned drainage."""
        self._stopping = True
        if self.is_mounted:
            self.create_button.disabled = True
        if self.terminal is not None:
            self.terminal.close_shell()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._stop())

    async def _stop(self) -> None:
        try:
            if self.terminal is not None:
                await self.terminal.stop_owned()
            if self._write is not None:
                await self.mutations.cancel(self._write)
            if self._worker_task is not None and not self._worker_task.done():
                self._worker_task.cancel()
                await finish_owned(asyncio.gather(self._worker_task, return_exceptions=True))
            await self._close_owner()
            self.status(self.outcome())
        finally:
            self.stopped()

    async def stop_owned(self) -> None:
        self.request_stop()
        assert self._close_task is not None
        await finish_owned(self._close_task)

    @on(Button.Pressed, "#node-shell-cancel")
    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_mounted:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()


class NodeShellRecoveryScreen(ModalScreen[None]):
    """Local records first; cluster inspection and each cleanup remain explicit."""

    AUTO_FOCUS = "#node-recovery-cancel"
    BINDINGS: ClassVar[list[BindingType]] = NodeShellScreen.BINDINGS
    DEFAULT_CSS = """
    NodeShellRecoveryScreen { align: center middle; background: $background 80%; }
    #node-recovery-form { width: 96%; max-width: 114; height: 94%; max-height: 38;
        border: round $primary; padding: 0 1; background: $surface; }
    #node-recovery-table { height: 1fr; min-height: 3; }
    #node-recovery-detail { height: 1fr; min-height: 2; }
    #node-recovery-detail Static { height: auto; }
    #node-recovery-feedback { height: auto; max-height: 4; }
    #node-recovery-buttons, #node-recovery-review-buttons { height: 1; }
    #node-recovery-form Button { height: 1; border: none; min-width: 7; padding: 0 1; }
    #node-recovery-form Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        manager: NodeShellManager,
        policy: AccessPolicy,
        connection: Callable[[], tuple[KubernetesSession, SessionIdentity] | None],
        session_current: Callable[[KubernetesSession, SessionIdentity], bool],
        *,
        scan: Callable[[], Awaitable[tuple[JournalRecord, ...]]],
        records_changed: Callable[[tuple[JournalRecord, ...]], None],
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.manager, self.policy = manager, policy
        self.connection, self.session_current = connection, session_current
        self.records_changed, self.stopped = records_changed, stopped
        self.scan = scan
        self.records: tuple[JournalRecord, ...] = ()
        self.owner: NodeShellRecovery | None = None
        self.review: RecoveryReview | None = None
        self._connection: tuple[KubernetesSession, SessionIdentity] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._confirming = False
        self.table: DataTable[object] = DataTable(
            id="node-recovery-table", cursor_type="row", zebra_stripes=True
        )
        self.preview = Static(
            "Select a record. Unknown create UIDs can only be inspected or forgotten locally. No context is connected automatically.",
            id="node-recovery-preview",
            markup=False,
        )
        self.feedback = Static(
            "Reading private local recovery records…", id="node-recovery-feedback", markup=False
        )
        self.confirm_button = Button(
            "Confirm", id="node-recovery-confirm", compact=True, disabled=True, variant="warning"
        )
        self.cancel_button = Button("Cancel", id="node-recovery-cancel", compact=True)

    @property
    def busy(self) -> bool:
        return not self.is_mounted or self._worker_task is None or not self._worker_task.done()

    def compose(self) -> ComposeResult:
        with Vertical(id="node-recovery-form"):
            yield Static(
                "Node-shell recovery · local metadata only until explicit Inspect or Cleanup",
                markup=False,
            )
            yield self.table
            with VerticalScroll(id="node-recovery-detail"):
                yield self.preview
            yield self.feedback
            with Horizontal(id="node-recovery-buttons"):
                yield Button("Inspect", id="node-recovery-inspect", compact=True)
                yield Button("Cleanup", id="node-recovery-cleanup", compact=True)
                yield Button("Forget", id="node-recovery-forget", compact=True)
                yield Button("Reload", id="node-recovery-reload", compact=True)
            with Horizontal(id="node-recovery-review-buttons"):
                yield self.confirm_button
                yield self.cancel_button

    def on_mount(self) -> None:
        self.table.add_columns("Context", "Node", "Namespace / Pod", "Ownership", "Status")
        self._worker_task = asyncio.create_task(self._reload())

    def status(self, text: str) -> None:
        if self.feedback.is_attached:
            self.feedback.update(safe_text(text))

    def selected(self) -> JournalRecord | None:
        table = self.table
        return self.records[table.cursor_row] if 0 <= table.cursor_row < len(self.records) else None

    def invalidate_review(self) -> None:
        self.review = None
        if self.is_mounted:
            self.confirm_button.disabled = True

    @on(DataTable.RowHighlighted, "#node-recovery-table")
    def selection_changed(self) -> None:
        if self._confirming:
            return
        self.invalidate_review()
        record = self.selected()
        if record is not None:
            self.preview.update(
                safe_text(
                    f"Context: {record.context}\nNode: {record.node_name} · UID {record.node_uid}\n"
                    f"Namespace: {record.namespace} · UID {record.namespace_uid}\n"
                    f"Pod: {record.pod_name}\nReturned UID: {record.pod_uid or '(unknown; never adopted)'}\n"
                    f"State: {record.state.value} · {record.result_code}\n"
                    "Cleanup requires an explicitly connected matching context and namespace UID. "
                    "Forget removes only this local record and does not clean up a remote Pod.",
                    multiline=True,
                )
            )

    @on(Button.Pressed, "#node-recovery-reload")
    def reload(self) -> None:
        if not self.busy and not self._stopping:
            self.invalidate_review()
            self._worker_task = asyncio.create_task(self._reload())

    async def _release(self) -> None:
        owner, self.owner = self.owner, None
        self.review = None
        if owner is not None:
            await owner.close()

    async def _reload(self) -> None:
        try:
            await self._release()
            self.records = await self.scan()
            if self._stopping:
                return
            self.records_changed(self.records)
            table = self.table
            selected = (
                table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                if table.row_count
                else None
            )
            table.clear()
            for record in self.records:
                table.add_row(
                    safe_text(record.context),
                    safe_text(record.node_name),
                    safe_text(f"{record.namespace}/{record.pod_name}"),
                    "Known UID" if record.pod_uid is not None else "Unknown UID",
                    safe_text(f"{record.state.value} · {record.result_code}"),
                    key=record.operation_id,
                )
            if selected is not None and any(
                record.operation_id == selected for record in self.records
            ):
                table.move_cursor(
                    row=next(
                        i
                        for i, record in enumerate(self.records)
                        if record.operation_id == selected
                    )
                )
            self.status(
                f"{len(self.records)} local record(s). No cluster request was made by listing."
            )
        except asyncio.CancelledError:
            raise
        except AppError as error:
            self.status(str(error))
        except Exception as error:
            await self._release()
            self.app._handle_exception(error)

    @on(Button.Pressed, "#node-recovery-inspect")
    def inspect(self) -> None:
        self.start_review("inspect")

    @on(Button.Pressed, "#node-recovery-cleanup")
    def cleanup(self) -> None:
        self.start_review("cleanup")

    @on(Button.Pressed, "#node-recovery-forget")
    def forget(self) -> None:
        self.start_review("forget")

    def start_review(self, action: str) -> None:
        if self.busy or self._stopping:
            return
        record = self.selected()
        if record is None:
            self.status("Select a local recovery record first.")
            return
        self.invalidate_review()
        self._worker_task = asyncio.create_task(self._prepare_recovery(record, action))

    async def _prepare_recovery(self, record: JournalRecord, action: str) -> None:
        try:
            await self._release()
            selected_connection = None if action == "forget" else self.connection()
            self._connection = selected_connection
            client, identity = (
                selected_connection if selected_connection is not None else (None, None)
            )
            owner = NodeShellRecovery(
                self.manager.journal,
                client,
                self.policy,
                (lambda: self.session_current(client, identity))
                if client is not None and identity is not None
                else lambda: False,
            )
            self.owner = owner
            if action == "inspect":
                observation = await owner.inspect(record)
                self.status(f"Inspection: {observation.code}. Unknown ownership remains unknown.")
                return
            review = await (
                owner.prepare_cleanup(record)
                if action == "cleanup"
                else owner.prepare_forget(record)
            )
            if self._stopping or self.selected() is not record:
                await self._release()
                return
            self.review = review
            self.preview.update(
                safe_text(
                    f"Context: {record.context}\nNamespace: {record.namespace}\nPod: {record.pod_name}\n"
                    f"Returned UID: {record.pod_uid or '(unknown)'}\n"
                    + (
                        "Delete only this known UID with a server UID precondition. "
                        "A replacement is preserved. Remove the journal only after confirmed absence."
                        if action == "cleanup"
                        else "Forget this local record. No remote Pod is changed and no cleanup is claimed. "
                        "An uncertain create may still become visible later."
                    ),
                    multiline=True,
                )
            )
            confirm = self.confirm_button
            confirm.label = "Delete known UID" if action == "cleanup" else "Forget record"
            confirm.disabled = False
            self.cancel_button.focus()
            self.status("Review this exact action; Cancel remains the default.")
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError) as error:
            await self._release()
            self.status(str(error))
        except Exception as error:
            await self._release()
            self.app._handle_exception(error)

    @on(Button.Pressed, "#node-recovery-confirm")
    def confirm(self) -> None:
        owner, review = self.owner, self.review
        if self.busy or self._stopping or owner is None or review is None:
            return
        self.invalidate_review()
        self._confirming = True
        try:
            proof = owner.confirm(review)
            operation = owner.cleanup(proof) if review.action == "cleanup" else owner.forget(proof)
        except AppError as error:
            self._confirming = False
            self.status(str(error))
            return
        self._worker_task = asyncio.create_task(self._complete(operation))
        self._worker_task.add_done_callback(
            lambda task: operation.close() if task.cancelled() else None
        )

    async def _complete(self, operation: Coroutine[Any, Any, MutationResult]) -> None:
        try:
            result = await operation
            await self._reload()
            self.status(result.message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._release()
            self.app._handle_exception(error)
        finally:
            self._confirming = False

    def validate_target(self) -> None:
        if self.review is not None and self.review.action == "cleanup":
            connection = self._connection
            if self.policy.read_only or connection is None or not self.session_current(*connection):
                self.invalidate_review()
                self.status("Recovery connection or policy changed. Review again before cleanup.")

    async def _stop(self) -> None:
        try:
            if self._worker_task is not None and not self._worker_task.done():
                self._worker_task.cancel()
                await finish_owned(asyncio.gather(self._worker_task, return_exceptions=True))
            await self._release()
        finally:
            self.stopped()

    async def stop_owned(self) -> None:
        self._stopping = True
        self.invalidate_review()
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._stop())
        await finish_owned(self._close_task)

    @on(Button.Pressed, "#node-recovery-cancel")
    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_mounted:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()
