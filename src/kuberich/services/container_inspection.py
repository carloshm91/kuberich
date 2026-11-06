"""Finite, fresh and explicitly disclosed container configuration observations."""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from typing import Any, Literal
from uuid import UUID, uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    ResponseLimitExceeded,
)
from kuberich.domain.container_inspection import (
    MAX_GET_BYTES,
    MAX_INPUT_BYTES,
    MAX_READS,
    ContainerIdentity,
    EntryId,
    InspectionSnapshot,
    ReasonCode,
    ResolvedValue,
    SourceRead,
    SourceRef,
    SourceState,
    build_inspection,
    object_binding,
    reference_plan,
    resolve_selected,
)
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader, parse_owned

MAX_OPERATION_SECONDS = 30.0
STALE_MESSAGE = "Container configuration changed; reload required."
INTENT_MESSAGE = "Disclosure intent expired; select the entry again."


@dataclass(frozen=True, slots=True)
class DisclosureIntent:
    token: UUID
    snapshot_id: UUID
    entry: EntryId
    action: Literal["reveal", "copy"]
    generation: int


@dataclass(slots=True)
class _Reads:
    reader: ResourceReader
    retained: int = 0
    limited: bool = False


async def _drain(task: asyncio.Task[Any]) -> None:
    """Retrieve completion even when an outer owner is cancelled repeatedly."""
    await finish_owned(asyncio.gather(task, return_exceptions=True))


def _source_state(problem: ConnectionProblem) -> SourceState:
    if isinstance(problem, HttpProblem):
        if problem.status == 404:
            return "not-found"
        if problem.status in {401, 403}:
            return "forbidden"
    if problem.state is ConnectionState.TIMEOUT:
        return "timed-out"
    if problem.state is ConnectionState.API_ERROR:
        return "invalid"
    return "unreachable"


class ContainerInspectionService:
    """Own one captured client/Pod/container and drain before releasing that client."""

    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        container: ContainerIdentity,
        discovery: Discovery,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        now: Callable[[], datetime],
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.container, self.discovery, self.policy = container, discovery, policy
        self.current, self.now = current, now
        self._client = client
        self._captured_target = target
        self._snapshot: InspectionSnapshot | None = None
        self._operation: asyncio.Task[Any] | None = None
        self._operation_kind: Literal["index", "disclosure"] | None = None
        self._generation = 0
        self._intent_generation = 0
        self._intent: DisclosureIntent | None = None
        self._closed = False

    @property
    def operation_count(self) -> int:
        return int(self._operation is not None and not self._operation.done())

    @property
    def snapshot(self) -> InspectionSnapshot | None:
        return self._snapshot

    def require_current(self) -> None:
        self.policy.require(Action.READ)
        if (
            self._closed
            or not self.current()
            or self.client is not self._client
            or self.target != self._captured_target
            or self.client.context.name != self.target.session.context
            or (self.resource.group, self.resource.version, self.resource.name, self.resource.kind)
            != ("", "v1", "pods", "Pod")
            or not self.resource.namespaced
            or "get" not in self.resource.verbs
            or self.target.group != ""
            or self.target.resource != "pods"
            or self.target.namespace is None
            or self.target.container not in {None, self.container.name}
            or self.container.field not in {"containers", "initContainers", "ephemeralContainers"}
        ):
            raise AppError("Container inspection target is unavailable; select it again.")

    def snapshot_current(self, snapshot_id: UUID) -> bool:
        try:
            self.require_current()
        except AppError:
            return False
        return self._snapshot is not None and self._snapshot.id == snapshot_id

    def _check(self, generation: int, intent_generation: int | None = None) -> None:
        self.require_current()
        if generation != self._generation:
            raise AppError(STALE_MESSAGE)
        if intent_generation is not None and intent_generation != self._intent_generation:
            raise AppError(INTENT_MESSAGE)

    async def _own[T](
        self,
        operation: Coroutine[Any, Any, T],
        kind: Literal["index", "disclosure"],
    ) -> T:
        generation = self._generation
        intent_generation = self._intent_generation if kind == "disclosure" else None
        task = asyncio.create_task(operation)
        self._operation, self._operation_kind = task, kind
        try:
            result = await asyncio.shield(task)
            # A completed child can no longer be cancelled. Revalidate after its
            # completion callback hands control back to this public caller.
            self._check(generation, intent_generation)
            return result
        except asyncio.CancelledError:
            task.cancel()
            await _drain(task)
            raise
        finally:
            if self._operation is task:
                self._operation, self._operation_kind = None, None

    def _descriptor(self, ref: SourceRef) -> ApiResource | None:
        name = "configmaps" if ref.kind == "ConfigMap" else "secrets"
        matches = tuple(
            item
            for item in self.discovery.resources
            if (item.group, item.version, item.name, item.kind) == ("", "v1", name, ref.kind)
            and item.namespaced
            and "get" in item.verbs
        )
        return matches[0] if len(matches) == 1 else None

    def _retire(self, snapshot_id: UUID) -> None:
        if self._snapshot is not None and self._snapshot.id == snapshot_id:
            self._snapshot = None
            self._generation += 1
            self._intent_generation += 1
            self._intent = None

    async def _pod(
        self,
        reads: _Reads,
        generation: int,
        intent: int | None,
        *,
        snapshot_id: UUID | None = None,
    ) -> ResourceRecord:
        self._check(generation, intent)
        remaining = MAX_INPUT_BYTES - reads.retained
        if remaining <= 0:
            raise AppError("Container inspection input limit reached; reload required.")
        record = await reads.reader.get(
            self.resource,
            self.target.name,
            self.target.namespace,
            max_bytes=min(MAX_GET_BYTES, remaining),
        )
        self._check(generation, intent)
        await parse_owned(partial(object_binding, record, kind="Pod"))
        self._check(generation, intent)
        if record.uid != self.target.uid:
            if snapshot_id is not None:
                self._retire(snapshot_id)
            raise AppError(STALE_MESSAGE)
        reads.retained += record.size_bytes
        if reads.retained > MAX_INPUT_BYTES:
            raise AppError("Container inspection input limit reached; reload required.")
        return record

    async def _sources(
        self,
        pod: ResourceRecord,
        reads: _Reads,
        generation: int,
        intent: int | None,
    ) -> tuple[SourceRead, ...]:
        plan = await parse_owned(partial(reference_plan, pod, self.container))
        self._check(generation, intent)
        results = []
        for ref in plan.refs:
            self._check(generation, intent)
            resource = self._descriptor(ref)
            # Reserve the final Pod check while all consumed source inputs remain owned.
            remaining = MAX_INPUT_BYTES - reads.retained - pod.size_bytes
            if resource is None:
                results.append(SourceRead(ref, "unsupported", None, self.now()))
                continue
            if remaining <= 0:
                reads.limited = True
                results.append(SourceRead(ref, "not-collected-limit", None, self.now()))
                continue
            try:
                record = await reads.reader.get(
                    resource,
                    ref.name,
                    ref.namespace,
                    max_bytes=min(MAX_GET_BYTES, remaining),
                )
                self._check(generation, intent)
                await parse_owned(partial(object_binding, record, kind=ref.kind))
                self._check(generation, intent)
                if record.size_bytes > remaining:
                    reads.limited = True
                    results.append(SourceRead(ref, "not-collected-limit", None, self.now()))
                    continue
                reads.retained += record.size_bytes
                results.append(SourceRead(ref, "available", record, self.now()))
            except ConnectionProblem as problem:
                self._check(generation, intent)
                if remaining < MAX_GET_BYTES and isinstance(problem, ResponseLimitExceeded):
                    reads.limited = True
                results.append(SourceRead(ref, _source_state(problem), None, self.now()))
            except (AppError, ReadBudgetExceeded):
                self._check(generation, intent)
                results.append(SourceRead(ref, "invalid", None, self.now()))
        return tuple(results)

    async def index(self) -> InspectionSnapshot:
        self.require_current()
        self.invalidate()
        generation = self._generation
        previous = self._operation
        if previous is not None:
            completion = asyncio.gather(previous, return_exceptions=True)
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError:
                await finish_owned(completion)
                raise
        self._check(generation)
        return await self._own(self._index(generation), "index")

    async def _index(self, generation: int) -> InspectionSnapshot:
        try:
            async with asyncio.timeout(MAX_OPERATION_SECONDS):
                started = self.now()
                budget = ReadBudget(MAX_READS)
                reads = _Reads(ResourceReader(self.client, tables=False, budget=budget))
                pod = await self._pod(reads, generation, None)
                sources = await self._sources(pod, reads, generation, None)
                final = await self._pod(reads, generation, None)
                initial_binding = await parse_owned(partial(object_binding, pod, kind="Pod"))
                final_binding = await parse_owned(partial(object_binding, final, kind="Pod"))
                self._check(generation)
                if initial_binding != final_binding:
                    raise AppError(STALE_MESSAGE)
                result = await parse_owned(
                    partial(
                        build_inspection,
                        pod,
                        self.container,
                        sources,
                        target=self.target,
                        snapshot_id=uuid4(),
                        started_at=started,
                        observed_at=self.now(),
                        reads=budget.used,
                    )
                )
                self._check(generation)
                if reads.limited:
                    result = replace(
                        result,
                        complete=False,
                        notices=tuple(dict.fromkeys((*result.notices, ReasonCode.INPUT_LIMIT))),
                    )
                self._snapshot = result
                return result
        except TimeoutError:
            raise AppError("Container inspection timed out; reload required.") from None
        except (ConnectionProblem, ReadBudgetExceeded):
            raise AppError("Container inspection read failed; reload required.") from None

    def new_intent(
        self, snapshot_id: UUID, entry: EntryId, action: Literal["reveal", "copy"]
    ) -> DisclosureIntent:
        self.require_current()
        if (
            not self.snapshot_current(snapshot_id)
            or self._snapshot is None
            or not any(item.id == entry for item in self._snapshot.entries)
            or action not in {"reveal", "copy"}
        ):
            raise AppError(INTENT_MESSAGE)
        self.cancel_disclosure()
        intent = DisclosureIntent(uuid4(), snapshot_id, entry, action, self._intent_generation)
        self._intent = intent
        return intent

    async def disclose(self, intent: DisclosureIntent) -> ResolvedValue:
        self.require_current()
        snapshot = self._snapshot
        if (
            self._intent != intent
            or snapshot is None
            or not self.snapshot_current(intent.snapshot_id)
        ):
            raise AppError(INTENT_MESSAGE)
        self._intent = None  # Every attempt consumes its token, including a busy/failing attempt.
        if self.operation_count:
            raise AppError("Container inspection is busy; retry after the current read finishes.")
        return await self._own(self._disclose(snapshot, intent, self._generation), "disclosure")

    async def _disclose(
        self, snapshot: InspectionSnapshot, intent: DisclosureIntent, generation: int
    ) -> ResolvedValue:
        try:
            async with asyncio.timeout(MAX_OPERATION_SECONDS):
                self._check(generation, intent.generation)
                reads = _Reads(
                    ResourceReader(self.client, tables=False, budget=ReadBudget(MAX_READS))
                )
                pod = await self._pod(
                    reads,
                    generation,
                    intent.generation,
                    snapshot_id=snapshot.id,
                )
                binding = await parse_owned(partial(object_binding, pod, kind="Pod"))
                self._check(generation, intent.generation)
                if binding != snapshot.pod:
                    self._retire(snapshot.id)
                    raise AppError(STALE_MESSAGE)
                sources = await self._sources(pod, reads, generation, intent.generation)
                final = await self._pod(
                    reads,
                    generation,
                    intent.generation,
                    snapshot_id=snapshot.id,
                )
                final_binding = await parse_owned(partial(object_binding, final, kind="Pod"))
                self._check(generation, intent.generation)
                if final_binding != snapshot.pod or reads.limited:
                    self._retire(snapshot.id)
                    raise AppError(STALE_MESSAGE)
                result = await parse_owned(
                    partial(resolve_selected, snapshot, intent.entry, pod, sources)
                )
                self._check(generation, intent.generation)
                if ReasonCode.STALE_BINDING in result.reasons:
                    self._retire(snapshot.id)
                    raise AppError(STALE_MESSAGE)
                return result
        except TimeoutError:
            raise AppError("Container disclosure timed out; reload required.") from None
        except (ConnectionProblem, ReadBudgetExceeded):
            raise AppError("Container disclosure read failed; reload required.") from None

    def cancel_disclosure(self) -> None:
        self._intent_generation += 1
        self._intent = None
        if self._operation_kind == "disclosure" and self._operation is not None:
            self._operation.cancel()

    def observe_pod(self, record: ResourceRecord) -> None:
        # Only immutable record identity/version checks belong on the event loop.
        if (
            record.name != self.target.name
            or record.namespace != self.target.namespace
            or record.uid != self.target.uid
            or (
                self._snapshot is not None
                and record.resource_version != self._snapshot.pod.resource_version
            )
        ):
            self.invalidate()

    def invalidate(self) -> None:
        self._generation += 1
        self._snapshot = None
        self.cancel_disclosure()
        if self._operation is not None:
            self._operation.cancel()

    async def close(self) -> None:
        self._closed = True
        self.invalidate()
        task = self._operation
        if task is not None:
            await _drain(task)
            if self._operation is task:
                self._operation, self._operation_kind = None, None
