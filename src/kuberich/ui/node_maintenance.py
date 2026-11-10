"""Explicit Node maintenance review, guarded execution and owned Stop controls."""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from typing import ClassVar
from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.node_maintenance import (
    DrainOptions,
    MaintenanceMode,
    MaintenanceReview,
    PodReview,
)
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.mutations import MutationManager
from kuberich.services.node_maintenance import NodeMaintenanceService
from kuberich.services.ownership import finish_owned
from kuberich.ui.port_forwards import ForwardInput


class NodeMaintenanceScreen(ModalScreen[None]):
    AUTO_FOCUS = "#node-maintenance-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", show=False, priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    NodeMaintenanceScreen { align: center middle; background: $background 80%; }
    #node-maintenance-form { width: 98%; max-width: 128; height: 96%;
        border: round $warning; padding: 0 1; background: $surface; }
    #node-maintenance-title { height: 1; }
    #node-maintenance-scroll { height: 1fr; }
    #node-maintenance-scroll Static { height: auto; }
    #node-maintenance-pods { height: 9; min-height: 3; }
    #node-maintenance-timeout { height: 3; width: 18; }
    #node-maintenance-scroll Checkbox { width: 100%; height: auto; min-height: 1; }
    #node-maintenance-progress { height: auto; max-height: 3; }
    #node-maintenance-feedback { height: auto; max-height: 3; }
    #node-maintenance-buttons { height: 1; }
    #node-maintenance-buttons Button { height: 1; border: none; min-width: 12; padding: 0 1; }
    #node-maintenance-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(
        self,
        owner: NodeMaintenanceService,
        mutations: MutationManager,
        mode: MaintenanceMode,
        *,
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.owner, self.mutations, self.mode, self.stopped = owner, mutations, mode, stopped
        self.review: MaintenanceReview | None = None
        self.started = False
        self.finished = False
        self._worker: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._write: UUID | None = None
        self._stopping = False
        self._rows: dict[str, tuple[object, ...]] = {}
        self.table: DataTable[object] = DataTable(
            id="node-maintenance-pods", cursor_type="row", zebra_stripes=True
        )
        self.feedback = Static(
            "Reading the captured Node…", id="node-maintenance-feedback", markup=False
        )
        self.preview = Static("", id="node-maintenance-preview", markup=False)
        self.detail = Static("", id="node-maintenance-detail", markup=False)
        self.progress = Static("", id="node-maintenance-progress", markup=False)
        self.confirm_button = Button(
            "Confirm", id="node-maintenance-confirm", compact=True, variant="warning", disabled=True
        )
        self.cancel_button = Button("Cancel", id="node-maintenance-cancel", compact=True)

    @property
    def busy(self) -> bool:
        return self._worker is not None and not self._worker.done()

    def compose(self) -> ComposeResult:
        target = self.owner.target
        with Vertical(id="node-maintenance-form"):
            yield Static(
                f"Node maintenance · {self.mode.value} · review before changing scheduling",
                id="node-maintenance-title",
                markup=False,
            )
            with VerticalScroll(id="node-maintenance-scroll"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nNode: {target.name}\nNode UID: {target.uid}\nScope: all namespaces, independent of the workspace filter",
                        multiline=True,
                    ),
                    id="node-maintenance-target",
                    markup=False,
                )
                yield self.preview
                if self.mode is MaintenanceMode.DRAIN:
                    yield Static("Total drain timeout in seconds (1-3600)", markup=False)
                    yield ForwardInput(
                        "300", id="node-maintenance-timeout", type="integer", max_length=4
                    )
                    yield Checkbox(
                        "Force: consent to evict reviewed unmanaged/orphaned Pods; recreation is not guaranteed",
                        id="node-maintenance-force",
                    )
                    yield Checkbox(
                        "Delete emptyDir data: consent to loss of reviewed emptyDir data (including memory-backed)",
                        id="node-maintenance-emptydir",
                    )
                    yield Checkbox(
                        "Leave DaemonSet Pods running on this Node",
                        id="node-maintenance-daemonsets",
                    )
                    yield self.table
                    yield self.detail
                yield Static(
                    "Stop prevents future requests; completed evictions remain. Cancellation is not rollback. Uncordon requires a separate fresh review. No PDB edits, direct Pod deletion or grace-period overrides.",
                    id="node-maintenance-limits",
                    markup=False,
                )
            yield self.progress
            yield self.feedback
            with Horizontal(id="node-maintenance-buttons"):
                yield Button("Review", id="node-maintenance-review", compact=True)
                yield self.confirm_button
                yield self.cancel_button

    def on_mount(self) -> None:
        if self.mode is MaintenanceMode.DRAIN:
            self.table.add_columns(
                "Namespace / Pod", "Owner", "Phase / Ready", "Local data", "PDBs", "Progress"
            )
        self._worker = asyncio.create_task(self._prepare())
        self.set_interval(0.2, self.refresh_progress)

    def status(self, value: str) -> None:
        if self.feedback.is_attached:
            self.feedback.update(safe_text(value))

    def options(self) -> DrainOptions:
        if self.mode is not MaintenanceMode.DRAIN:
            return DrainOptions()
        try:
            timeout = int(self.query_one("#node-maintenance-timeout", Input).value)
        except ValueError:
            raise AppError("Use a finite timeout from 1 to 3600 seconds.") from None
        return DrainOptions(
            force=self.query_one("#node-maintenance-force", Checkbox).value,
            delete_emptydir_data=self.query_one("#node-maintenance-emptydir", Checkbox).value,
            leave_daemonsets=self.query_one("#node-maintenance-daemonsets", Checkbox).value,
            timeout_seconds=timeout,
        )

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def changed(self) -> None:
        if not self.started:
            self.review = None
            self.confirm_button.disabled = True
            self.status("Options changed. Review again to read fresh facts; no write has started.")

    @on(Input.Submitted)
    @on(Button.Pressed, "#node-maintenance-review")
    def prepare(self) -> None:
        if self.started or self._stopping or self.busy:
            return
        self._worker = asyncio.create_task(self._prepare())

    async def _prepare(self) -> None:
        self.review = None
        self.confirm_button.disabled = True
        self.status(
            "Reading Node identity, all-namespace Pods, owners and PDB evidence; no writes…"
        )
        try:
            options = self.options()
            review = await self.owner.prepare(self.mode, options)
            if self._stopping:
                return
            if options != self.options():
                self.status("Options changed during preparation. Review the current options again.")
                return
            self.review = review
            scheduling = "cordoned" if review.node_unschedulable else "schedulable"
            blockers = "\n".join(review.blockers)
            self.preview.update(
                safe_text(
                    f"Observed scheduling: {scheduling}\nReviewed Node version: {review.node_resource_version}\nRequested operation: {review.mode.value}\n"
                    + (
                        f"Blocked: {blockers}"
                        if blockers
                        else "Review complete. Confirm authorizes this exact intent once."
                    ),
                    multiline=True,
                )
            )
            self._render_pods(review)
            self.confirm_button.disabled = bool(review.blockers)
            self.cancel_button.focus()
            self.status(
                "Resolve the blockers and review again."
                if review.blockers
                else "Review context, UID, facts and options. Confirm requires a deliberate action."
            )
        except asyncio.CancelledError:
            raise
        except (AppError, ConnectionProblem, TimeoutError):
            self.status(
                "Review unavailable: check captured identity, connection, complete inventory and permissions. No write started."
            )

    def _render_pods(self, review: MaintenanceReview) -> None:
        if self.mode is not MaintenanceMode.DRAIN:
            return
        self.table.clear()
        self._rows.clear()
        for pod in review.pods:
            target = pod.target
            row = (
                safe_text(f"{target.namespace}/{target.name}"),
                safe_text(pod.owner),
                safe_text(f"{pod.phase} / {pod.ready if pod.ready is not None else 'unknown'}"),
                safe_text("; ".join(pod.storage) or "No declared local data"),
                safe_text(", ".join(pdb.name for pdb in pod.pdbs) or "No matching PDB"),
                safe_text("Retained" if pod.retained else "Reviewed"),
            )
            self._rows[target.uid] = row
            self.table.add_row(*row, key=target.uid)
        self.selection_changed()

    def selected_pod(self) -> PodReview | None:
        if self.review is None or not 0 <= self.table.cursor_row < len(self.review.pods):
            return None
        return self.review.pods[self.table.cursor_row]

    @on(DataTable.RowHighlighted, "#node-maintenance-pods")
    def selection_changed(self) -> None:
        pod = self.selected_pod()
        if pod is None:
            return
        target = pod.target
        lines = [
            f"Pod: {target.namespace}/{target.name} · UID: {target.uid} · version: {pod.resource_version}",
            f"Owner: {pod.owner} · {'managed' if pod.managed else 'unmanaged/orphaned'}",
            f"DaemonSet: {pod.daemonset} · Mirror/static: {pod.mirror} · Already terminating: {pod.terminating}",
        ]
        lines.extend(pod.storage)
        lines.extend(pod.blockers)
        for pdb in pod.pdbs:
            lines.append(
                f"PDB {pdb.name} · UID {pdb.uid} · minAvailable {pdb.min_available or 'unset'} · maxUnavailable {pdb.max_unavailable or 'unset'} · disruptionsAllowed {pdb.disruptions_allowed} · healthy {pdb.current_healthy}/{pdb.desired_healthy} · generation {pdb.generation}/{pdb.observed_generation} · {pdb.unhealthy_policy} · {'current status' if pdb.status_current else 'status unknown/stale'}"
            )
        if len(pod.pdbs) > 1:
            lines.append(
                "Multiple matching PDBs: configuration may prevent eviction; allowances are not combined."
            )
        lines.append(
            "PDB evidence is informational. The API decides every eviction; zero allowance may require a wait. Storage portability and replacement readiness are not guaranteed."
        )
        self.detail.update(safe_text("\n".join(lines), multiline=True))

    @on(Button.Pressed, "#node-maintenance-confirm")
    def confirm(self) -> None:
        review = self.review
        if self.started or self._stopping or self.busy or review is None or review.blockers:
            return
        try:
            if review.options != self.options():
                raise AppError("Options changed.")
            self._write = self.mutations.start(self.owner, self.owner.confirm(review))
        except AppError:
            self.review = None
            self.confirm_button.disabled = True
            self.status("The target, options or policy changed. Cancel and start a fresh review.")
            return
        self.started = True
        self.confirm_button.disabled = True
        self.query_one("#node-maintenance-review", Button).disabled = True
        for field in self.query("Input, Checkbox"):
            field.disabled = True
        self.cancel_button.label = "Stop drain" if self.mode is MaintenanceMode.DRAIN else "Stop"
        self.cancel_button.focus()
        self.status(
            "Running the reviewed operation. Stop retains completed and uncertain outcomes."
        )
        self._worker = asyncio.create_task(self._result(self._write))

    async def _result(self, identity: UUID) -> None:
        result = await self.mutations.wait(identity)
        self.finished = True
        self.refresh_progress()
        self.status(f"{result.state.value}: {result.message}")
        self.cancel_button.label = "Back"

    def refresh_progress(self) -> None:
        if not self.progress.is_attached:
            return
        progress = self.owner.progress
        if self.started:
            counts = Counter(item.state.value for item in progress.pods)
            summary = " · ".join(f"{state}: {count}" for state, count in counts.items())
            for item in progress.pods:
                if item.uid in self._rows:
                    self.table.update_cell(
                        item.uid,
                        self.table.ordered_columns[-1].key,
                        safe_text(
                            f"{item.state.value} · attempts {item.attempts} · {item.message}"
                        ),
                    )
        else:
            summary = "No write started."
        node = progress.node
        age = max(0, time.time() - node.observed_at)
        self.progress.update(
            safe_text(
                f"{summary}\nFinal/current Node observation: {node.state.value} · age {age:.0f}s · observed UID {node.uid or 'unknown'}\nThis observation is separate from a successful cordon request.",
                multiline=True,
            )
        )

    def validate_target(self) -> None:
        if self._stopping or self.finished:
            return
        try:
            self.owner.require_current()
        except AppError:
            self.request_stop()

    def request_stop(self) -> None:
        self._stopping = True
        self.confirm_button.disabled = True
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())

    async def _stop(self) -> None:
        try:
            if not self.started and self._worker is not None and not self._worker.done():
                self._worker.cancel()
            if self._write is not None:
                result = await self.mutations.cancel(self._write)
                self.status(f"{result.state.value}: {result.message}")
            if self._worker is not None:
                if not self._worker.done():
                    self._worker.cancel()
                await finish_owned(asyncio.gather(self._worker, return_exceptions=True))
            await self.owner.close()
            self.finished = True
            self.refresh_progress()
            self.cancel_button.label = "Back"
        finally:
            self.stopped()

    async def stop_owned(self) -> None:
        self.request_stop()
        assert self._stop_task is not None
        await finish_owned(self._stop_task)

    @on(Button.Pressed, "#node-maintenance-cancel")
    async def cancel(self) -> None:
        if self.started and not self.finished:
            await self.stop_owned()
            return
        await self.action_back()

    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_mounted:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()
