"""Explicit recovery on a selected connection; unknown creates are never adopted."""

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID, uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell import (
    REQUEST_SECONDS,
    delete_pod,
    session_fingerprint,
)
from kuberich.adapters.node_shell_files import JournalLease, NodeShellJournal
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.node_shell import OwnedPod
from kuberich.domain.node_shell_journal import JournalRecord, JournalState
from kuberich.domain.resources import api_segment, resource_object, resource_text
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned

RecoveryAction = Literal["cleanup", "forget"]
RECOVERY_SECONDS = 15


class RecoveryJournalError(RuntimeError):
    """Local durability failed; drainage must precede the fatal reporting boundary."""


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    record: JournalRecord
    pod_present: bool | None
    code: str


@dataclass(frozen=True, slots=True)
class RecoveryReview:
    record: JournalRecord
    action: RecoveryAction
    identity: UUID


class NodeShellRecovery:
    """Retain one exact local record and lease through review and finite work.

    Construction and local forgetting do not connect, resolve contexts or run
    authentication helpers. The caller supplies an already connected client for
    explicit inspection or reviewed cleanup and drains this owner before closing it.
    """

    def __init__(
        self,
        journal: NodeShellJournal,
        client: KubernetesSession | None,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.journal, self.client, self.policy, self.current = journal, client, policy, current
        self._lease: JournalLease | None = None
        self._review: RecoveryReview | None = None
        self._proof: Confirmation | None = None
        self._running: asyncio.Task[MutationResult] | None = None
        self._preparing: asyncio.Task[Any] | None = None
        self._closed = False

    async def _release(self) -> None:
        self._preparing = None
        lease, self._lease = self._lease, None
        if lease is not None:
            await finish_owned(asyncio.create_task(lease.close()))

    async def _durable(self, operation: Coroutine[Any, Any, None]) -> None:
        try:
            await operation
        except (AppError, OSError):
            raise RecoveryJournalError(
                "Node-shell recovery journal durability failed; inspect local and remote state."
            ) from None

    async def _capture(self, record: JournalRecord) -> None:
        if self._closed or self._lease is not None or self._preparing is not None:
            raise AppError("This recovery owner is closed or already retains a review.")
        self._preparing = asyncio.current_task()
        try:
            self._lease = await self.journal.acquire()
            if self._closed:
                raise AppError("This recovery owner closed during local preparation.")
            if record not in await self._lease.scan():
                raise AppError("The local recovery record changed; reload the recovery list.")
        except BaseException:
            await self._release()
            raise

    def _require_connection(
        self, record: JournalRecord, *, mutate: bool = False
    ) -> KubernetesSession:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        client = self.client
        if (
            self._closed
            or not self.current()
            or client is None
            or client.configuration is None
            or client.context.name != record.context
        ):
            raise AppError("Select and explicitly connect the recorded context before recovery.")
        return client

    async def _scope(self, record: JournalRecord, *, mutate: bool = False) -> KubernetesSession:
        client = self._require_connection(record, mutate=mutate)
        if await session_fingerprint(client) != record.connection_fingerprint:
            raise AppError("The selected connection does not match this recovery record.")
        self._require_connection(record, mutate=mutate)
        async with asyncio.timeout(REQUEST_SECONDS):
            namespace = await client.get_json("/api/v1/namespaces/" + api_segment(record.namespace))
        self._require_connection(record, mutate=mutate)
        metadata = resource_object(namespace.get("metadata"))
        if (
            namespace.get("apiVersion") != "v1"
            or namespace.get("kind") != "Namespace"
            or metadata.get("name") != record.namespace
            or metadata.get("uid") != record.namespace_uid
            or metadata.get("deletionTimestamp") is not None
        ):
            raise AppError("The recorded namespace UID no longer matches; cleanup is blocked.")
        return client

    async def _pod_uid(self, client: KubernetesSession, record: JournalRecord) -> str | None:
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                value = await client.get_json(
                    "/api/v1/namespaces/"
                    + api_segment(record.namespace)
                    + "/pods/"
                    + api_segment(record.pod_name)
                )
        except HttpProblem as error:
            if error.status == 404:
                return None
            raise
        metadata = resource_object(value.get("metadata"))
        if (
            value.get("apiVersion") != "v1"
            or value.get("kind") != "Pod"
            or metadata.get("name") != record.pod_name
            or metadata.get("namespace") != record.namespace
        ):
            raise AppError("The diagnostic Pod observation could not be verified.")
        return resource_text(metadata.get("uid"))

    async def inspect(self, record: JournalRecord) -> RecoveryObservation:
        await self._capture(record)
        try:
            client = await self._scope(record)
            uid = await self._pod_uid(client, record)
            self._require_connection(record)
            code = (
                "absent"
                if uid is None
                else "present_unowned"
                if record.pod_uid is None
                else "present_owned"
                if uid == record.pod_uid
                else "replacement"
            )
            return RecoveryObservation(record, uid is not None, code)
        finally:
            await self._release()

    async def prepare_cleanup(self, record: JournalRecord) -> RecoveryReview:
        if record.pod_uid is None:
            raise AppError("No returned Pod UID was recorded; inspect or forget locally instead.")
        self.policy.require(Action.MUTATE)
        await self._capture(record)
        try:
            client = await self._scope(record, mutate=True)
            await self._pod_uid(client, record)
            self._require_connection(record, mutate=True)
            self._review = RecoveryReview(record, "cleanup", uuid4())
            self._preparing = None
            return self._review
        except BaseException:
            await self._release()
            raise

    async def prepare_forget(self, record: JournalRecord) -> RecoveryReview:
        self.policy.require(Action.READ)
        await self._capture(record)
        self._review = RecoveryReview(record, "forget", uuid4())
        self._preparing = None
        return self._review

    def confirm(self, review: RecoveryReview) -> Confirmation:
        if self._closed or review is not self._review:
            raise AppError("Confirm the exact current recovery review.")
        if review.action == "cleanup":
            self._require_connection(review.record, mutate=True)
        self._proof = Confirmation(review.identity, uuid4())
        return self._proof

    def _consume(self, proof: Confirmation, action: RecoveryAction) -> RecoveryReview | None:
        review = self._review
        if (
            self._closed
            or proof is not self._proof
            or review is None
            or review.action != action
            or proof.intent != review.identity
        ):
            return None
        self._proof = self._review = None
        return review

    async def _blocked(self) -> MutationResult:
        return MutationResult(MutationState.BLOCKED, "An unused exact recovery review is required.")

    def cleanup(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        review = self._consume(confirmation, "cleanup")
        return self._cleanup(review.record) if review is not None else self._blocked()

    def forget(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        review = self._consume(confirmation, "forget")
        return self._forget(review.record) if review is not None else self._blocked()

    async def _forget(self, record: JournalRecord) -> MutationResult:
        self._running = asyncio.current_task()
        try:
            if self._closed or self._lease is None:
                return await self._blocked()
            self.policy.require(Action.READ)
            await self._durable(self._lease.remove(record.operation_id))
            return MutationResult(
                MutationState.SUCCEEDED,
                "Local recovery record forgotten; no remote Pod was changed or cleanup claimed.",
            )
        finally:
            self._running = None
            await self._release()

    async def _cleanup(self, record: JournalRecord) -> MutationResult:
        self._running = asyncio.current_task()
        result: MutationResult | None = None
        try:
            if self._lease is None or record.pod_uid is None:
                return await self._blocked()
            client = await self._scope(record, mutate=True)
            uid = await self._pod_uid(client, record)
            self._require_connection(record, mutate=True)
            if uid != record.pod_uid:
                await self._durable(self._lease.remove(record.operation_id))
                return MutationResult(
                    MutationState.SUCCEEDED,
                    "The original Pod is absent; its record was removed and any replacement preserved.",
                )
            pending = replace(
                record,
                state=JournalState.CLEANUP_PENDING,
                updated_at=max(int(time.time()), record.updated_at),
                result_code="cleanup_pending",
            )
            await self._durable(self._lease.write(pending))

            def authorize() -> None:
                self._require_connection(record, mutate=True)

            result = await delete_pod(
                client,
                OwnedPod(record.pod_name, record.namespace, record.pod_uid),
                authorize,
            )
            async with asyncio.timeout(RECOVERY_SECONDS):
                while True:
                    uid = await self._pod_uid(client, record)
                    self._require_connection(record)
                    if uid != record.pod_uid:
                        await self._durable(self._lease.remove(record.operation_id))
                        return MutationResult(
                            MutationState.SUCCEEDED,
                            "The original diagnostic Pod is absent; UID cleanup and journal removal completed.",
                        )
                    if result.state not in {
                        MutationState.ACCEPTED,
                        MutationState.UNCERTAIN,
                        MutationState.CONFLICT,
                        MutationState.NOT_FOUND,
                    }:
                        break
                    await asyncio.sleep(0.5)
            return MutationResult(
                result.state, "Cleanup is still pending; the known-UID record was retained."
            )
        except (AppError, ConnectionProblem, TimeoutError, OSError):
            return MutationResult(
                result.state if result is not None else MutationState.BLOCKED,
                "Cleanup could not be fully confirmed; inspect local and remote state before retry.",
            )
        finally:
            self._running = None
            await self._release()

    async def close(self) -> None:
        self._closed = True
        for task in (self._running, self._preparing):
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
                await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._proof = self._review = None
        await self._release()
