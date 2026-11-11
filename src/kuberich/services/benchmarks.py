"""One reviewed bounded HTTP run; its load drains before the owned forward/client."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakSet

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.benchmarks import BenchmarkSettings
from kuberich.domain.benchmark_results import (
    BenchmarkCompletion,
    BenchmarkMetrics,
    BenchmarkProvenance,
    BenchmarkResult,
)
from kuberich.domain.benchmark_targets import (
    BenchmarkBackend,
    backend_matches,
    backend_port,
    pod_ports,
    ready_pod,
    service_endpoints,
)
from kuberich.domain.benchmarks import LoadOptions, RequestOptions, RequestReview, review_request
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.port_forwards import ForwardState, PortMapping, validate_forward_target
from kuberich.domain.relationships import selector_matches
from kuberich.domain.resources import api_segment, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.benchmark_tool import (
    BenchmarkCleanupError,
    BenchmarkTool,
    BenchmarkToolError,
)
from kuberich.services.ownership import finish_owned
from kuberich.services.port_forwards import ForwardInfo, ForwardManager, ForwardService
from kuberich.services.resources import parse_owned


class BenchmarkState(StrEnum):
    IDLE = "idle"
    REVIEWING = "reviewing"
    REVIEWED = "reviewed"
    PROBING = "probing"
    FORWARDING = "forwarding"
    RUNNING = "running"
    REPORTING = "reporting"
    SAVING = "saving"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    TARGET_LOST = "target_lost"
    TOOL_FAILED = "tool_failed"
    MALFORMED_OUTPUT = "malformed_output"
    CLEANUP_FAILED = "cleanup_failed"


class BenchmarkTargetLost(AppError):
    def __init__(self) -> None:
        super().__init__("The reviewed benchmark Service/backend identity or readiness changed.")


@dataclass(frozen=True, slots=True, repr=False)
class BenchmarkReview:
    identity: UUID
    backend: BenchmarkBackend
    request: RequestOptions = field(repr=False)
    load: LoadOptions
    preview: RequestReview
    routing: tuple[object, ...] = field(default=(), repr=False)


def _path(target: ResourceTarget) -> str:
    assert target.namespace is not None
    return (
        "/api/v1/namespaces/"
        + api_segment(target.namespace)
        + "/"
        + target.resource
        + "/"
        + api_segment(target.name)
    )


class BenchmarkService:
    """The service issues and consumes one exact review; callers cannot mint approval."""

    def __init__(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        settings: BenchmarkSettings,
        environment: Mapping[str, str],
        directory: Path,
        forwards: ForwardManager,
        store: BenchmarkStore,
        forward: ForwardInfo | None = None,
        retired: Callable[[BenchmarkService], None] = lambda _: None,
    ) -> None:
        self.client, self.target, self.policy, self.current = client, target, policy, current
        self.settings, self.environment, self.directory = (
            settings,
            dict(environment),
            directory.absolute(),
        )
        self.forwards, self.store, self.forward, self.retired = forwards, store, forward, retired
        self.state, self.message = (
            BenchmarkState.IDLE,
            "Select a backend and review the bounded load.",
        )
        self.result: BenchmarkResult | None = None
        self.save_failed = False
        self._candidates: tuple[BenchmarkBackend, ...] = ()
        self._review: BenchmarkReview | None = None
        self._listeners: set[Callable[[], None]] = set()
        self._jobs: set[asyncio.Task[Any]] = set()
        self._run_task: asyncio.Task[BenchmarkResult] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._closed, self._started = False, False
        self._reason: BenchmarkCompletion = "cancelled"
        self._reads = 0
        self._preparing = False
        self._dedicated: UUID | None = None
        self._ready = False
        self._tool: BenchmarkTool | None = None

    @property
    def operation_count(self) -> int:
        return sum(not task.done() for task in self._jobs)

    @property
    def process_ids(self) -> tuple[int, ...]:
        return () if self._tool is None else self._tool.process_ids

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _publish(self, state: BenchmarkState, message: str) -> None:
        self.state, self.message = state, message
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                self._listeners.discard(listener)

    def require_current(self) -> None:
        self.policy.require(Action.BENCHMARK)
        validate_forward_target(self.target)
        if (
            self._closed
            or not self.current()
            or self.client.context.name != self.target.session.context
            or self.client.configuration is None
        ):
            raise AppError("Benchmark connection changed; capture and review the target again.")
        if self.forward is not None:
            source = self.forwards.owned_source(self.forward.identity, self.forward.attempt)
            if source.client is not self.client or source.target != self.target:
                raise AppError("Benchmark source forward changed; review the current session.")

    def _run_guard(self) -> None:
        self.require_current()
        if self._ready:
            assert self._dedicated is not None
            self.forwards.owned_source(self._dedicated, 0)

    def validate_target(self) -> bool:
        try:
            self.require_current()
        except AppError:
            self.revoke_review()
            self._invalidate()
            return False
        return True

    def revoke_review(self) -> None:
        self._review = None

    def _invalidate(self) -> None:
        self._reason = "target_lost"
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()

    def invalidate(self) -> None:
        """Mark observed connection/forward loss before any screen starts drainage."""
        self.revoke_review()
        self._invalidate()

    async def _owned[T](self, operation: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(operation)
        self._jobs.add(task)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                task.cancel()
                await finish_owned(asyncio.gather(task, return_exceptions=True))
                raise
        finally:
            self._jobs.discard(task)

    async def _get(self, target: ResourceTarget) -> dict[str, Any]:
        self.require_current()
        self._reads += 1
        if self._reads > 128:
            raise AppError("Benchmark target verification exhausted its bounded read budget.")
        async with asyncio.timeout(10):
            payload = await self.client.get_json(_path(target), max_bytes=2 * 1024 * 1024)
        self.require_current()
        return payload

    async def _verify(
        self, backend: BenchmarkBackend, expected: tuple[object, ...] | None = None
    ) -> tuple[object, ...]:
        try:
            return await self._verify_backend(backend, expected)
        except (AppError, ConnectionProblem, TimeoutError):
            raise BenchmarkTargetLost() from None

    async def _verify_backend(
        self, backend: BenchmarkBackend, expected: tuple[object, ...] | None
    ) -> tuple[object, ...]:
        service = None if backend.service is None else await self._get(backend.service)
        pod = await self._get(backend.pod)

        def verify() -> tuple[object, ...]:
            backend_matches(backend, service, pod)
            routing: tuple[object, ...] = (tuple(sorted(pod_ports(backend.pod, pod))),)
            if service is not None:
                assert backend.service is not None
                selector, endpoints = service_endpoints(backend.service, service)
                routing += (selector, tuple(sorted(endpoints, key=lambda endpoint: endpoint.port)))
            if expected is not None and routing != expected:
                raise AppError("Reviewed Service selector or declared backend ports changed.")
            return routing

        routing = await parse_owned(verify)
        self.require_current()
        return routing

    async def candidates(self) -> tuple[BenchmarkBackend, ...]:
        return await self._owned(self._find_candidates())

    async def _find_candidates(self) -> tuple[BenchmarkBackend, ...]:
        self.require_current()
        if self._preparing or self._started:
            raise AppError("A benchmark review or run is already active.")
        self._preparing = True
        self.revoke_review()
        self._candidates = ()
        try:
            source = await self._get(self.target)
            allowed = None if self.forward is None else {p.remote for p in self.forward.mappings}
            if self.target.resource == "pods":
                numbers = await parse_owned(lambda: pod_ports(self.target, source))
                found = tuple(
                    BenchmarkBackend(None, self.target, None, number)
                    for number in sorted({number for _, number in numbers})
                    if allowed is None or number in allowed
                )
            else:
                selector, endpoints = await parse_owned(
                    lambda: service_endpoints(self.target, source)
                )
                assert self.target.namespace is not None
                params = {
                    "limit": "129",
                    "labelSelector": ",".join(
                        item.key + "=" + item.values[0] for item in selector.requirements
                    ),
                }
                self._reads += 1
                if self._reads > 128:
                    raise AppError("Benchmark backend selection exhausted its bounded read budget.")
                async with asyncio.timeout(10):
                    listing = await self.client.get_json(
                        "/api/v1/namespaces/" + api_segment(self.target.namespace) + "/pods",
                        params=params,
                        max_bytes=2 * 1024 * 1024,
                    )
                self.require_current()

                def extract() -> tuple[BenchmarkBackend, ...]:
                    metadata = resource_object(listing.get("metadata"))
                    items = listing.get("items")
                    if (
                        listing.get("apiVersion") != "v1"
                        or listing.get("kind") != "PodList"
                        or not isinstance(items, list)
                        or len(items) > 128
                        or metadata.get("continue") not in {None, ""}
                        or metadata.get("remainingItemCount", 0) != 0
                    ):
                        raise AppError(
                            "Benchmark backend enumeration is incomplete or exceeds 128 Pods."
                        )
                    results = []
                    for raw in items:
                        # Kubernetes list items may omit their TypeMeta. The
                        # already-validated outer v1 PodList supplies only absent
                        # fields; conflicting explicit descriptors still fail.
                        pod = {"apiVersion": "v1", "kind": "Pod", **resource_object(raw)}
                        meta = resource_object(pod.get("metadata"))
                        labels = resource_object(meta.get("labels", {}))
                        if not selector_matches(selector, labels):
                            continue
                        backend = ResourceTarget(
                            self.target.session,
                            "",
                            "pods",
                            self.target.namespace,
                            api_segment(meta.get("name")),
                            api_segment(meta.get("uid")),
                        )
                        status = resource_object(pod.get("status"))
                        if (
                            status.get("phase") != "Running"
                            or meta.get("deletionTimestamp") is not None
                        ):
                            continue
                        conditions = status.get("conditions", [])
                        if not isinstance(conditions, list) or len(conditions) > 128:
                            raise AppError("Invalid benchmark Pod readiness conditions.")
                        if not any(
                            isinstance(c, dict)
                            and c.get("type") == "Ready"
                            and c.get("status") == "True"
                            for c in conditions
                        ):
                            continue
                        ready_pod(backend, pod)
                        for endpoint in endpoints:
                            if allowed is None or endpoint.port in allowed:
                                results.append(
                                    BenchmarkBackend(
                                        self.target,
                                        backend,
                                        endpoint.port,
                                        backend_port(endpoint, backend, pod),
                                    )
                                )
                                if len(results) > 128:
                                    raise AppError("Benchmark backend/port choices exceed 128.")
                    return tuple(results)

                found = await parse_owned(extract)
            self.require_current()
            if not found:
                raise AppError(
                    "No eligible Ready backend and TCP port are available for this benchmark."
                )
            self._candidates = found
            return found
        finally:
            self._preparing = False

    async def review(
        self, backend: BenchmarkBackend, request: RequestOptions, load: LoadOptions
    ) -> BenchmarkReview:
        return await self._owned(self._prepare(backend, request, load))

    async def _prepare(
        self, backend: BenchmarkBackend, request: RequestOptions, load: LoadOptions
    ) -> BenchmarkReview:
        self.require_current()
        self.revoke_review()
        if self._preparing or self._started or not any(backend is b for b in self._candidates):
            raise AppError("Select this owner's current backend before reviewing the load.")
        if not isinstance(request, RequestOptions) or not isinstance(load, LoadOptions):
            raise AppError("Benchmark review requires validated request and load options.")
        self._preparing = True
        self._publish(BenchmarkState.REVIEWING, "Verifying the selected Service and Ready backend.")
        try:
            routing = await self._verify(backend)
            review = BenchmarkReview(
                uuid4(), backend, request, load, review_request(request), routing
            )
            self._review = review
            self._publish(
                BenchmarkState.REVIEWED, "Review this single backend, request and load before Run."
            )
            return review
        finally:
            self._preparing = False

    async def run(self, review: BenchmarkReview) -> BenchmarkResult:
        try:
            self.require_current()
        except AppError:
            self.revoke_review()
            raise
        if review is not self._review or self._started:
            raise AppError("An unused exact benchmark review is required; review again.")
        self.revoke_review()
        self._started = True
        task = asyncio.create_task(self._execute(review))
        self._run_task = task
        self._jobs.add(task)
        try:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                task.cancel()
                await finish_owned(asyncio.gather(task, return_exceptions=True))
                if self.result is None:
                    self._publish(
                        BenchmarkState(self._reason),
                        "Benchmark stopped before execution; no trustworthy metrics are available.",
                    )
                raise
        finally:
            self._jobs.discard(task)

    async def _watch(self, review: BenchmarkReview) -> None:
        check_at = asyncio.get_running_loop().time() + 1
        try:
            while True:
                self._run_guard()
                if asyncio.get_running_loop().time() >= check_at:
                    await self._verify(review.backend, review.routing)
                    check_at = asyncio.get_running_loop().time() + 1
                await asyncio.sleep(0.03)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._invalidate()

    async def _forward_ready(self, identity: UUID) -> int:
        async with asyncio.timeout(20):
            while True:
                self.require_current()
                info = next(
                    (record for record in self.forwards.infos if record.identity == identity), None
                )
                if info is None or info.state in {
                    ForwardState.FAILED,
                    ForwardState.STOPPED,
                    ForwardState.STOPPING,
                    ForwardState.RECONNECTING,
                }:
                    raise AppError("The dedicated benchmark forward could not become ready.")
                if info.state is ForwardState.READY:
                    if info.attempt != 0 or info.address != "127.0.0.1" or len(info.ports) != 1:
                        raise AppError("The dedicated benchmark listener changed.")
                    self.forwards.owned_source(identity, 0)
                    self._ready = True
                    return info.ports[0].local
                await asyncio.sleep(0.03)

    async def _execute(self, review: BenchmarkReview) -> BenchmarkResult:
        started, run_id = datetime.now(UTC), uuid4()
        version: str | None = None
        metrics: BenchmarkMetrics | None = None
        completion: BenchmarkCompletion = "tool_failed"
        monitor: asyncio.Task[None] | None = None

        def unsubscribe() -> None:
            pass

        try:
            self.require_current()
            await self._verify(review.backend, review.routing)
            if self.settings.executable is None:
                raise AppError("Configure an explicit Vegeta executable before Run.")
            tool = BenchmarkTool(
                self.settings.executable,
                self.policy,
                Path(self.client.directory.name),
                self._run_guard,
            )
            self._tool = tool
            self._publish(
                BenchmarkState.PROBING,
                "Checking the explicitly configured Vegeta 12.13.0 executable.",
            )
            version = await tool.probe()
            await self._verify(review.backend, review.routing)
            self._publish(
                BenchmarkState.FORWARDING, "Starting a dedicated loopback Pod forward; no load yet."
            )
            source = ForwardService(
                self.client,
                review.backend.pod,
                self.policy,
                self.current,
                environment=self.environment,
                directory=self.directory,
            )

            def changed(info: ForwardInfo) -> None:
                if info.identity == self._dedicated and (
                    info.attempt != 0
                    or info.state
                    in {
                        ForwardState.RECONNECTING,
                        ForwardState.FAILED,
                        ForwardState.STOPPED,
                        ForwardState.STOPPING,
                    }
                ):
                    self._invalidate()

            unsubscribe = self.forwards.subscribe(changed)
            self.require_current()
            self._dedicated = self.forwards.start(
                source, (PortMapping(0, review.backend.pod_port),), "127.0.0.1", retries=0
            )
            port = await self._forward_ready(self._dedicated)
            await self._verify(review.backend, review.routing)
            monitor = asyncio.create_task(self._watch(review))
            self._publish(
                BenchmarkState.RUNNING,
                "Running reviewed HTTP load; Cancel drains it before releasing the forward.",
            )
            metrics = await tool.execute(
                review.request,
                review.load,
                port,
                version=version,
                reporting=lambda: self._publish(
                    BenchmarkState.REPORTING, "Load stopped; decoding the bounded private report."
                ),
            )
            self._run_guard()
            completion = "complete"
        except asyncio.CancelledError:
            completion, metrics = self._reason, None
        except BenchmarkCleanupError:
            completion, metrics = "cleanup_failed", None
        except BenchmarkTargetLost:
            completion, metrics = "target_lost", None
        except BenchmarkToolError as error:
            completion, metrics = (
                ("malformed_output" if error.reason == "malformed_output" else "tool_failed"),
                None,
            )
        except Exception:
            completion, metrics = (
                ("target_lost" if not self.validate_target() else "tool_failed"),
                None,
            )
        finally:
            if monitor is not None:
                monitor.cancel()
                await finish_owned(asyncio.gather(monitor, return_exceptions=True))
            unsubscribe()
            if self._dedicated is not None:
                try:
                    await self.forwards.stop(self._dedicated)
                except asyncio.CancelledError:
                    completion, metrics = self._reason, None
                except Exception:
                    completion, metrics = "cleanup_failed", None
            self._ready = False
            self.environment.clear()
        backend = review.backend
        assert backend.pod.namespace is not None
        provenance = BenchmarkProvenance(
            backend.pod.session.context,
            backend.pod.namespace,
            backend.pod.name,
            backend.pod.uid,
            backend.pod_port,
            None if backend.service is None else backend.service.name,
            None if backend.service is None else backend.service.uid,
            backend.service_port,
        )
        self.result = BenchmarkResult(
            run_id,
            started,
            datetime.now(UTC),
            version,
            provenance,
            review.request.method,
            review.load,
            completion,
            metrics,
        )
        self._publish(
            BenchmarkState.SAVING, "Owned load and forward drained; saving a redacted local result."
        )
        try:
            await self.store.save(self.result)
        except (Exception, asyncio.CancelledError):
            self.save_failed = True
        self._publish(
            BenchmarkState(completion),
            "Benchmark cleanup could not be confirmed; the run is incomplete."
            if completion == "cleanup_failed"
            else "Benchmark complete; local result saved."
            if completion == "complete" and not self.save_failed
            else "Result remains visible; local save failed."
            if self.save_failed
            else "Benchmark incomplete; all admitted local work was drained.",
        )
        return self.result

    async def cancel(self) -> None:
        self.revoke_review()
        tasks = tuple(task for task in self._jobs if task is not asyncio.current_task())
        for task in tasks:
            if not task.done():
                task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        if self.result is None:
            self._publish(
                BenchmarkState(self._reason),
                "Benchmark cancelled before execution; no trustworthy metrics are available."
                if self._reason == "cancelled"
                else "Benchmark target changed; no trustworthy metrics are available.",
            )

    async def _stop(self) -> None:
        await self.cancel()
        self._candidates = ()
        self._listeners.clear()
        self.environment.clear()
        self.retired(self)

    async def stop_owned(self) -> None:
        self._closed = True
        if self._closing is None:
            self._closing = asyncio.create_task(self._stop())
        await finish_owned(self._closing)


class BenchmarkManager:
    """One app-wide owner, retained through report/persistence and detached-screen cleanup."""

    def __init__(self, forwards: ForwardManager, store: BenchmarkStore) -> None:
        self.forwards, self.store = forwards, store
        self._active: BenchmarkService | None = None
        self._retired: WeakSet[KubernetesSession] = WeakSet()
        self._closed = False

    @property
    def active_count(self) -> int:
        return int(self._active is not None)

    def _retire(self, service: BenchmarkService) -> None:
        if self._active is service:
            self._active = None

    def create(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        settings: BenchmarkSettings,
        environment: Mapping[str, str],
        directory: Path,
        forward: ForwardInfo | None = None,
    ) -> BenchmarkService:
        if self._closed or self._active is not None or client in self._retired:
            raise AppError(
                "A benchmark viewer is active or draining; close it before starting another."
            )
        owner = BenchmarkService(
            client,
            target,
            policy,
            current,
            settings=settings,
            environment=environment,
            directory=directory,
            forwards=self.forwards,
            store=self.store,
            forward=forward,
            retired=self._retire,
        )
        owner.require_current()
        self._active = owner
        return owner

    async def close_for_client(self, client: KubernetesSession) -> None:
        self.invalidate_for_client(client)
        if self._active is not None and self._active.client is client:
            await self._active.stop_owned()

    def invalidate_for_client(self, client: KubernetesSession) -> None:
        """Retire starts and classify target loss before UI cleanup can retire the owner."""
        self._retired.add(client)
        if self._active is not None and self._active.client is client:
            self._active.invalidate()

    async def close(self) -> None:
        self._closed = True
        if self._active is not None:
            await self._active.stop_owned()
