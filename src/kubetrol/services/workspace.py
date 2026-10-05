"""Own the active session/view, coalesce switches and bound UI subscriptions."""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.connections import ConnectionProblem, ConnectionState, namespace_name
from kubetrol.domain.resources import Discovery
from kubetrol.domain.views import (
    USABLE_CONNECTIONS,
    ResourceScope,
    ResourceSelection,
    ViewObservation,
    ViewStore,
)
from kubetrol.domain.watches import SyncUpdate
from kubetrol.errors import AppError
from kubetrol.security.arguments import validate_argument
from kubetrol.services.resources import ResourceReader
from kubetrol.services.sessions import SessionService
from kubetrol.services.watches import ListWatch

MAX_SUBSCRIPTIONS = 8


class ViewSubscription(AsyncIterator[ViewObservation]):
    """One replaceable pending observation; no event history or producer queue."""

    def __init__(self, initial: ViewObservation, remove: Callable[[], None]) -> None:
        self._pending: ViewObservation | None = initial
        self._ready = asyncio.Event()
        self._ready.set()
        self._closed = False
        self._remove = remove

    def offer(self, observation: ViewObservation) -> None:
        if not self._closed:
            self._pending = observation
            self._ready.set()

    async def __anext__(self) -> ViewObservation:
        await self._ready.wait()
        if self._closed:
            raise StopAsyncIteration
        observation = self._pending
        self._pending = None
        self._ready.clear()
        assert observation is not None
        return observation

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._pending = None
            self._remove()
            del self._remove
            self._ready.set()


@dataclass(frozen=True)
class _Selection:
    revision: int
    context: str
    resource: ResourceSelection
    reconnect: bool = False
    change_namespace: bool = False
    namespace: str | None = None


def _cancel_once(task: asyncio.Task[None] | None) -> None:
    # Repeated cancellation can interrupt an adapter's awaited cleanup worker.
    if task is not None and not task.done() and not task.cancelling():
        task.cancel()


async def _join(task: asyncio.Task[None]) -> None:
    completion = asyncio.gather(task, return_exceptions=True)
    cancelled = False
    while not completion.done():
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            # A second interrupt must not cancel the cleanup being drained either.
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


class WorkspaceService:
    def __init__(
        self,
        sessions: SessionService,
        *,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.sessions = sessions
        self.store = ViewStore()
        self.selection = ResourceSelection()
        self._on_error = on_error
        self._subscriptions: set[ViewSubscription] = set()
        self._desired: _Selection | None = None
        self.task: asyncio.Task[None] | None = None
        self._operation: asyncio.Task[None] | None = None
        self._watch: asyncio.Task[None] | None = None
        self._discovery: tuple[KubernetesSession, Discovery] | None = None
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    def _require_open(self) -> None:
        if self._closed:
            raise AppError("The workspace is closed.")

    def subscribe(self) -> ViewSubscription:
        self._require_open()
        if len(self._subscriptions) >= MAX_SUBSCRIPTIONS:
            raise AppError("Too many active resource subscriptions.")
        subscription = ViewSubscription(
            self.store.observation, lambda: self._subscriptions.discard(subscription)
        )
        self._subscriptions.add(subscription)
        return subscription

    def _publish(self) -> None:
        for subscription in self._subscriptions:
            subscription.offer(self.store.observation)

    def _schedule(self, selection: _Selection) -> asyncio.Task[None]:
        self._desired = selection
        _cancel_once(self._watch)
        _cancel_once(self._operation)
        self._publish()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._drive(), name="kubetrol-workspace")
        return self.task

    def connect(self, context: str) -> asyncio.Task[None]:
        self._require_open()
        validate_argument(context)
        revision = self.store.begin(context)
        return self._schedule(_Selection(revision, context, self.selection, reconnect=True))

    def _current_context(self) -> str:
        self._require_open()
        connection = self.store.observation.connection
        if (
            self.sessions.client is None
            or connection.identity is None
            or connection.state not in USABLE_CONNECTIONS
            or connection.identity != self.sessions.observation.identity
        ):
            raise AppError("Connect to a context before selecting a resource scope.")
        return connection.identity.context

    def select_namespace(self, namespace: str | None) -> asyncio.Task[None]:
        context = self._current_context()
        if namespace is not None:
            namespace_name(namespace)
        connection = replace(self.store.observation.connection, namespace=namespace)
        revision = self.store.begin(context, connection)
        return self._schedule(
            _Selection(
                revision, context, self.selection, change_namespace=True, namespace=namespace
            )
        )

    def select_resource(self, resource: ResourceSelection) -> asyncio.Task[None]:
        context = self._current_context()
        self.selection = resource
        connection = self.store.observation.connection
        revision = self.store.begin(context, connection)
        return self._schedule(
            _Selection(
                revision,
                context,
                resource,
                change_namespace=connection.namespace != self.sessions.observation.namespace,
                namespace=connection.namespace,
            )
        )

    async def _stop_watch(self) -> None:
        task = self._watch
        if task is not None:
            _cancel_once(task)
            try:
                await _join(task)
            finally:
                self._watch = None

    async def _drive(self) -> None:
        while self._desired is not None:
            selection = self._desired
            self._desired = None
            self._operation = asyncio.create_task(self._transition(selection))
            try:
                await self._operation
            except asyncio.CancelledError:
                # Only the replaceable operation is cancelled; this owner drains it.
                pass
            except Exception as error:
                self._unexpected(selection.revision, error)
            finally:
                self._operation = None

    def _unexpected(self, revision: int, error: Exception) -> None:
        self.store.fail(
            revision,
            ConnectionProblem(ConnectionState.API_ERROR, "Resource synchronization failed."),
        )
        self._publish()
        if self._on_error is None:
            raise error
        self._on_error(error)

    async def _transition(self, selection: _Selection) -> None:
        await self._stop_watch()
        try:
            if selection.reconnect:
                self._discovery = None
                observation = await self.sessions.connect(selection.context)
            elif selection.change_namespace:
                observation = self.sessions.select_namespace(selection.namespace)
            else:
                observation = self.sessions.observation
            if not self.store.connected(selection.revision, observation):
                return
            self._publish()
            if observation.state not in USABLE_CONNECTIONS:
                return
            client = self.sessions.client
            assert client is not None and observation.identity is not None
            reader = ResourceReader(client)
            if self._discovery is None or self._discovery[0] is not client:
                discovery = await reader.discover()
                if selection.revision != self.store.observation.revision:
                    return
                self._discovery = client, discovery
            else:
                discovery = self._discovery[1]
            resource = discovery.find(
                selection.resource.name,
                group=selection.resource.group,
                version=selection.resource.version,
            )
            scope = ResourceScope(
                observation.identity,
                resource,
                observation.namespace if resource.namespaced else None,
            )
            self.store.bind(selection.revision, scope)
            self._publish()
            self._watch = asyncio.create_task(
                self._run_watch(selection.revision, client, scope, reader),
                name="kubetrol-resource-watch",
            )
        except AppError:
            self._fail(
                selection.revision,
                ConnectionProblem(
                    ConnectionState.API_ERROR,
                    "Selected resource/scope is unavailable. Check discovery and permissions.",
                ),
            )
        except ConnectionProblem as problem:
            self._fail(selection.revision, problem)

    def _fail(self, revision: int, problem: ConnectionProblem) -> None:
        if self.store.fail(revision, problem):
            self._publish()

    async def _run_watch(
        self,
        revision: int,
        client: KubernetesSession,
        scope: ResourceScope,
        reader: ResourceReader,
    ) -> None:
        async def receive(update: SyncUpdate) -> None:
            if (
                self.sessions.client is client
                and self.sessions.observation.identity == scope.session
                and self.store.apply(revision, scope, update)
            ):
                self._publish()

        try:
            await ListWatch(reader).run(scope.resource, scope.namespace, receive)
        except ConnectionProblem as problem:
            self._fail(revision, problem)
        except AppError:
            self._fail(
                revision,
                ConnectionProblem(
                    ConnectionState.API_ERROR, "Invalid resource synchronization state."
                ),
            )
        except Exception as error:
            self._unexpected(revision, error)

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self.store.disconnect()
            self._desired = None
            _cancel_once(self._operation)
            _cancel_once(self._watch)
            self._closing = asyncio.create_task(self._close())
        await _join(self._closing)
        # Retrieve any unexpected close failure rather than silently suppress it.
        self._closing.result()

    async def _close(self) -> None:
        try:
            if self.task is not None:
                await _join(self.task)
            await self._stop_watch()
            await self.sessions.close()
        finally:
            self._discovery = None
            for subscription in tuple(self._subscriptions):
                subscription.close()
