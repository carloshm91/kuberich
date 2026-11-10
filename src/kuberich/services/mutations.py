"""Captured confirmation, common write policy, revalidation and owned cancellation."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4
from weakref import WeakSet

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.mutations import conditional_patch
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.curated import curated_read_only
from kuberich.domain.mutations import (
    MutationIntent,
    MutationResult,
    MutationState,
    annotation_intent,
    mutation_path,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_record
from kuberich.domain.targets import MutationTarget, ResourceAddress, ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.processes import _finish_owned


@dataclass(frozen=True, repr=False)
class Confirmation:
    intent: UUID
    token: UUID


class WriteIntent(Protocol):
    @property
    def effects(self) -> tuple[str, ...]: ...


@runtime_checkable
class BatchWriteIntent(WriteIntent, Protocol):
    """Optional immutable identity metadata; no request/source owners are retained."""

    @property
    def targets(self) -> tuple[MutationTarget, ...]: ...


class MutationSource(Protocol):
    client: KubernetesSession

    @property
    def target(self) -> MutationTarget: ...

    @property
    def intent(self) -> WriteIntent | None: ...

    def require_current(self) -> None: ...

    async def execute(self, confirmation: Confirmation) -> MutationResult: ...


class MutationService:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current = policy, current
        self.intent: MutationIntent | None = None
        self._confirmation: Confirmation | None = None
        self._approved_intent: MutationIntent | None = None

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        if curated_read_only(self.resource):
            raise AppError("This resource supports reading, inspection and navigation only.")
        mutation_path(self.resource, self.target)
        if not self.current() or self.client.context.name != self.target.session.context:
            raise AppError("Mutation target/connection changed. Select the resource again.")

    async def _read(self) -> ResourceRecord:
        self.require_current()
        data = await self.client.get_json(mutation_path(self.resource, self.target))
        self.require_current()
        record = resource_record(self.resource, data, self.target.namespace)
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("Mutation read returned a different resource.")
        return record

    async def prepare_annotation(self, key: str, value: str) -> MutationIntent:
        self.require_current()
        self._confirmation = None
        self._approved_intent = None
        self.intent = None
        record = await self._read()
        self.intent = annotation_intent(self.resource, self.target, record, key, value)
        return self.intent

    def confirm(self, intent: MutationIntent) -> Confirmation:
        self.require_current()
        if (
            not isinstance(intent, MutationIntent)
            or intent is not self.intent
            or intent.target != self.target
            or intent.resource != self.resource
        ):
            raise AppError("Confirmation must match the exact prepared mutation.")
        self._confirmation = Confirmation(intent.identity, uuid4())
        self._approved_intent = intent
        return self._confirmation

    async def execute(self, confirmation: Confirmation) -> MutationResult:
        intent = self.intent
        if (
            not isinstance(confirmation, Confirmation)
            or intent is None
            or confirmation is not self._confirmation
            or intent is not self._approved_intent
            or intent.target != self.target
            or intent.resource != self.resource
        ):
            return MutationResult(
                MutationState.BLOCKED, "An unused confirmation for this exact change is required."
            )
        # Consume before the first await. Concurrent submits cannot reuse it.
        self._confirmation = None
        self._approved_intent = None
        try:
            self.require_current()
            record = await self._read()
            if record.resource_version != intent.resource_version:
                return MutationResult(
                    MutationState.CONFLICT,
                    "Object version changed after confirmation. Read and confirm again.",
                )
            self.require_current()
            return await conditional_patch(self.client, intent, self.require_current)
        except asyncio.CancelledError:
            return MutationResult(
                MutationState.CANCELLED, "Cancelled during revalidation; no write started."
            )
        except HttpProblem as error:
            if error.status == 403:
                return MutationResult(
                    MutationState.DENIED,
                    "Permission denied while revalidating the target; no write started.",
                )
            if error.status == 404:
                return MutationResult(
                    MutationState.NOT_FOUND, "Target disappeared before write; no write started."
                )
            return MutationResult(
                MutationState.REJECTED, "API revalidation failed; no write started."
            )
        except ConnectionProblem as error:
            state = (
                MutationState.TIMEOUT
                if error.state is ConnectionState.TIMEOUT
                else MutationState.UNREACHABLE
            )
            return MutationResult(
                state, "Connection revalidation failed before write; no request was started."
            )
        except AppError:
            return MutationResult(
                MutationState.BLOCKED if self.policy.read_only else MutationState.STALE,
                "Write policy or captured target changed; no write started.",
            )


@dataclass(frozen=True)
class MutationRecord:
    identity: UUID
    target: MutationTarget
    effects: tuple[str, ...]
    result: MutationResult | None
    targets: tuple[MutationTarget, ...] = ()


class MutationManager:
    """Bounded public history; closing clients reject future starts and drain writes."""

    def __init__(self) -> None:
        self._records: OrderedDict[UUID, MutationRecord] = OrderedDict()
        self._live: dict[UUID, tuple[KubernetesSession, asyncio.Task[MutationResult]]] = {}
        self._retired: WeakSet[KubernetesSession] = WeakSet()
        self._closed = False

    @property
    def active_count(self) -> int:
        """Registered writes, including completed jobs awaiting result retirement."""
        return len(self._live)

    @property
    def records(self) -> tuple[MutationRecord, ...]:
        return tuple(self._records.values())

    def start(self, source: MutationSource, confirmation: Confirmation) -> UUID:
        source.require_current()
        if self._closed or source.client in self._retired:
            raise AppError("Mutation connection is closing; no new write can start.")
        if len(self._live) >= 8:
            raise AppError("Eight writes are already active. Wait for their results.")
        intent = source.intent
        if intent is None:
            raise AppError("Prepare and confirm a mutation first.")
        targets = tuple(intent.targets) if isinstance(intent, BatchWriteIntent) else ()
        if targets and (
            len(targets) > 100
            or any(
                not isinstance(target, (ResourceTarget, ResourceAddress))
                or target.session != source.target.session
                for target in targets
            )
        ):
            raise AppError("Batch history requires bounded identities from the captured session.")
        identity = uuid4()
        while len(self._records) >= 32:
            oldest = next(key for key in self._records if key not in self._live)
            del self._records[oldest]
        self._records[identity] = MutationRecord(
            identity, source.target, intent.effects, None, targets
        )
        task = asyncio.create_task(source.execute(confirmation))
        self._live[identity] = source.client, task
        task.add_done_callback(lambda completed: self._completed(identity, completed))
        return identity

    def _completed(self, identity: UUID, task: asyncio.Task[MutationResult]) -> None:
        if identity not in self._live:
            return
        old = self._records[identity]
        if task.cancelled():
            result = MutationResult(
                MutationState.CANCELLED,
                "Cancelled before operation entry; no write started.",
                tuple(
                    (
                        target,
                        MutationResult(
                            MutationState.CANCELLED,
                            "Unsent: cancelled before operation entry; no write request started.",
                        ),
                    )
                    for target in old.targets
                ),
            )
        elif task.exception() is not None:
            result = MutationResult(
                MutationState.UNCERTAIN,
                "Unexpected write failure. Inspect the object before another change.",
                tuple(
                    (
                        target,
                        MutationResult(
                            MutationState.UNCERTAIN,
                            "Outcome unknown after unexpected failure; inspect before a new review.",
                        ),
                    )
                    for target in old.targets
                ),
            )
        else:
            result = task.result()
            if old.targets and not result.items and result.state is MutationState.BLOCKED:
                result = MutationResult(
                    result.state,
                    result.message,
                    tuple(
                        (
                            target,
                            MutationResult(
                                MutationState.BLOCKED,
                                "Unsent: exact confirmation was not admitted.",
                            ),
                        )
                        for target in old.targets
                    ),
                )
        self._records[identity] = MutationRecord(
            identity, old.target, old.effects, result, old.targets
        )
        self._live.pop(identity, None)

    async def wait(self, identity: UUID) -> MutationResult:
        if identity not in self._records:
            raise AppError("That mutation result is no longer retained.")
        active = self._live.get(identity)
        if active is not None:
            try:
                await asyncio.shield(active[1])
            except asyncio.CancelledError:
                waiter = asyncio.current_task()
                if waiter is not None and waiter.cancelling():
                    raise
            except Exception:
                # Completion retains a safe uncertain result, never the raw error.
                pass
            if active[1].done():
                self._completed(identity, active[1])
        result = self._records[identity].result
        assert result is not None
        return result

    async def _drain(self, tasks: tuple[asyncio.Task[MutationResult], ...]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        await _finish_owned(asyncio.gather(*tasks, return_exceptions=True))

    async def cancel(self, identity: UUID) -> MutationResult:
        """Stop and drain one registered job without retiring its client."""
        if identity not in self._records:
            raise AppError("That mutation result is no longer retained.")
        active = self._live.get(identity)
        if active is not None:
            await self._drain((active[1],))
        return await self.wait(identity)

    async def stop_for_client(self, client: KubernetesSession) -> None:
        self._retired.add(client)
        await self._drain(tuple(task for owner, task in self._live.values() if owner is client))

    async def close(self) -> None:
        self._closed = True
        await self._drain(tuple(task for _, task in self._live.values()))
