"""Connection-owned finite history collection, identity checks and bounded cache."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from kuberich.adapters.history_http import ExternalHistoryTransport
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    namespace_name,
)
from kuberich.domain.history import (
    HISTORY_CACHE_TTL,
    MAX_HISTORY_CACHE_BYTES,
    MAX_HISTORY_CACHE_ENTRIES,
    MAX_HISTORY_CACHE_POINTS,
    BackendCandidate,
    BackendCandidates,
    EndpointIdentity,
    EndpointStatus,
    ExternalHistoryBackend,
    HistoryBackend,
    HistoryOptions,
    HistoryRequest,
    HistoryScope,
    HistorySnapshot,
    HistoryStatus,
    MembershipEvidence,
    Provider,
    SourceStatus,
    build_history_plan,
    current_history_members,
    history_window,
)
from kuberich.domain.pulse import PulseScope
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.resources import Discovery, ResourceRecord
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.history import HistoryReader, HistoryTransport, ServiceHistoryTransport
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader


@dataclass(frozen=True)
class _Entry:
    snapshot: HistorySnapshot
    at: float
    points: int
    size: int


class HistoryWorkspace:
    """One owner per connection, with a replaceable latest collection intent."""

    def __init__(
        self,
        client: KubernetesSession,
        discovery: Discovery,
        session: SessionIdentity,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        observed_session: Callable[[], SessionIdentity | None],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client: KubernetesSession | None = client
        self._discovery = discovery
        self._connection = (session.context, session.connection_id)
        self._policy, self._current, self._observed_session = policy, current, observed_session
        self._now, self._monotonic = now, monotonic
        self._intent = self._revision = 0
        self._closed = False
        self._detail: HistoryScope | None = None
        self._active: asyncio.Task[HistorySnapshot] | None = None
        self._detection: asyncio.Task[BackendCandidates] | None = None
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[object, _Entry] = OrderedDict()
        self._external: ExternalHistoryTransport | None = None
        self._external_endpoint: ExternalHistoryBackend | None = None
        self._service_uids: OrderedDict[HistoryBackend, str] = OrderedDict()
        self._snapshot = HistorySnapshot()
        self._overview_snapshot = HistorySnapshot()

    @property
    def snapshot(self) -> HistorySnapshot:
        return self._snapshot.fresh(self._now())

    @property
    def config_revision(self) -> int:
        return self._revision

    @property
    def operation_count(self) -> int:
        return (
            int(self._active is not None and not self._active.done())
            + int(self._detection is not None and not self._detection.done())
            + (self._external.operation_count if self._external is not None else 0)
        )

    @property
    def retained_points(self) -> int:
        return sum(entry.points for entry in self._cache.values())

    @property
    def retained_bytes(self) -> int:
        return sum(entry.size for entry in self._cache.values())

    def require_current(self, scope: HistoryScope) -> None:
        observed = self._observed_session()
        if (
            self._closed
            or not self._current()
            or observed != scope.session
            or (observed is None or (observed.context, observed.connection_id) != self._connection)
        ):
            raise AppError("History scope belongs to an obsolete connection or generation.")
        self._policy.require(Action.READ)

    def observe_target(self, scope: HistoryScope, record: ResourceRecord | None) -> None:
        self.require_current(scope)
        target = scope.target
        if target is None:
            return
        if (
            record is None
            or (record.name, record.namespace, record.uid)
            != (target.name, target.namespace, target.uid)
            or (scope.created_at is not None and record.created_at != scope.created_at)
        ):
            self.invalidate()
            raise AppError("History target changed; select the current object again.")
        if scope.kind == "container":
            spec = record.manifest.get("spec", {})
            declarations = spec.get(scope.container_field, []) if isinstance(spec, dict) else []
            if not isinstance(declarations, list) or not any(
                isinstance(item, dict) and item.get("name") == target.container
                for item in declarations
            ):
                self.invalidate()
                raise AppError("History container declaration changed; select it again.")

    def invalidate(self) -> None:
        """Revoke publication synchronously, before any asynchronous drainage."""
        self._intent += 1
        self._revision += 1
        self._cache.clear()
        self._snapshot = HistorySnapshot()
        self._overview_snapshot = HistorySnapshot()
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for task in (self._active, self._detection):
            # Target validation revokes this collector before returning a typed conflict.
            if task is not None and task is not current:
                task.cancel()

    def enter_detail(self, scope: HistoryScope) -> None:
        self.require_current(scope)
        self.invalidate()
        self._detail = scope

    async def _drain_active(self) -> None:
        task = self._active
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            if self._active is task:
                self._active = None

    async def leave_detail(self) -> None:
        self.invalidate()
        await self._drain_active()
        self._detail = None

    def selected_candidate(
        self, candidate: BackendCandidate, options: HistoryOptions | None = None
    ) -> HistoryOptions:
        source = options.endpoint if options is not None else None
        endpoint = HistoryBackend(
            candidate.namespace,
            candidate.service,
            candidate.port,
            candidate.scheme,
            source.matchers if source is not None else (),
            source.cluster_label if source is not None else None,
            source.cluster_value if source is not None else None,
        )
        self.invalidate()
        self._service_uids[endpoint] = candidate.uid
        self._service_uids.move_to_end(endpoint)
        while len(self._service_uids) > 16:
            self._service_uids.popitem(last=False)
        return (
            replace(options, endpoint=endpoint, api_prefix=candidate.prefix)
            if options
            else HistoryOptions(
                endpoint, provider=candidate.provider_hint, api_prefix=candidate.prefix
            )
        )

    async def overview(self, scope: PulseScope, options: HistoryOptions | None) -> HistorySnapshot:
        if options is None:
            return HistorySnapshot()

        def paused() -> HistorySnapshot:
            cached = self._overview_snapshot.fresh(self._now())
            return (
                cached
                if cached.status is not HistoryStatus.UNCONFIGURED
                else HistorySnapshot(
                    HistoryStatus.UNAVAILABLE,
                    detail="Overview history is paused while metric details are foreground.",
                    scope_label=options.endpoint.scope_label(scope.namespace),
                )
            )

        if self._detail is not None:
            return paused()
        start, end, step = history_window(self._now(), 900)
        try:
            snapshot = await self.collect(
                HistoryRequest(
                    uuid4(),
                    HistoryScope(scope.session, "cluster", scope.namespace),
                    options,
                    start,
                    end,
                    step,
                    ("cpu", "memory"),
                    self._revision,
                )
            )
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if caller is None or caller.cancelling():
                raise
            return paused()
        self._overview_snapshot = snapshot
        return snapshot

    async def collect(self, request: HistoryRequest) -> HistorySnapshot:
        self.require_current(request.scope)
        if request.config_revision != self._revision:
            raise AppError("History configuration changed; refresh the request.")
        self._intent += 1
        intent = self._intent
        if self._detection is not None:
            self._detection.cancel()
            await finish_owned(asyncio.gather(self._detection, return_exceptions=True))
        if self._active is not None:
            self._active.cancel()
        async with self._lock:
            await self._drain_active()
            if intent != self._intent:
                raise asyncio.CancelledError
            self.require_current(request.scope)
            task = asyncio.create_task(
                self._collect(request, intent), name="kuberich-history-collection"
            )
            self._active = task
        try:
            return await task
        finally:
            if self._active is task and task.done():
                self._active = None

    def _valid(self, request: HistoryRequest, intent: int) -> bool:
        try:
            self.require_current(request.scope)
        except AppError:
            return False
        return intent == self._intent and request.config_revision == self._revision

    async def _target(self, reader: ResourceReader, scope: HistoryScope) -> None:
        if scope.target is not None and scope.resource is not None:
            self.observe_target(
                scope,
                await reader.get(
                    scope.resource, scope.target.name, scope.target.namespace, max_bytes=1024 * 1024
                ),
            )

    async def _service(self, reader: ResourceReader, endpoint: HistoryBackend) -> str:
        service = await reader.get(
            self._discovery.find("services"),
            endpoint.service,
            endpoint.namespace,
            max_bytes=1024 * 1024,
        )
        spec = service.manifest.get("spec", {})
        ports = spec.get("ports", []) if isinstance(spec, dict) else []
        if not isinstance(ports, list):
            ports = []
        if (
            service.uid is None
            or not isinstance(spec, dict)
            or spec.get("type") == "ExternalName"
            or (
                not any(
                    isinstance(port, dict) and port.get("port") == endpoint.port for port in ports
                )
            )
        ):
            raise AppError("History Service identity or port is unavailable.")
        previous = self._service_uids.setdefault(endpoint, service.uid)
        self._service_uids.move_to_end(endpoint)
        while len(self._service_uids) > 16:
            self._service_uids.popitem(last=False)
        if previous != service.uid:
            self._cache.clear()
            raise AppError("History Service was replaced; select the backend again.")
        return service.uid

    async def _membership(self, reader: ResourceReader, scope: HistoryScope) -> MembershipEvidence:
        if scope.membership != "current-members" or scope.target is None or scope.resource is None:
            return MembershipEvidence(mode=scope.membership)
        pods_resource = self._discovery.find("pods")
        pods = await reader.list(
            pods_resource,
            scope.namespace,
            page_size=64,
            max_items=256,
            max_retained_bytes=1024 * 1024,
        )
        intermediates = None
        if scope.resource.name in {"deployments", "cronjobs"}:
            resource = self._discovery.find(
                "replicasets" if scope.resource.name == "deployments" else "jobs",
                group="apps" if scope.resource.name == "deployments" else "batch",
            )
            intermediates = await reader.list(
                resource,
                scope.namespace,
                page_size=64,
                max_items=256,
                max_retained_bytes=1024 * 1024,
            )
        after = await reader.list(
            pods_resource,
            scope.namespace,
            page_size=64,
            max_items=256,
            max_retained_bytes=1024 * 1024,
        )
        return replace(
            current_history_members(scope.target, scope.resource, pods, intermediates, after),
            observed_at=self._now(),
        )

    async def _collect(self, request: HistoryRequest, intent: int) -> HistorySnapshot:
        client = self._client
        if client is None:
            raise AppError("History connection is closed.")
        reader = ResourceReader(client, budget=ReadBudget(64))
        endpoint = request.options.endpoint
        service_transport: ServiceHistoryTransport | None = None
        transport: HistoryTransport
        try:
            async with asyncio.timeout(30):
                await self._target(reader, request.scope)
                membership = await self._membership(reader, request.scope)
                auth_revision = "service"
                if isinstance(endpoint, HistoryBackend):
                    uid = await self._service(reader, endpoint)
                    identity = EndpointIdentity(
                        "service",
                        request.options.provider,
                        endpoint.namespace,
                        endpoint.service,
                        uid,
                        prefix=request.options.api_prefix,
                    )
                    service_transport = ServiceHistoryTransport(
                        client,
                        endpoint,
                        uid,
                        prefix=request.options.api_prefix,
                        budget=reader.budget,
                    )
                    transport = service_transport
                else:
                    if self._external_endpoint != endpoint:
                        if self._external is not None:
                            await self._external.close()
                        self._cache.clear()
                        self._external = ExternalHistoryTransport(endpoint)
                        self._external_endpoint = endpoint
                    assert self._external is not None
                    previous_auth = self._external.auth_revision
                    try:
                        auth_revision = await self._external.prepare()
                    except AppError:
                        self._cache.clear()
                        raise
                    if previous_auth != auth_revision:
                        self._cache.clear()
                        self._snapshot = HistorySnapshot(
                            HistoryStatus.LOADING,
                            detail="External history authentication changed; collecting new data.",
                        )
                    identity = EndpointIdentity(
                        "external",
                        request.options.provider,
                        origin=endpoint.origin,
                        prefix=endpoint.prefix,
                    )
                    transport = self._external
                key = (
                    request.scope,
                    request.options,
                    request.start,
                    request.end,
                    request.step_seconds,
                    request.families,
                    request.config_revision,
                    identity,
                    auth_revision,
                    (
                        membership.mode,
                        membership.status,
                        membership.members,
                        membership.fingerprint,
                    ),
                )
                entry = self._cache.get(key)
                if entry is not None and 0 <= self._monotonic() - entry.at < HISTORY_CACHE_TTL:
                    snapshot = replace(entry.snapshot, request_id=request.id)
                    self._cache.move_to_end(key)
                else:
                    plan = build_history_plan(request, membership)
                    snapshot = await HistoryReader().collect(
                        transport, plan, lambda: self._valid(request, intent), now=self._now
                    )
                    endpoint_statuses: dict[HistoryStatus, EndpointStatus] = {
                        HistoryStatus.UNAUTHORIZED: "unauthorized",
                        HistoryStatus.FORBIDDEN: "forbidden",
                        HistoryStatus.TIMEOUT: "timeout",
                        HistoryStatus.UNAVAILABLE: "unavailable",
                        HistoryStatus.INVALID_RESPONSE: "invalid-response",
                        HistoryStatus.FAILED: "invalid-response",
                    }
                    endpoint_status = endpoint_statuses.get(snapshot.status, "compatible")
                    snapshot = replace(
                        snapshot,
                        endpoint_identity=replace(
                            identity,
                            status=endpoint_status,
                            compatibility="Prometheus-compatible; provider hint is not engine identity",
                        ),
                    )
                await self._target(reader, request.scope)
                if isinstance(endpoint, HistoryBackend):
                    await self._service(reader, endpoint)
                elif self._external is not None and await self._external.prepare() != auth_revision:
                    self._cache.clear()
                    raise AppError("External history authentication changed; refresh the request.")
                if not self._valid(request, intent):
                    raise asyncio.CancelledError
                self._snapshot = snapshot
                self._retain(key, snapshot)
                return snapshot
        except (AppError, ConnectionProblem, TimeoutError, ReadBudgetExceeded) as error:
            status = (
                HistoryStatus.UNAUTHORIZED
                if isinstance(error, HttpProblem) and error.status == 401
                else HistoryStatus.FORBIDDEN
                if isinstance(error, HttpProblem) and error.status == 403
                else (
                    HistoryStatus.TIMEOUT
                    if isinstance(error, TimeoutError)
                    or (
                        isinstance(error, ConnectionProblem)
                        and error.state is ConnectionState.TIMEOUT
                    )
                    else HistoryStatus.CONFIGURATION_CONFLICT
                    if isinstance(error, AppError)
                    else HistoryStatus.UNAVAILABLE
                )
            )
            snapshot = HistorySnapshot(
                status,
                self._now(),
                request.start,
                request.end,
                request.step_seconds,
                detail="History collection is unavailable; verify the selected scope and backend.",
                request_id=request.id,
            )
            if self._valid(request, intent):
                self._snapshot = snapshot
            return snapshot
        finally:
            if service_transport is not None:
                await finish_owned(asyncio.create_task(service_transport.close()))

    def _retain(self, key: object, snapshot: HistorySnapshot) -> None:
        if snapshot.status not in {
            HistoryStatus.VALID,
            HistoryStatus.PARTIAL,
            HistoryStatus.NO_DATA,
        }:
            return
        points = sum(len(item.points) for item in snapshot.series)
        size = 32768 + max(
            snapshot.accounted_bytes,
            points * 512 + sum(256 + 4 * len(repr(item.labels)) for item in snapshot.series),
        )
        if points > MAX_HISTORY_CACHE_POINTS or size > MAX_HISTORY_CACHE_BYTES:
            return
        self._cache[key] = _Entry(snapshot, self._monotonic(), points, size)
        self._cache.move_to_end(key)
        for old_key, entry in tuple(self._cache.items()):
            if self._monotonic() - entry.at >= HISTORY_CACHE_TTL:
                del self._cache[old_key]
        while (
            len(self._cache) > MAX_HISTORY_CACHE_ENTRIES
            or self.retained_points > MAX_HISTORY_CACHE_POINTS
            or self.retained_bytes > MAX_HISTORY_CACHE_BYTES
        ):
            self._cache.popitem(last=False)

    async def detect(self, namespaces: tuple[str, ...]) -> BackendCandidates:
        if not 1 <= len(namespaces) <= 4 or len(set(namespaces)) != len(namespaces):
            raise AppError("History detection requires one to four exact namespaces.")
        for namespace in namespaces:
            namespace_name(namespace)
        observed = self._observed_session()
        if observed is None:
            raise AppError("History detection requires a current connection.")
        self.require_current(HistoryScope(observed, "cluster"))
        self.invalidate()
        await self._drain_active()
        if self._detection is not None:
            self._detection.cancel()
            await finish_owned(asyncio.gather(self._detection, return_exceptions=True))
        task = asyncio.create_task(self._detect(namespaces))
        intent = self._intent
        self._detection = task
        try:
            candidates = await task
            self.require_current(HistoryScope(observed, "cluster"))
            if intent != self._intent:
                raise asyncio.CancelledError
            return candidates
        finally:
            if self._detection is task:
                self._detection = None

    async def _detect(self, namespaces: tuple[str, ...]) -> BackendCandidates:
        if self._client is None:
            raise AppError("History connection is closed.")
        reader = ResourceReader(self._client, budget=ReadBudget(16))
        resource = self._discovery.find("services")
        candidates: list[BackendCandidate] = []
        sources: list[tuple[str, SourceStatus]] = []
        retained = inspected = 0
        complete = True
        async with asyncio.timeout(30):
            for namespace in namespaces:
                try:
                    snapshot = await reader.list(
                        resource,
                        namespace,
                        page_size=32,
                        max_items=128 - inspected,
                        max_retained_bytes=1024 * 1024 - retained,
                    )
                    inspected += len(snapshot.items)
                    retained += snapshot.collection.retained_bytes
                    complete &= snapshot.collection.complete
                    sources.append(
                        (namespace, "available" if snapshot.collection.complete else "partial")
                    )
                    for record in snapshot.items:
                        data = record.manifest
                        spec = data.get("spec", {})
                        labels = data.get("metadata", {}).get("labels", {})
                        if not isinstance(labels, dict):
                            labels = {}
                        if (
                            not isinstance(spec, dict)
                            or spec.get("type") == "ExternalName"
                            or not record.uid
                        ):
                            continue
                        hint: Provider = "auto"
                        names = " ".join(
                            str(labels.get(key, ""))
                            for key in (
                                "app",
                                "app.kubernetes.io/name",
                                "app.kubernetes.io/component",
                            )
                        ).lower()
                        for name in ("prometheus", "victoriametrics", "thanos"):
                            if name in names:
                                hint = name
                        ports = spec.get("ports", [])
                        for port in ports if isinstance(ports, list) else []:
                            if not isinstance(port, dict) or type(port.get("port")) is not int:
                                continue
                            port_name = port.get("name", "")
                            if hint == "auto" and port_name not in {
                                "prometheus",
                                "http-metrics",
                                "http-query",
                                "vmselect",
                            }:
                                continue
                            if len(candidates) == 16:
                                complete = False
                                break
                            candidates.append(
                                BackendCandidate(
                                    namespace,
                                    record.name,
                                    record.uid,
                                    port["port"],
                                    provider_hint=hint,
                                )
                            )
                except (AppError, ConnectionProblem, ReadBudgetExceeded):
                    complete = False
                    sources.append((namespace, "unavailable"))
        return BackendCandidates(tuple(candidates), complete, tuple(sources))

    async def close(self) -> None:
        self._closed = True
        self.invalidate()
        await self._drain_active()
        if self._detection is not None:
            await finish_owned(asyncio.gather(self._detection, return_exceptions=True))
            self._detection = None
        if self._external is not None:
            await finish_owned(asyncio.create_task(self._external.close()))
            self._external = None
        self._client = None
        self._detail = None
