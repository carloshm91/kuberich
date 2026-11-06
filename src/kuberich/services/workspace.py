"""Own the active session/view, coalesce switches and bound UI subscriptions."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

from kuberich.adapters.credentials import CredentialLogin
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.authorization import AuthorizationIntent, AuthorizationRequest, rescope_intent
from kuberich.domain.cluster_diagnostics import (
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
)
from kuberich.domain.connections import ConnectionProblem, ConnectionState, namespace_name
from kuberich.domain.history import HistorySnapshot
from kuberich.domain.metrics import MetricsSnapshot
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.pulse import PulseScope, PulseSnapshot
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipPath,
    RelationshipRef,
    RelationshipRequest,
    RelationshipScope,
    RelationshipSnapshot,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import (
    USABLE_CONNECTIONS,
    ResourceScope,
    ResourceSelection,
    ViewObservation,
    ViewStore,
)
from kuberich.domain.watches import SyncUpdate
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.services.access import AccessPolicy
from kuberich.services.authorization_workspace import AuthorizationWorkspace
from kuberich.services.cluster_diagnostics import DiagnosticService
from kuberich.services.diagnostic_workspace import DiagnosticWorkspace
from kuberich.services.metrics import MetricsPoller, supports_metrics
from kuberich.services.pulse import PulseService
from kuberich.services.relationships import RelationshipService
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.watches import ListWatch

MAX_SUBSCRIPTIONS = 8


class DiagnosticPopeye(Protocol):
    async def __call__(
        self,
        client: KubernetesSession,
        discovery: Discovery,
        request: DiagnosticRequest,
        current: Callable[[DiagnosticRequest], bool],
        *,
        max_findings: int,
        max_text_bytes: int,
        max_source_text_bytes: int,
    ) -> DiagnosticSnapshot: ...


@dataclass(frozen=True)
class WorkspaceOwnership:
    """Registered lifecycle ownership, without exposing tasks or cached data."""

    watch_count: int
    operation_count: int
    subscription_count: int
    discovery_count: int
    close_complete: bool
    metrics_count: int = 0
    pulse_count: int = 0
    relationships_count: int = 0
    authorization_count: int = 0
    diagnostics_count: int = 0


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
    authenticate: CredentialLogin | None = None
    pulse: bool = False
    relationships: RelationshipRequest | None = None
    authorization: AuthorizationRequest | None = None
    diagnostics: DiagnosticRequest | None = None
    diagnostic_producer: Literal["native", "popeye"] = "native"
    diagnostic_cancel: bool = False
    diagnostic_client: KubernetesSession | None = None


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
        pulse_history: Callable[[KubernetesSession, PulseScope], Awaitable[HistorySnapshot]]
        | None = None,
        diagnostic_policy: AccessPolicy | None = None,
        diagnostic_now: Callable[[], datetime] | None = None,
        diagnostic_popeye: DiagnosticPopeye | None = None,
    ) -> None:
        self.sessions = sessions
        self.store = ViewStore()
        self.selection = ResourceSelection()
        self.pulse_selected = False
        self._pulse_history = pulse_history
        self._on_error = on_error
        self._subscriptions: set[ViewSubscription] = set()
        self._desired: _Selection | None = None
        self.task: asyncio.Task[None] | None = None
        self._operation: asyncio.Task[None] | None = None
        self._watch: asyncio.Task[None] | None = None
        self._metrics: asyncio.Task[None] | None = None
        self._metrics_poller: MetricsPoller | None = None
        self._pulse: asyncio.Task[None] | None = None
        self._relationships: asyncio.Task[None] | None = None
        self._authorization = AuthorizationWorkspace()
        self._diagnostics = DiagnosticWorkspace()
        self._diagnostic_policy = (
            diagnostic_policy if diagnostic_policy is not None else AccessPolicy(True)
        )
        self._diagnostic_now = (
            diagnostic_now if diagnostic_now is not None else lambda: datetime.now(UTC)
        )
        self._diagnostic_popeye = diagnostic_popeye
        self._diagnostic_cancelling: DiagnosticRequest | None = None
        self._relationship_request: RelationshipRequest | None = None
        self._relationship_revision = 0
        self._relationship_service: tuple[KubernetesSession, RelationshipService] | None = None
        self._discovery: tuple[KubernetesSession, Discovery] | None = None
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    @property
    def ownership(self) -> WorkspaceOwnership:
        """Snapshot registered owners, including completed tasks not yet retired."""
        return WorkspaceOwnership(
            watch_count=int(self._watch is not None),
            operation_count=int(self._operation is not None),
            subscription_count=len(self._subscriptions),
            discovery_count=int(self._discovery is not None),
            close_complete=self._closing is not None and self._closing.done(),
            metrics_count=int(self._metrics is not None),
            pulse_count=int(self._pulse is not None),
            relationships_count=int(self._relationships is not None),
            authorization_count=int(self._authorization.task is not None),
            diagnostics_count=int(self._diagnostics.task is not None),
        )

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
        _cancel_once(self._metrics)
        _cancel_once(self._pulse)
        _cancel_once(self._relationships)
        _cancel_once(self._operation)
        self._authorization.cancel()
        _cancel_once(self._diagnostics.task)
        self._publish()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._drive(), name="kuberich-workspace")
        return self.task

    def connect(
        self,
        context: str,
        *,
        scope: NamespaceChoice | None = None,
        authenticate: CredentialLogin | None = None,
    ) -> asyncio.Task[None]:
        self._require_open()
        validate_argument(context)
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        authorization = self.authorization_request
        if authorization is not None:
            if authorization.session.context != context:
                self._authorization.invalidate()
            else:
                intent = (
                    rescope_intent(authorization.intent, scope.namespace)
                    if scope is not None
                    else authorization.intent
                )
                self._authorization.prepare(authorization.session, intent)
        request = self._relationship_request
        if request is not None and request.scope.root.session.context != context:
            self._relationship_request = None
            self._relationship_service = None
        revision = self.store.begin(context)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                reconnect=True,
                change_namespace=scope is not None,
                namespace=scope.namespace if scope is not None else None,
                authenticate=authenticate,
                pulse=self.pulse_selected,
                relationships=self._relationship_request,
                authorization=self.authorization_request,
            )
        )

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
        if self._diagnostic_scope() is not None:
            identity = self.store.observation.connection.identity
            assert identity is not None
            return self._submit_diagnostics(
                DiagnosticScope(identity, namespace),
                header=NamespaceChoice(namespace),
                force_namespace=True,
            )
        if self.authorization_request is not None:
            return self.select_authorization(
                self.authorization_request.intent, scope=NamespaceChoice(namespace)
            )
        if namespace is not None:
            namespace_name(namespace)
        connection = replace(self.store.observation.connection, namespace=namespace)
        revision = self.store.begin(context, connection)
        request = self._relationship_request
        if request is not None:
            self._relationship_revision += 1
            request = replace(
                request,
                revision=self._relationship_revision,
                scope=replace(request.scope, namespace=namespace),
            )
            self._relationship_request = request
            self.store.bind_relationships(revision, request)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=True,
                namespace=namespace,
                pulse=self.pulse_selected,
                relationships=request,
            )
        )

    def select_resource(self, resource: ResourceSelection) -> asyncio.Task[None]:
        context = self._current_context()
        self.prepare_resource(resource)
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

    def prepare_resource(self, resource: ResourceSelection) -> None:
        """Prepare an ordinary view before connecting, with no transport effects."""
        self._require_open()
        self.selection = resource
        self._authorization.invalidate()
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        self.pulse_selected = False
        self._relationship_request = None
        self._relationship_service = None

    def select_pulse(self) -> asyncio.Task[None]:
        """Select a native overview, including before the first connection is ready."""
        self._require_open()
        self.pulse_selected = True
        self._authorization.invalidate()
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        self._relationship_request = None
        self._relationship_service = None
        context = self.store.observation.context
        if context is None:
            return asyncio.create_task(asyncio.sleep(0), name="kuberich-pulse-selection")
        try:
            self._current_context()
        except AppError:
            return self.connect(context)
        connection = self.store.observation.connection
        revision = self.store.begin(context, connection)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=connection.namespace != self.sessions.observation.namespace,
                namespace=connection.namespace,
                pulse=True,
            )
        )

    @property
    def diagnostic_request(self) -> DiagnosticRequest | None:
        return self._diagnostics.request if self._diagnostic_cancelling is None else None

    @property
    def diagnostic_collecting(self) -> bool:
        return self._diagnostics.collecting

    def _diagnostic_scope(self) -> DiagnosticScope | None:
        request = self.diagnostic_request
        snapshot = self.store.observation.diagnostics
        return (
            request.scope
            if request is not None
            else snapshot.request.scope
            if snapshot is not None
            else None
        )

    def select_diagnostics(
        self,
        scope: DiagnosticScope,
        *,
        header: NamespaceChoice | None = None,
    ) -> asyncio.Task[None]:
        return self._submit_diagnostics(scope, header=header)

    def _submit_diagnostics(
        self,
        scope: DiagnosticScope,
        *,
        header: NamespaceChoice | None = None,
        producer: Literal["native", "popeye"] = "native",
        force_namespace: bool = False,
    ) -> asyncio.Task[None]:
        context = self._current_context()
        connection = self.store.observation.connection
        if scope.session != connection.identity:
            raise AppError("The diagnostic scope belongs to an obsolete connection.")
        namespace = connection.namespace if header is None else header.namespace
        if scope.root is None and scope.namespace != namespace:
            raise AppError("Diagnostic overview scope must match the selected header namespace.")
        connection = replace(connection, namespace=namespace)
        self._diagnostic_cancelling = None
        request = self._diagnostics.prepare(scope, producer)
        self._authorization.invalidate()
        self.pulse_selected = False
        self._relationship_request = None
        self._relationship_service = None
        revision = self.store.begin(context, connection)
        self.store.bind_diagnostics(revision, request)
        retained = self._diagnostics.snapshot
        if retained is not None:
            self.store.apply_diagnostics(revision, replace(retained, collecting=True))
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=force_namespace
                or header is not None
                or namespace != self.sessions.observation.namespace,
                namespace=namespace,
                diagnostics=request,
                diagnostic_producer=producer,
            )
        )

    def refresh_diagnostics(self) -> asyncio.Task[None]:
        scope = self._diagnostic_scope()
        if scope is None:
            raise AppError("Open diagnostics before refreshing its evidence.")
        return self._submit_diagnostics(scope)

    def run_popeye(self) -> asyncio.Task[None]:
        self._current_context()
        scope = self._diagnostic_scope()
        if scope is None:
            connection = self.store.observation.connection
            assert connection.identity is not None
            scope = DiagnosticScope(connection.identity, connection.namespace)
        return self._submit_diagnostics(scope, producer="popeye")

    def cancel_diagnostics(self) -> asyncio.Task[None]:
        context = self._current_context()
        if self._diagnostic_cancelling is not None and self.task is not None:
            return self.task
        request = self.diagnostic_request
        if request is None:
            raise AppError("Open diagnostics before cancelling its collection.")
        # Invalidate the old producer's outer publication guard synchronously while
        # preserving its rows. The owned transition drains before binding cancel().
        self._diagnostic_cancelling = request
        previous = self.store.observation
        revision = previous.revision + 1
        self.store.observation = replace(previous, revision=revision)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                diagnostics=request,
                diagnostic_cancel=True,
                diagnostic_client=self.sessions.client,
            )
        )

    async def _finish_diagnostic_cancel(self, selection: _Selection) -> None:
        if selection.revision != self.store.observation.revision:
            return
        snapshot = await self._diagnostics.cancel()
        if snapshot is None or selection.revision != self.store.observation.revision:
            return
        self._diagnostic_cancelling = None
        connection = self.store.observation.connection
        if (
            selection.diagnostic_client is None
            or self.sessions.client is not selection.diagnostic_client
            or self.sessions.observation.state not in USABLE_CONNECTIONS
            or self.sessions.observation.identity != snapshot.request.scope.session
            or connection.state not in USABLE_CONNECTIONS
            or connection.identity != snapshot.request.scope.session
        ):
            self._diagnostics.invalidate()
            return
        if self.store.bind_diagnostics(selection.revision, snapshot.request):
            self.store.apply_diagnostics(selection.revision, snapshot)
            self._publish()

    async def stop_diagnostics(self) -> None:
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        observation = self.store.observation
        if observation.diagnostics is not None:
            assert observation.context is not None
            self.store.begin(observation.context, observation.connection)
            self._publish()
        await self._diagnostics.stop()

    def _diagnostic_current(
        self,
        client: KubernetesSession,
        revision: int,
        request: DiagnosticRequest,
    ) -> bool:
        view = self.store.observation
        return (
            not self._closed
            and self.sessions.client is client
            and self.sessions.observation.state in USABLE_CONNECTIONS
            and self.sessions.observation.identity == request.scope.session
            and view.connection.state in USABLE_CONNECTIONS
            and view.connection.identity == request.scope.session
            and view.revision == revision
            and self.diagnostic_request == request
            and view.diagnostics is not None
            and view.diagnostics.request == request
        )

    def _start_diagnostics(
        self,
        selection: _Selection,
        client: KubernetesSession,
        discovery: Discovery,
    ) -> None:
        request = selection.diagnostics
        assert request is not None
        if request != self.diagnostic_request:
            return
        identity = self.sessions.observation.identity
        assert identity is not None
        if request.scope.session != identity:
            request = self._diagnostics.prepare(
                replace(request.scope, session=identity), selection.diagnostic_producer
            )
        self.store.bind_diagnostics(selection.revision, request)
        retained = self._diagnostics.snapshot
        if retained is not None:
            self.store.apply_diagnostics(selection.revision, replace(retained, collecting=True))

        def current(candidate: DiagnosticRequest) -> bool:
            return self._diagnostic_current(client, selection.revision, candidate)

        max_findings = self._diagnostics.remaining_findings
        max_text_bytes = self._diagnostics.remaining_text_bytes
        max_source_text_bytes = self._diagnostics.remaining_source_text_bytes
        external = self._diagnostic_popeye
        service = DiagnosticService(
            ResourceReader(client),
            discovery,
            self._diagnostic_policy,
            current,
            now=self._diagnostic_now,
        )

        async def collect(
            captured: DiagnosticRequest,
            publish: Callable[[DiagnosticSnapshot], None],
        ) -> DiagnosticSnapshot:
            try:
                if not current(captured):
                    raise asyncio.CancelledError
                if selection.diagnostic_producer == "native":
                    return await service.collect(captured, publish)
                source = DiagnosticSource(
                    "popeye:execution",
                    DiagnosticSourceKind.POPEYE,
                    None,
                    captured.scope.namespace,
                    DiagnosticStatus.LOADING,
                    None,
                    None,
                    None,
                    "Explicit Popeye collection; external API read count is unknown.",
                )
                publish(DiagnosticSnapshot(captured, (), (source,), True, 0, None))
                if external is None:
                    return DiagnosticSnapshot(
                        captured,
                        (),
                        (
                            replace(
                                source,
                                status=DiagnosticStatus.UNAVAILABLE,
                                observed_at=self._diagnostic_now(),
                                detail="Popeye integration is not configured. No external tool was run; external API read count is unknown.",
                            ),
                        ),
                        False,
                        0,
                        self._diagnostic_now(),
                    )
                result = await external(
                    client,
                    discovery,
                    captured,
                    current,
                    max_findings=max_findings,
                    max_text_bytes=max_text_bytes,
                    max_source_text_bytes=max_source_text_bytes,
                )
                if not current(captured):
                    raise asyncio.CancelledError
                if result.request != captured:
                    raise AppError("Diagnostic producer returned a different request.")
                return result
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if current(captured):
                    self._diagnostics.invalidate()
                    self._unexpected(selection.revision, error)
                raise

        def publish(snapshot: DiagnosticSnapshot) -> None:
            if current(snapshot.request) and self.store.apply_diagnostics(
                selection.revision, snapshot
            ):
                self._publish()

        self._diagnostics.start(request, collect, publish)
        task = self._diagnostics.task
        assert task is not None
        task.add_done_callback(
            lambda completed: None if completed.cancelled() else completed.exception()
        )
        self._publish()

    async def resolve_diagnostic(
        self,
        request: DiagnosticRequest,
        ref: RelationshipRef,
    ) -> ResourceRecord:
        self._current_context()
        client, discovery, revision = (
            self.sessions.client,
            self.discovery,
            self.store.observation.revision,
        )
        if (
            client is None
            or discovery is None
            or not self._diagnostic_current(client, revision, request)
        ):
            raise AppError("Diagnostic evidence belongs to an obsolete request.")
        service = DiagnosticService(
            ResourceReader(client),
            discovery,
            self._diagnostic_policy,
            lambda candidate: self._diagnostic_current(client, revision, candidate),
            now=self._diagnostic_now,
        )
        return await service.resolve(request, ref)

    @property
    def authorization_request(self) -> AuthorizationRequest | None:
        return self._authorization.request

    @property
    def authorization_collecting(self) -> bool:
        return self._authorization.collecting

    def select_authorization(
        self,
        intent: AuthorizationIntent,
        *,
        scope: NamespaceChoice | None = None,
        preserve_intent: bool = False,
    ) -> asyncio.Task[None]:
        context = self._current_context()
        if preserve_intent and scope is None:
            raise AppError("History restoration requires its captured header scope.")
        if scope is not None and not preserve_intent:
            intent = rescope_intent(intent, scope.namespace)
        connection = self.store.observation.connection
        if scope is not None:
            connection = replace(connection, namespace=scope.namespace)
        assert connection.identity is not None
        request = self._authorization.prepare(connection.identity, intent)
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        self.pulse_selected = False
        self._relationship_request = None
        self._relationship_service = None
        revision = self.store.begin(context, connection)
        self.store.bind_authorization(revision, request)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=connection.namespace != self.sessions.observation.namespace,
                namespace=connection.namespace,
                authorization=request,
            )
        )

    def refresh_authorization(self) -> asyncio.Task[None]:
        request = self.authorization_request
        if request is None:
            raise AppError("Open authorization before refreshing evidence.")
        return self.select_authorization(request.intent)

    async def stop_authorization(self) -> None:
        self._authorization.invalidate()
        if self.store.observation.authorization is not None:
            observation = self.store.observation
            assert observation.context is not None
            self.store.begin(observation.context, observation.connection)
            self._publish()
        await self._authorization.stop()

    @property
    def relationship_request(self) -> RelationshipRequest | None:
        return self._relationship_request

    @property
    def relationship_collecting(self) -> bool:
        """Distinguish in-flight collection from a retained, owned task receipt."""
        return self._relationships is not None and not self._relationships.done()

    def select_relationships(
        self,
        root: ResourceTarget,
        resource: ApiResource,
        mode: RelationshipMode,
        *,
        expanded: frozenset[RelationshipPath] = frozenset(),
    ) -> asyncio.Task[None]:
        context = self._current_context()
        connection = self.store.observation.connection
        if root.session != connection.identity:
            raise AppError("The relationship root belongs to an obsolete connection.")
        self._authorization.invalidate()
        self._diagnostics.invalidate()
        self._diagnostic_cancelling = None
        self._relationship_revision += 1
        scope = RelationshipScope(root, resource, connection.namespace, mode)
        request = RelationshipRequest(scope, self._relationship_revision, expanded)
        self._relationship_request = request
        self.pulse_selected = False
        revision = self.store.begin(context, connection)
        self.store.bind_relationships(revision, request)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=connection.namespace != self.sessions.observation.namespace,
                namespace=connection.namespace,
                relationships=request,
            )
        )

    def set_relationship_expanded(
        self, path: RelationshipPath, expanded: bool
    ) -> asyncio.Task[None]:
        request = self._relationship_request
        if request is None:
            raise AppError("Open a relationship view before expanding a reference.")
        paths = set(request.expanded)
        if expanded:
            paths.add(path)
        else:
            paths = {item for item in paths if item[: len(path)] != path}
        return self.select_relationships(
            request.scope.root,
            request.scope.resource,
            request.scope.mode,
            expanded=frozenset(paths),
        )

    def refresh_relationships(self) -> asyncio.Task[None]:
        request = self._relationship_request
        if request is None:
            raise AppError("Open a relationship view before refreshing its evidence.")
        self._relationship_service = None
        return self.select_relationships(
            request.scope.root,
            request.scope.resource,
            request.scope.mode,
            expanded=request.expanded,
        )

    @property
    def discovery(self) -> Discovery | None:
        """Only expose catalogue data belonging to the currently owned client."""
        identity = self.sessions.observation.identity
        if (
            not self._closed
            and identity is not None
            and identity == self.store.observation.connection.identity
            and identity.context == self.store.observation.context
            and self._discovery is not None
            and self._discovery[0] is self.sessions.client
        ):
            return self._discovery[1]
        return None

    def set_query(self, query: ResourceQuery) -> asyncio.Task[None]:
        """Changing API selectors invalidates the old scope before cleanup awaits."""
        return self.select_resource(replace(self.selection, query=query))

    def refresh_discovery(self) -> asyncio.Task[None]:
        context = self._current_context()
        self._discovery = None
        self._relationship_service = None
        if self._diagnostic_scope() is not None:
            return self.refresh_diagnostics()
        if self.authorization_request is not None:
            return self.refresh_authorization()
        connection = self.store.observation.connection
        revision = self.store.begin(context, connection)
        return self._schedule(
            _Selection(
                revision,
                context,
                self.selection,
                change_namespace=connection.namespace != self.sessions.observation.namespace,
                namespace=connection.namespace,
                pulse=self.pulse_selected,
                relationships=self._relationship_request,
            )
        )

    def select_discovered(
        self, name: str, *, group: str | None = None, version: str | None = None
    ) -> asyncio.Task[None]:
        self._current_context()
        discovery = self.discovery
        if discovery is None:
            raise AppError("Wait for the current resource catalogue or refresh discovery.")
        resource = discovery.resolve(name, group=group, version=version)
        return self.select_resource(
            ResourceSelection(resource.name, resource.group, version, server_columns=True)
        )

    async def _stop_watch(self) -> None:
        await self._diagnostics.stop()
        await self._authorization.stop()
        relationships = self._relationships
        if relationships is not None:
            _cancel_once(relationships)
            try:
                await _join(relationships)
            finally:
                self._relationships = None
        pulse = self._pulse
        if pulse is not None:
            _cancel_once(pulse)
            try:
                await _join(pulse)
            finally:
                self._pulse = None
        metrics = self._metrics
        if metrics is not None:
            _cancel_once(metrics)
            try:
                await _join(metrics)
            finally:
                self._metrics = None
                self._metrics_poller = None
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
                if (
                    selection.authenticate is not None
                    and self._desired is None
                    and not self._closed
                ):
                    self.sessions.observation = replace(
                        self.sessions.observation,
                        state=ConnectionState.AUTH_ERROR,
                        message="Azure login was cancelled. Use :login to try again, or r to retry the connection.",
                    )
                    self.store.connected(selection.revision, self.sessions.observation)
                    self._publish()
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
        if selection.diagnostic_cancel:
            await self._finish_diagnostic_cancel(selection)
            return
        try:
            if selection.reconnect:
                self._discovery = None
                observation = (
                    await self.sessions.connect(selection.context)
                    if selection.authenticate is None
                    else await self.sessions.connect(
                        selection.context, authenticate=selection.authenticate
                    )
                )
            else:
                observation = self.sessions.observation
            if selection.revision != self.store.observation.revision:
                return
            if selection.change_namespace and observation.state in USABLE_CONNECTIONS:
                observation = self.sessions.select_namespace(selection.namespace)
            if not self.store.connected(selection.revision, observation):
                return
            self._publish()
            if observation.state not in USABLE_CONNECTIONS:
                return
            client = self.sessions.client
            assert client is not None and observation.identity is not None
            reader = ResourceReader(
                client,
                tables=selection.resource.server_columns or selection.resource.query.compact,
            )
            if self._discovery is None or self._discovery[0] is not client:
                discovery = await reader.discover()
                if selection.revision != self.store.observation.revision:
                    return
                self._discovery = client, discovery
            else:
                discovery = self._discovery[1]
            if selection.diagnostics is not None:
                self._start_diagnostics(selection, client, discovery)
                return
            if selection.authorization is not None:

                def authorization_current(candidate: AuthorizationRequest) -> bool:
                    view = self.store.observation
                    return (
                        not self._closed
                        and self.sessions.client is client
                        and self.sessions.observation.identity == candidate.session
                        and view.revision == selection.revision
                        and self.authorization_request == candidate
                        and view.authorization is not None
                        and view.authorization.request == candidate
                    )

                self._authorization.start(
                    selection.authorization,
                    ResourceReader(client),
                    discovery,
                    selection.revision,
                    self.store,
                    authorization_current,
                    self._publish,
                    self._unexpected,
                )
                self._publish()
                return
            if selection.relationships is not None:
                request = selection.relationships
                if request.scope.root.session != observation.identity:
                    request = replace(
                        request,
                        scope=replace(
                            request.scope,
                            root=replace(request.scope.root, session=observation.identity),
                            namespace=observation.namespace,
                        ),
                    )
                self._relationship_request = request
                self.store.bind_relationships(selection.revision, request)

                def relationship_current(candidate: RelationshipRequest) -> bool:
                    current_view = self.store.observation
                    return (
                        not self._closed
                        and self.sessions.client is client
                        and self.sessions.observation.identity == candidate.scope.root.session
                        and current_view.revision == selection.revision
                        and self._relationship_request == candidate
                        and current_view.relationships is not None
                        and current_view.relationships.request == candidate
                    )

                cached = self._relationship_service
                if cached is None or cached[0] is not client or cached[1].scope != request.scope:
                    service = RelationshipService(
                        ResourceReader(client), discovery, request.scope, relationship_current
                    )
                    self._relationship_service = client, service
                else:
                    service = cached[1]
                    # The graph cache/budget survives expansion, but its outer
                    # workspace revision belongs to this newly owned invocation.
                    service.current = relationship_current
                self._relationships = asyncio.create_task(
                    self._run_relationships(selection.revision, service, request),
                    name="kuberich-relationship-collection",
                )
                self._publish()
                return
            if selection.pulse:
                pulse_scope = PulseScope(observation.identity, observation.namespace)
                self.store.bind_pulse(selection.revision, pulse_scope)

                def pulse_current() -> bool:
                    return (
                        not self._closed
                        and self.sessions.client is client
                        and self.sessions.observation.identity == pulse_scope.session
                        and self.store.observation.revision == selection.revision
                        and self.store.observation.pulse is not None
                        and self.store.observation.pulse.scope == pulse_scope
                    )

                history = self._pulse_history
                pulse_service = PulseService(
                    ResourceReader(client),
                    discovery,
                    pulse_scope,
                    pulse_current,
                    history=(lambda: history(client, pulse_scope)) if history is not None else None,
                )
                self._pulse = asyncio.create_task(
                    self._run_pulse(selection.revision, pulse_service),
                    name="kuberich-cluster-pulse",
                )
                self._publish()
                return
            resource = discovery.find(
                selection.resource.name,
                group=selection.resource.group,
                version=selection.resource.version,
            )
            scope = ResourceScope(
                observation.identity,
                resource,
                observation.namespace if resource.namespaced else None,
                selection.resource.query,
            )
            self.store.bind(selection.revision, scope)
            self._publish()
            if supports_metrics(scope):

                def current() -> bool:
                    return (
                        not self._closed
                        and self.sessions.client is client
                        and self.sessions.observation.identity == scope.session
                        and self.store.observation.revision == selection.revision
                        and self.store.observation.scope == scope
                    )

                self._metrics_poller = MetricsPoller(
                    ResourceReader(client),
                    discovery,
                    scope,
                    lambda: self.store.observation.snapshot,
                    current,
                )
                self._metrics = asyncio.create_task(
                    self._run_metrics(selection.revision, self._metrics_poller),
                    name="kuberich-resource-metrics",
                )
            self._watch = asyncio.create_task(
                self._run_watch(selection.revision, client, scope, reader),
                name="kuberich-resource-watch",
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
                if self._metrics_poller is not None:
                    self._metrics_poller.wake()
                self._publish()

        try:
            await ListWatch(reader, query=scope.query, progress=True).run(
                scope.resource, scope.namespace, receive
            )
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

    async def _run_metrics(self, revision: int, poller: MetricsPoller) -> None:
        def publish(metrics: MetricsSnapshot) -> None:
            if poller.current():
                self.store.observation = replace(self.store.observation, metrics=metrics)
                self._publish()

        try:
            await poller.run(publish)
        except Exception as error:
            self._unexpected(revision, error)

    async def _run_pulse(self, revision: int, service: PulseService) -> None:
        def publish(snapshot: PulseSnapshot) -> None:
            if service.current() and self.store.apply_pulse(revision, snapshot):
                self._publish()

        try:
            await service.run(publish)
        except Exception as error:
            self._unexpected(revision, error)

    async def _run_relationships(
        self, revision: int, service: RelationshipService, request: RelationshipRequest
    ) -> None:
        def publish(snapshot: RelationshipSnapshot) -> None:
            if service.current(request) and self.store.apply_relationships(revision, snapshot):
                self._publish()

        try:
            await service.collect(request, publish)
        except Exception as error:
            self._unexpected(revision, error)

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self._authorization.invalidate()
            self._diagnostics.invalidate()
            self._diagnostic_cancelling = None
            self.store.disconnect()
            self._desired = None
            _cancel_once(self._operation)
            _cancel_once(self._watch)
            _cancel_once(self._metrics)
            _cancel_once(self._pulse)
            _cancel_once(self._relationships)
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
            self._relationship_service = None
            self._relationship_request = None
            for subscription in tuple(self._subscriptions):
                subscription.close()
