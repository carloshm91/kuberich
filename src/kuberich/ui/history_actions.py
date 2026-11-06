"""Compose captured metric-history entries and retain their connection ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from kuberich.domain.history import HistoryOptions, HistoryScope, HistorySnapshot, HistoryStatus
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned

if TYPE_CHECKING:
    from textual.app import App

    from kuberich.adapters.kubernetes import KubernetesSession
    from kuberich.domain.container_inspection import ContainerIdentity
    from kuberich.domain.history import ScopeKind
    from kuberich.domain.pulse import PulseScope
    from kuberich.domain.resources import ResourceRecord
    from kuberich.domain.targets import SessionIdentity
    from kuberich.domain.views import ViewObservation
    from kuberich.services.access import AccessPolicy
    from kuberich.services.history_workspace import HistoryWorkspace
    from kuberich.services.sessions import SessionService
    from kuberich.services.workspace import WorkspaceService
    from kuberich.ui.chrome import WorkspaceChrome
    from kuberich.ui.history import HistoryScreen
    from kuberich.ui.resource_operations import OperationContext
    from kuberich.ui.target_capture import CapturedResource


@dataclass(frozen=True)
class _Opening:
    client: KubernetesSession
    scope: HistoryScope
    current: Callable[[], bool]
    chrome: WorkspaceChrome
    trail: tuple[str, ...]
    detection_namespace: str | None = None


def _host_network(record: ResourceRecord) -> bool:
    spec = record.manifest.get("spec")
    return isinstance(spec, dict) and spec.get("hostNetwork") is True


class HistoryActions:
    def __init__(
        self,
        *,
        host: App[None],
        sessions: SessionService,
        workspace: WorkspaceService,
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        options: Callable[[str], HistoryOptions | None],
        policy: AccessPolicy,
        notice: Callable[[str], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        self.host, self.sessions, self.workspace = host, sessions, workspace
        self.capture, self.context, self.options = capture, context, options
        self.policy, self.notice, self.on_error = policy, notice, on_error
        self._owners: dict[KubernetesSession, HistoryWorkspace] = {}
        self._screens: dict[HistoryScreen, _Opening] = {}
        self._pending: _Opening | None = None
        self._opening: _Opening | None = None
        self._actor: asyncio.Task[None] | None = None
        self._closing: dict[KubernetesSession, asyncio.Task[None]] = {}
        self._closed = False

    @property
    def retained_screen_count(self) -> int:
        return len(self._screens)

    @property
    def owner_count(self) -> int:
        return len(self._owners)

    @property
    def detail_active(self) -> bool:
        """Include an entry being opened and a screen still draining after removal."""
        return bool(self._screens or self._pending is not None or self._opening is not None)

    @property
    def operation_count(self) -> int:
        return int(self._actor is not None and not self._actor.done()) + sum(
            owner.operation_count for owner in self._owners.values()
        )

    def _owner(self, client: KubernetesSession, identity: SessionIdentity) -> HistoryWorkspace:
        from kuberich.services.history_workspace import HistoryWorkspace

        if self._closed or client in self._closing:
            raise AppError("The history connection is closing.")
        owner = self._owners.get(client)
        if owner is not None:
            return owner
        discovery = self.workspace.discovery
        if discovery is None:
            raise AppError("Metric history needs current API discovery; reconnect first.")

        def current() -> bool:
            observed = self.sessions.observation.identity
            return (
                not self._closed
                and self.sessions.client is client
                and observed is not None
                and (observed.context, observed.connection_id)
                == (identity.context, identity.connection_id)
            )

        owner = HistoryWorkspace(
            client,
            discovery,
            identity,
            self.policy,
            current,
            observed_session=lambda: self.sessions.observation.identity,
        )
        self._owners[client] = owner
        return owner

    async def overview(self, client: KubernetesSession, scope: PulseScope) -> HistorySnapshot:
        options = self.options(scope.session.context)
        if options is None:
            return HistorySnapshot()
        try:
            return await self._owner(client, scope.session).overview(scope, options)
        except AppError as error:
            return HistorySnapshot(HistoryStatus.UNAVAILABLE, detail=str(error))

    def open_current(self) -> None:
        from kuberich.domain.aggregate_logs import workload_kind
        from kuberich.domain.view_routes import ViewKind
        from kuberich.ui.history import HistoryScreen

        if self._closed or isinstance(self.host.screen, HistoryScreen):
            return
        context = self.context()
        if context.modal:
            self.notice("Open metric history from a resource, container or Pulse view.")
            return
        if context.route.kind is ViewKind.PULSE:
            client = self.sessions.client
            snapshot = self.workspace.store.observation.pulse
            if client is None or snapshot is None:
                self.notice("Connect before opening cluster metric history.")
                return
            pulse = snapshot.scope
            scope = HistoryScope(pulse.session, "cluster", pulse.namespace)

            def current() -> bool:
                observed = self.workspace.store.observation.pulse
                return (
                    self.sessions.client is client
                    and self.workspace.pulse_selected
                    and observed is not None
                    and observed.scope == pulse
                )

            self._queue(
                _Opening(client, scope, current, context.chrome, context.trail, scope.namespace)
            )
            return
        selection = self.capture(None)
        if selection is None:
            return
        client, resource, record, target, current = selection
        kind: ScopeKind
        if not resource.group and resource.name == "nodes":
            kind = "node"
        elif not resource.group and resource.name == "pods":
            kind = "pod"
        else:
            try:
                workload_kind(target)
            except AppError:
                self.notice(
                    "Metric history is available for Nodes, workloads, Pods and containers."
                )
                return
            kind = "workload"
        scope = HistoryScope(
            target.session,
            kind,
            target.namespace,
            target,
            resource,
            record.created_at,
            host_network=_host_network(record),
        )
        self._queue(
            _Opening(
                client,
                scope,
                current,
                context.chrome,
                context.trail,
                scope.namespace or self.workspace.store.observation.connection.namespace,
            )
        )

    def open_container(
        self, selection: CapturedResource[KubernetesSession], identity: ContainerIdentity
    ) -> None:
        client, resource, record, target, current = selection
        context = self.context()
        scope = HistoryScope(
            target.session,
            "container",
            target.namespace,
            replace(target, container=identity.name),
            resource,
            record.created_at,
            identity.field,
            host_network=_host_network(record),
        )
        self._queue(
            _Opening(
                client,
                scope,
                current,
                context.chrome,
                (*context.trail, "containers"),
                scope.namespace,
            )
        )

    def _queue(self, entry: _Opening) -> None:
        if self._closed or not entry.current():
            return
        self._pending = entry
        if self._actor is None or self._actor.done():
            actor = asyncio.create_task(self._open_latest(), name="kuberich-open-history")
            self._actor = actor
            actor.add_done_callback(self._opened)

    def _opened(self, task: asyncio.Task[None]) -> None:
        if self._actor is task:
            self._actor = None
        if not task.cancelled() and (error := task.exception()) is not None:
            if isinstance(error, Exception):
                self.on_error(error)
            else:
                raise error

    async def _open_latest(self) -> None:
        try:
            while self._pending is not None and not self._closed:
                entry, self._pending = self._pending, None
                self._opening = entry
                # A removed screen may still own a parser. Its old leave_detail
                # must complete before another screen can claim the same owner.
                for screen in tuple(self._screens):
                    await screen.stop_owned()
                if self._pending is not None or not entry.current() or self._closed:
                    continue
                try:
                    owner = self._owner(entry.client, entry.scope.session)
                    owner.require_current(entry.scope)
                except AppError as error:
                    self.notice(str(error))
                    continue
                self._push(entry, owner)
        finally:
            self._opening = None

    def _push(self, entry: _Opening, owner: HistoryWorkspace) -> None:
        from kuberich.ui.history import HistoryScreen

        def retired() -> None:
            self._screens.pop(screen, None)

        screen = HistoryScreen(
            owner,
            entry.scope,
            self.options(entry.scope.session.context),
            chrome=entry.chrome,
            trail=entry.trail,
            stopped=retired,
            current=entry.current,
            detection_namespace=entry.detection_namespace,
        )
        self._screens[screen] = entry
        self.host.push_screen(screen)

    def observe(self, view: ViewObservation) -> None:
        for screen, entry in tuple(self._screens.items()):
            screen.validate_target()
            target = entry.scope.target
            if target is not None and entry.current() and view.snapshot is not None:
                screen.observe_target(
                    next(
                        (record for record in view.snapshot.items if record.uid == target.uid), None
                    )
                )

    def configure(self, options: HistoryOptions | None) -> None:
        claimed = set()
        for screen, entry in tuple(self._screens.items()):
            claimed.add(entry.client)
            screen.configure(options)
        for client, owner in self._owners.items():
            if client not in claimed:
                owner.invalidate()

    async def _close_client(self, client: KubernetesSession) -> None:
        if self._pending is not None and self._pending.client is client:
            self._pending = None
        if self._opening is not None and self._opening.client is client and self._actor is not None:
            self._actor.cancel()
            await finish_owned(asyncio.gather(self._actor, return_exceptions=True))
        for screen, entry in tuple(self._screens.items()):
            if entry.client is client:
                await screen.stop_owned()
        owner = self._owners.pop(client, None)
        if owner is not None:
            await owner.close()

    async def close_for_client(self, client: KubernetesSession) -> None:
        closing = self._closing.get(client)
        if closing is None:
            closing = asyncio.create_task(self._close_client(client))
            self._closing[client] = closing
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await finish_owned(closing)
            raise
        finally:
            if closing.done():
                self._closing.pop(client, None)

    async def close(self) -> None:
        self._closed = True
        self._pending = None
        if self._actor is not None:
            self._actor.cancel()
            await finish_owned(asyncio.gather(self._actor, return_exceptions=True))
        for screen in tuple(self._screens):
            await screen.stop_owned()
        for client in tuple(self._owners):
            await self.close_for_client(client)
