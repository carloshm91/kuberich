"""Capture benchmark entry points and retain screens until owned cleanup completes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from textual.app import App

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmarks import BenchmarkManager, BenchmarkService
from kuberich.services.port_forwards import ForwardInfo
from kuberich.ui.target_capture import CapturedResource

if TYPE_CHECKING:
    from kuberich.ui.benchmarks import BenchmarkBrowserScreen, BenchmarkScreen
    from kuberich.ui.resource_operations import OperationContext


class BenchmarkActions:
    """Compose current owners while the local browser remains independent of them."""

    def __init__(
        self,
        host: App[None],
        manager: BenchmarkManager,
        store: BenchmarkStore,
        capture: Callable[[str | None], CapturedResource[KubernetesSession] | None],
        context: Callable[[], OperationContext],
        policy: AccessPolicy,
        settings: Callable[[str], BenchmarkSettings],
        connection: Callable[[], tuple[KubernetesSession, SessionIdentity] | None],
        session_current: Callable[[KubernetesSession, SessionIdentity], bool],
        notice: Callable[[str], None],
    ) -> None:
        self.host, self.manager, self.store = host, manager, store
        self.capture, self.context, self.policy = capture, context, policy
        self.settings, self.connection, self.session_current = settings, connection, session_current
        self.notice = notice
        self._screens: set[BenchmarkScreen] = set()
        self._browsers: set[BenchmarkBrowserScreen] = set()
        self._closed = False

    def open(self) -> None:
        try:
            self.policy.require(Action.BENCHMARK)
            context = self.context()
            if self._closed:
                return
            if context.route.kind is ViewKind.CUSTOM:
                raise AppError("Open a native Service view before reviewing an HTTP benchmark.")
            if not context.live:
                raise AppError("The Service view is stale or loading. Wait for a live observation.")
            selection = self.capture(None)
            if selection is None:
                return
            client, _, _, target, current = selection
            if target.group or target.resource != "services":
                raise AppError("Select a Service, or choose a READY owned forward from :pf.")
            settings = self.settings(target.session.context)
            owner = self.manager.create(
                client,
                target,
                self.policy,
                lambda: (
                    current()
                    and self.context().live
                    and self.settings(target.session.context) == settings
                ),
                settings=settings,
                environment=context.environment,
                directory=context.directory,
            )
            self._open(owner)
        except AppError as error:
            self.notice(str(error))

    def open_forward(self, info: ForwardInfo) -> None:
        try:
            self.policy.require(Action.BENCHMARK)
            if self._closed:
                return
            selected = self.connection()
            if selected is None or (
                selected[1].context != info.target.session.context
                or selected[1].connection_id != info.target.session.connection_id
            ):
                raise AppError("The forward connection changed. Review a current owned forward.")
            if info.state is not ForwardState.READY:
                raise AppError("Select a READY owned forward before reviewing a benchmark.")
            client, identity = selected
            context = self.context()
            settings = self.settings(identity.context)
            owner = self.manager.create(
                client,
                info.target,
                self.policy,
                lambda: (
                    self.session_current(client, identity)
                    and self.settings(identity.context) == settings
                ),
                settings=settings,
                environment=context.environment,
                directory=context.directory,
                forward=info,
            )
            self._open(owner)
        except AppError as error:
            self.notice(str(error))

    def _open(self, owner: BenchmarkService) -> None:
        from kuberich.ui.benchmarks import BenchmarkScreen

        context = self.context()
        screen = BenchmarkScreen(
            owner,
            chrome=context.chrome,
            trail=context.trail,
            stopped=lambda: self._screens.discard(screen),
        )
        self._screens.add(screen)
        self.host.push_screen(screen)

    def open_browser(self) -> None:
        if self._closed:
            return
        from kuberich.ui.benchmarks import BenchmarkBrowserScreen

        context = self.context()
        screen = BenchmarkBrowserScreen(
            self.store,
            chrome=context.chrome,
            trail=context.trail,
            stopped=lambda: self._browsers.discard(screen),
        )
        self._browsers.add(screen)
        self.host.push_screen(screen)

    def observe(self) -> None:
        for screen in tuple(self._screens):
            screen.validate_target()

    async def close_for_client(self, client: KubernetesSession) -> None:
        self.manager.invalidate_for_client(client)
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
        await asyncio.gather(
            *(screen.stop_owned() for screen in tuple(self._screens)),
            *(screen.stop_owned() for screen in tuple(self._browsers)),
        )
        await self.manager.close()
