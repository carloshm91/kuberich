"""Compose captured Pod debug screens and retain their local work through drainage."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.ephemeral_debug import EphemeralDebugManager
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner
from kuberich.ui.ephemeral_debug import EphemeralDebugScreen
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.ui.resource_operations import OperationContext


class EphemeralDebugActions:
    def __init__(
        self,
        host: App[None],
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        policy: AccessPolicy,
        mutations: MutationManager,
        processes: ProcessRunner,
        notice: Callable[[str], None],
    ) -> None:
        self.host, self.capture, self.context = host, capture, context
        self.policy, self.mutations, self.processes, self.notice = (
            policy,
            mutations,
            processes,
            notice,
        )
        self.manager = EphemeralDebugManager()
        self._screens: set[EphemeralDebugScreen] = set()
        self._closed = False

    @property
    def retained_count(self) -> int:
        return len(self._screens)

    def open(self) -> None:
        try:
            if self._closed or self._screens:
                raise AppError("A debug viewer is active or draining. Wait for local cleanup.")
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
                environment=context.environment,
                directory=context.directory,
            )
        except AppError as error:
            self.notice(str(error))
            return
        screen = EphemeralDebugScreen(
            owner,
            self.mutations,
            self.processes,
            shell=context.shell,
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
        await self.manager.close_for_client(client)

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(screen.stop_owned() for screen in tuple(self._screens)))
        await self.manager.close()
