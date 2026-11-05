"""Typed authorization submission boundary and scoped workspace ownership."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationRequest,
    AuthorizationSnapshot,
)
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ViewStore
from kuberich.services.authorization import AuthorizationReader, AuthorizationService
from kuberich.services.resources import ResourceReader


class AuthorizationSubmit(Protocol):
    def __call__(
        self,
        intent: AuthorizationIntent,
        *,
        scope: NamespaceChoice | None = None,
        preserve_intent: bool = False,
    ) -> asyncio.Task[None]: ...


class AuthorizationWorkspace:
    """A single request/task owner; invalidation happens before cancellation awaits."""

    def __init__(self) -> None:
        self.request: AuthorizationRequest | None = None
        self.task: asyncio.Task[None] | None = None
        self._revision = 0

    @property
    def collecting(self) -> bool:
        return self.task is not None and not self.task.done()

    def prepare(
        self, session: SessionIdentity, intent: AuthorizationIntent
    ) -> AuthorizationRequest:
        self._revision += 1
        self.request = AuthorizationRequest(session, self._revision, intent)
        self.cancel()
        return self.request

    def invalidate(self) -> None:
        self.request = None
        self.cancel()

    def cancel(self) -> None:
        task = self.task
        if task is not None and not task.done() and not task.cancelling():
            task.cancel()

    async def stop(self) -> None:
        task = self.task
        if task is None:
            return
        self.cancel()
        completion = asyncio.gather(task, return_exceptions=True)
        cancelled = False
        try:
            while not completion.done():
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        finally:
            self.task = None

    def start(
        self,
        request: AuthorizationRequest,
        reader: ResourceReader,
        discovery: Discovery,
        revision: int,
        store: ViewStore,
        current: Callable[[AuthorizationRequest], bool],
        publish: Callable[[], None],
        unexpected: Callable[[int, Exception], None],
    ) -> None:
        request = (
            replace(request, session=store.observation.connection.identity)
            if store.observation.connection.identity is not None
            else request
        )
        self.request = request
        store.bind_authorization(revision, request)
        service = AuthorizationService(
            reader, AuthorizationReader(reader.session), discovery, request.session, current
        )

        async def run() -> None:
            def receive(snapshot: AuthorizationSnapshot) -> None:
                if current(snapshot.request) and store.apply_authorization(revision, snapshot):
                    publish()

            try:
                await service.collect(request, receive)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                unexpected(revision, error)

        self.task = asyncio.create_task(run(), name="kuberich-authorization-collection")
