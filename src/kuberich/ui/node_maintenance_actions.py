"""Capture one Node maintenance owner and retain it until all work is drained."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.node_maintenance import MaintenanceMode
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import MutationManager
from kuberich.services.node_maintenance import NodeMaintenanceService
from kuberich.ui.node_maintenance import NodeMaintenanceScreen
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.ui.resource_operations import OperationContext


class NodeMaintenanceActions:
    def __init__(
        self,
        host: App[None],
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        policy: AccessPolicy,
        mutations: MutationManager,
        notice: Callable[[str], None],
    ) -> None:
        self.host, self.capture, self.context = host, capture, context
        self.policy, self.mutations, self.notice = policy, mutations, notice
        self._screens: set[NodeMaintenanceScreen] = set()
        self._closed = False

    @property
    def retained_count(self) -> int:
        return len(self._screens)

    def open(self, mode: MaintenanceMode) -> None:
        try:
            self.policy.require(Action.MUTATE)
            if self._closed or self._screens:
                raise AppError(
                    "Node maintenance is active or draining. Stop it before a fresh review."
                )
            if not self.context().live:
                raise AppError(
                    "The Node table is stale or loading. Wait for a live observation and review again."
                )
            selection = self.capture(None)
            if selection is None:
                return
            client, resource, _, target, current = selection
            owner = NodeMaintenanceService(
                client,
                resource,
                target,
                self.context().discovery or Discovery((resource,)),
                self.policy,
                lambda: current() and self.context().live,
            )
            owner.require_current()
        except AppError as error:
            self.notice(str(error))
            return
        screen = NodeMaintenanceScreen(
            owner,
            self.mutations,
            mode,
            stopped=lambda: self._screens.discard(screen),
        )
        self._screens.add(screen)
        self.host.push_screen(screen)

    def observe(self) -> None:
        for screen in tuple(self._screens):
            screen.validate_target()

    async def close_for_client(self, client: KubernetesSession) -> None:
        await asyncio.gather(
            *(
                screen.stop_owned()
                for screen in tuple(self._screens)
                if screen.owner.client is client
            )
        )

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(screen.stop_owned() for screen in tuple(self._screens)))
