"""Lazy local-manifest composition with retained screen and client ownership."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from kuberich.domain.manifests import FrozenManifestSource, ManifestAction, ManifestScope
from kuberich.domain.resources import Discovery
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner

if TYPE_CHECKING:
    from textual.screen import Screen

    from kuberich.adapters.kubernetes import KubernetesSession
    from kuberich.ui.manifest_browser import ManifestBrowserScreen
    from kuberich.ui.manifest_review import ManifestReviewScreen


@dataclass(frozen=True, slots=True)
class ManifestConnection:
    client: KubernetesSession
    scope: ManifestScope
    discovery: Discovery
    current: Callable[[], bool]


class ManifestActions:
    def __init__(
        self,
        *,
        local: LocalManifestService,
        manager: MutationManager,
        runner: ProcessRunner,
        capture_connection: Callable[[], ManifestConnection | None],
        push_screen: Callable[[Screen[None]], None],
        notice: Callable[[str], None],
    ) -> None:
        self.local, self.manager, self.runner = local, manager, runner
        self.capture_connection, self.push_screen, self.notice = (
            capture_connection,
            push_screen,
            notice,
        )
        self._browsers: list[ManifestBrowserScreen] = []
        self._reviews: list[ManifestReviewScreen] = []
        self._stopped = False

    @property
    def operation_count(self) -> int:
        return (
            self.local.operation_count
            + sum(screen.operation_count for screen in self._browsers)
            + sum(screen.operation_count for screen in self._reviews)
        )

    def _retain(self) -> None:
        self._browsers = [
            screen for screen in self._browsers if not screen.stopped or screen.operation_count
        ]
        self._reviews = [
            screen for screen in self._reviews if not screen.stopped or screen.operation_count
        ]

    def open_browser(self) -> None:
        if self._stopped:
            return
        from kuberich.ui.manifest_browser import ManifestBrowserScreen

        self._retain()
        screen = ManifestBrowserScreen(
            service=self.local, open_review=self.open_review, runner=self.runner
        )
        self._browsers.append(screen)
        self.push_screen(screen)

    def open_review(self, source: FrozenManifestSource, action: ManifestAction) -> None:
        if self._stopped:
            return
        from kuberich.ui.manifest_review import ManifestReviewScreen

        connection = self.capture_connection()
        if connection is None:
            self.notice(
                "Connect to a context before reviewing cluster changes; local inspection remains available."
            )
            return
        self._retain()
        service = ManifestMutationService(
            connection.client,
            connection.scope,
            connection.discovery,
            self.local.policy,
            source,
            lambda: connection.current() and self.local.current_source is source,
            lambda: self.local.require_source(source),
            self.local.environment,
            self.local.directory,
        )
        screen = ManifestReviewScreen(service=service, manager=self.manager, action=action)
        self._reviews.append(screen)
        self.push_screen(screen)

    async def close_for_client(self, client: KubernetesSession) -> None:
        for screen in tuple(self._reviews):
            if screen.service.client is client:
                await screen.stop_owned()
        self._retain()

    async def stop_owned(self) -> None:
        self._stopped = True
        for review in tuple(self._reviews):
            await review.stop_owned()
        for browser in tuple(self._browsers):
            await browser.stop_owned()
        self._reviews.clear()
        self._browsers.clear()
        await self.local.close()
