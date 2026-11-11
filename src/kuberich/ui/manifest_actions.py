"""Lazy local-manifest composition with retained screen and client ownership."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kuberich.domain.manifests import (
    FrozenDraftSource,
    FrozenManifestSource,
    ManifestAction,
    ManifestScope,
)
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services.access import Action
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner

if TYPE_CHECKING:
    from textual.screen import Screen

    from kuberich.adapters.kubernetes import KubernetesSession
    from kuberich.services.resource_creation import ResourceCreationService
    from kuberich.ui.manifest_browser import ManifestBrowserScreen
    from kuberich.ui.manifest_review import ManifestReviewScreen
    from kuberich.ui.resource_creation import ResourceCreationScreen


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
        config_path: Path | None = None,
        selected_context: Callable[[], str | None] | None = None,
        connect_context: Callable[[str], Awaitable[ManifestConnection]] | None = None,
    ) -> None:
        self.local, self.manager, self.runner = local, manager, runner
        self.capture_connection, self.push_screen, self.notice = (
            capture_connection,
            push_screen,
            notice,
        )
        self._browsers: list[ManifestBrowserScreen] = []
        self._creators: list[ResourceCreationScreen] = []
        self._reviews: list[ManifestReviewScreen] = []
        self._failed_owners: set[int] = set()
        self.config_path = config_path or local.directory / "config.yaml"
        self.selected_context, self.connect_context = selected_context, connect_context
        self._connecting_source: ResourceCreationService | None = None
        self._stopped = False

    @property
    def operation_count(self) -> int:
        return (
            self.local.operation_count
            + sum(screen.operation_count for screen in self._browsers)
            + sum(screen.operation_count for screen in self._reviews)
            + sum(screen.operation_count for screen in self._creators)
        )

    def _retain(self) -> None:
        self._browsers = [
            screen
            for screen in self._browsers
            if not screen.stopped or screen.operation_count or id(screen) in self._failed_owners
        ]
        self._reviews = [
            screen
            for screen in self._reviews
            if not screen.stopped or screen.operation_count or id(screen) in self._failed_owners
        ]
        self._creators = [
            screen
            for screen in self._creators
            if not screen.stopped or screen.operation_count or id(screen) in self._failed_owners
        ]

    def open_creation(self) -> None:
        if self._stopped:
            return
        from kuberich.services.resource_creation import ResourceCreationService
        from kuberich.services.resource_templates import TemplateCatalogService
        from kuberich.ui.resource_creation import ResourceCreationScreen

        self._retain()
        local = ResourceCreationService(
            self.local.policy, self.local.environment, self.local.directory
        )
        context = self.selected_context() if self.selected_context is not None else None
        screen = ResourceCreationScreen(
            service=local,
            runner=self.runner,
            open_review=lambda source: self.open_creation_review(source, local),
            catalog=TemplateCatalogService(self.config_path, local.directory),
            connection_ready=lambda: self.capture_connection() is not None,
            selected_context=context,
            connect_review=lambda source: self.connect_creation_review(source, local, context),
        )
        self._creators.append(screen)
        self.push_screen(screen)

    def open_creation_review(
        self, source: FrozenDraftSource, local: ResourceCreationService
    ) -> None:
        if self._stopped:
            return

        connection = self.capture_connection()
        if connection is None:
            self.notice(
                "Connect to a context before strict server validation; draft inspection is offline."
            )
            return
        self._push_creation_review(source, local, connection)

    def _push_creation_review(
        self,
        source: FrozenDraftSource,
        local: ResourceCreationService,
        connection: ManifestConnection,
    ) -> None:
        from kuberich.ui.manifest_review import ManifestReviewScreen

        self._retain()
        service = ManifestMutationService(
            connection.client,
            connection.scope,
            connection.discovery,
            local.policy,
            source,
            lambda: connection.current() and local.current_source is source,
            lambda: local.require_source(source),
            local.environment,
            local.directory,
        )
        screen = ManifestReviewScreen(service=service, manager=self.manager, action="create")
        self._reviews.append(screen)
        self.push_screen(screen)

    async def connect_creation_review(
        self, source: FrozenDraftSource, local: ResourceCreationService, context: str | None
    ) -> None:
        if self._stopped or self._connecting_source is not None:
            raise AppError(
                "Creation connection is closed or another explicit connection is active."
            )
        local.policy.require(Action.MUTATE)
        await local.require_source(source)
        connection = self.capture_connection()
        if connection is None:
            if context is None or self.connect_context is None:
                raise AppError("Select a configured context before connecting for creation review.")
            self._connecting_source = local
            try:
                connection = await self.connect_context(context)
            finally:
                self._connecting_source = None
        await local.require_source(source)
        local.policy.require(Action.MUTATE)
        if self._stopped or not connection.current() or connection.scope.session.context != context:
            raise AppError("Creation connection changed; review the explicit context again.")
        self._push_creation_review(source, local, connection)

    def open_browser(self) -> None:
        if self._stopped:
            return
        from kuberich.ui.manifest_browser import ManifestBrowserScreen

        self._retain()
        screen = ManifestBrowserScreen(
            service=self.local,
            open_review=self.open_review,
            runner=self.runner,
            open_creation=self.open_creation,
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
        failures: list[BaseException] = []
        for screen in tuple(self._reviews):
            if screen.service.client is client:
                try:
                    await screen.stop_owned()
                except BaseException as error:
                    self._failed_owners.add(id(screen))
                    failures.append(error)
                else:
                    self._failed_owners.discard(id(screen))
        for creator in tuple(self._creators):
            if creator.service is self._connecting_source:
                continue
            try:
                await creator.stop_owned()
            except BaseException as error:
                self._failed_owners.add(id(creator))
                failures.append(error)
            else:
                self._failed_owners.discard(id(creator))
        self._retain()
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("Manifest client owners could not completely close.", failures)

    async def stop_owned(self) -> None:
        self._stopped = True
        failures: list[BaseException] = []
        owners: tuple[
            ManifestReviewScreen | ManifestBrowserScreen | ResourceCreationScreen, ...
        ] = (*self._reviews, *self._browsers, *self._creators)
        for screen in owners:
            try:
                await screen.stop_owned()
            except BaseException as error:
                self._failed_owners.add(id(screen))
                failures.append(error)
            else:
                self._failed_owners.discard(id(screen))
        try:
            await self.local.close()
        except BaseException as error:
            failures.append(error)
        self._retain()
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("Manifest owners could not completely close.", failures)
