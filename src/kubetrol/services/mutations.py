"""Captured confirmation, common write policy, revalidation and owned cancellation."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4
from weakref import WeakSet

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.adapters.mutations import conditional_patch
from kubetrol.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kubetrol.domain.mutations import (
    MutationIntent,
    MutationResult,
    MutationState,
    annotation_intent,
    mutation_path,
)
from kubetrol.domain.resources import ApiResource, ResourceRecord, resource_record
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy, Action
from kubetrol.services.processes import _finish_owned


@dataclass(frozen=True, repr=False)
class Confirmation:
    intent: UUID
    token: UUID


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
    target: ResourceTarget
    effects: tuple[str, ...]
    result: MutationResult | None


class MutationManager:
    """Bounded public history; closing clients reject future starts and drain writes."""

    def __init__(self) -> None:
        self._records: OrderedDict[UUID, MutationRecord] = OrderedDict()
        self._live: dict[UUID, tuple[KubernetesSession, asyncio.Task[MutationResult]]] = {}
        self._retired: WeakSet[KubernetesSession] = WeakSet()
        self._closed = False

    @property
    def records(self) -> tuple[MutationRecord, ...]:
        return tuple(self._records.values())

    def start(self, source: MutationService, confirmation: Confirmation) -> UUID:
        source.require_current()
        if self._closed or source.client in self._retired:
            raise AppError("Mutation connection is closing; no new write can start.")
        if len(self._live) >= 8:
            raise AppError("Eight writes are already active. Wait for their results.")
        intent = source.intent
        if intent is None:
            raise AppError("Prepare and confirm a mutation first.")
        identity = uuid4()
        while len(self._records) >= 32:
            oldest = next(key for key in self._records if key not in self._live)
            del self._records[oldest]
        self._records[identity] = MutationRecord(identity, source.target, intent.effects, None)
        task = asyncio.create_task(source.execute(confirmation))
        self._live[identity] = source.client, task
        task.add_done_callback(lambda completed: self._completed(identity, completed))
        return identity

    def _completed(self, identity: UUID, task: asyncio.Task[MutationResult]) -> None:
        old = self._records[identity]
        if task.cancelled():
            result = MutationResult(
                MutationState.CANCELLED, "Cancelled before operation entry; no write started."
            )
        elif task.exception() is not None:
            result = MutationResult(
                MutationState.UNCERTAIN,
                "Unexpected write failure. Inspect the object before another change.",
            )
        else:
            result = task.result()
        self._records[identity] = MutationRecord(identity, old.target, old.effects, result)
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
        result = self._records[identity].result
        assert result is not None
        return result

    async def _drain(self, tasks: tuple[asyncio.Task[MutationResult], ...]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()
        await _finish_owned(asyncio.gather(*tasks, return_exceptions=True))

    async def stop_for_client(self, client: KubernetesSession) -> None:
        self._retired.add(client)
        await self._drain(tuple(task for owner, task in self._live.values() if owner is client))

    async def close(self) -> None:
        self._closed = True
        await self._drain(tuple(task for _, task in self._live.values()))
