"""Compose captured node-shell owners without implicit cluster connections."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.node_shell_journal import JournalRecord
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import MutationManager
from kuberich.services.node_shell import NodeShellManager
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.ui.node_shell import NodeShellRecoveryScreen, NodeShellScreen
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.ui.resource_operations import OperationContext


class NodeShellActions:
    def __init__(
        self,
        host: App[None],
        manager: NodeShellManager,
        policy: AccessPolicy,
        mutations: MutationManager,
        processes: ProcessRunner,
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        settings: Callable[[], NodeShellSettings],
        generation: Callable[[], int],
        notice: Callable[[str], None],
        connection: Callable[[], tuple[KubernetesSession, SessionIdentity] | None],
        session_current: Callable[[KubernetesSession, SessionIdentity], bool],
    ) -> None:
        self.host, self.manager, self.policy = host, manager, policy
        self.mutations, self.processes = mutations, processes
        self.capture, self.context, self.settings, self.generation = (
            capture,
            context,
            settings,
            generation,
        )
        self.notice, self.connection, self.session_current = notice, connection, session_current
        self.pending_records: tuple[JournalRecord, ...] = ()
        self._screens: set[NodeShellScreen] = set()
        self._recoveries: set[NodeShellRecoveryScreen] = set()
        self._scan_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event | None = None
        self._scan_lock = asyncio.Lock()
        self._closed = False

    @property
    def retained_count(self) -> int:
        return len(self._screens) + len(self._recoveries)

    def start_scan(self, ready: asyncio.Event) -> None:
        self._ready = ready
        self._scan_task = asyncio.create_task(self._scan_after_frame(ready))

    async def scan(self) -> tuple[JournalRecord, ...]:
        """Serialize local scans after the actual first-frame readiness boundary."""
        if self._ready is not None:
            await self._ready.wait()
        async with self._scan_lock:
            if self._closed:
                raise AppError("Node-shell recovery is closing.")
            return await self.manager.scan()

    async def _scan_after_frame(self, ready: asyncio.Event) -> None:
        await ready.wait()
        if self._closed:
            return
        try:
            self.pending_records = await self.scan()
            if self.pending_records:
                self.notice(
                    f"{len(self.pending_records)} pending node-shell record(s). "
                    "Use :node-shell-recover to inspect local recovery metadata."
                )
        except AppError as error:
            self.notice(str(error))

    def open(self) -> None:
        try:
            self.policy.require(Action.MUTATE)
            self.policy.require(Action.EXEC)
            settings = self.settings()
            if not settings.enabled:
                raise AppError(
                    "Node shell is disabled. Configure node_shell with an approved image digest "
                    "and existing namespace, then explicitly enable it."
                )
            if self._closed or self._screens:
                raise AppError("A node-shell viewer is active or draining. Wait for cleanup.")
            selection = self.capture(None)
            if selection is None:
                return
            context = self.context()
            client, resource, _, target, current = selection
            owner = self.manager.create(
                client,
                resource,
                target,
                self.policy,
                current,
                settings=settings,
                config_generation=self.generation(),
                current_config=self.generation,
                environment=context.environment,
                directory=Path(context.directory),
            )
        except AppError as error:
            self.notice(str(error))
            return
        screen = NodeShellScreen(
            owner,
            self.mutations,
            self.processes,
            stopped=lambda: self._screens.discard(screen),
        )
        self._screens.add(screen)
        self.host.push_screen(screen)

    def open_recovery(self) -> None:
        if self._closed or self.context().modal:
            return
        screen = NodeShellRecoveryScreen(
            self.manager,
            self.policy,
            self.connection,
            self.session_current,
            scan=self.scan,
            records_changed=lambda records: setattr(self, "pending_records", records),
            stopped=lambda: self._recoveries.discard(screen),
        )
        self._recoveries.add(screen)
        self.host.push_screen(screen)

    def observe(self) -> None:
        for recovery in tuple(self._recoveries):
            recovery.validate_target()
        for screen in tuple(self._screens):
            if not self.settings().enabled or self.policy.read_only:
                screen.request_stop()
            else:
                screen.validate_target()

    async def close_for_client(self, client: KubernetesSession) -> None:
        await asyncio.gather(
            *(
                screen.stop_owned()
                for screen in tuple(self._screens)
                if screen.owner.client is client
            )
        )
        await asyncio.gather(
            *(
                screen.stop_owned()
                for screen in tuple(self._recoveries)
                if screen.owner is not None and screen.owner.client is client
            )
        )
        await self.manager.close_for_client(client)

    async def close(self) -> None:
        self._closed = True
        if self._scan_task is not None:
            self._scan_task.cancel()
            await finish_owned(asyncio.gather(self._scan_task, return_exceptions=True))
        await asyncio.gather(*(screen.stop_owned() for screen in tuple(self._screens)))
        await asyncio.gather(*(screen.stop_owned() for screen in tuple(self._recoveries)))
        await self.manager.close()
