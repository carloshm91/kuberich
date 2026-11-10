"""Owned diagnostic Pod lifecycle, exact reviews and UID-only cleanup authority."""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell import (
    REQUEST_SECONDS,
    create_pod,
    delete_pod,
    pod_path,
    session_fingerprint,
)
from kuberich.adapters.node_shell_files import JournalLease, NodeShellJournal
from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.node_shell import (
    CONTAINER,
    EXEC_ARGV,
    NodeShellIntent,
    OwnedPod,
    admitted_profile,
    new_intent,
    validate_node,
    validate_node_descriptor,
)
from kuberich.domain.node_shell_journal import JournalRecord, JournalState
from kuberich.domain.processes import ProcessCommand
from kuberich.domain.resources import ApiResource, api_segment, resource_object, resource_text
from kuberich.domain.targets import ResourceAddress, ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned
from kuberich.services.shell import ShellRequest, ShellService, ShellSession

CLEANUP_SECONDS = 15
POLL_SECONDS = 0.5


class NodeShellState(StrEnum):
    REVIEW = "review"
    CREATING = "creating"
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    CLEANING = "cleaning"
    CLOSED = "closed"
    PENDING = "cleanup_pending"


@dataclass(frozen=True, slots=True)
class NodeShellObservation:
    state: NodeShellState
    code: str
    node_name: str
    pod_name: str | None
    pod_uid: str | None
    operation_id: str | None


async def _get(client: KubernetesSession, path: str) -> dict[str, object]:
    async with asyncio.timeout(REQUEST_SECONDS):
        return await client.get_json(path, max_bytes=2 * 1024 * 1024)


def _namespace_uid(value: object, name: str) -> str:
    namespace = resource_object(value)
    metadata = resource_object(namespace.get("metadata"))
    if (
        namespace.get("apiVersion") != "v1"
        or namespace.get("kind") != "Namespace"
        or metadata.get("name") != name
        or metadata.get("deletionTimestamp") is not None
    ):
        raise AppError("Node shell requires the reviewed, existing live namespace.")
    return resource_text(metadata.get("uid"))


def _observed_pod_uid(value: object, owned: OwnedPod) -> str:
    pod = resource_object(value)
    metadata = resource_object(pod.get("metadata"))
    if (
        pod.get("apiVersion") != "v1"
        or pod.get("kind") != "Pod"
        or metadata.get("name") != owned.name
        or metadata.get("namespace") != owned.namespace
    ):
        raise AppError("Diagnostic cleanup observation returned an unverified Pod address.")
    return resource_text(metadata.get("uid"))


class NodeShellService:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        node: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        settings: NodeShellSettings,
        config_generation: int,
        current_config: Callable[[], int],
        journal: NodeShellJournal,
        environment: Mapping[str, str],
        directory: Path,
        retired: Callable[["NodeShellService"], None] | None = None,
    ) -> None:
        validate_node_descriptor(resource)
        self.client, self.node, self.policy, self.current = client, node, policy, current
        self.settings, self.config_generation = settings, config_generation
        self.current_config, self.journal = current_config, journal
        self.environment, self.directory = dict(environment), directory
        self.intent: NodeShellIntent | None = None
        self.owned: OwnedPod | None = None
        self._confirmation: Confirmation | None = None
        self._approved: NodeShellIntent | None = None
        self._profile: bytes | None = None
        self._lease: JournalLease | None = None
        self._record: JournalRecord | None = None
        self._running: asyncio.Task[MutationResult] | None = None
        self._preparing: asyncio.Task[NodeShellIntent] | None = None
        self._shell_preparing: asyncio.Task[tuple[ShellSession, ShellRequest]] | None = None
        self._terminal: asyncio.Task[object] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._stop_requested = False
        self._delete_attempted = False
        self._admitted = False
        self._shell_reserved = False
        self._durability_failed = False
        self._created_result: MutationResult | None = None
        self._retired = retired
        self._state, self._code = NodeShellState.REVIEW, "prepared"

    @property
    def target(self) -> ResourceAddress:
        if self.intent is None:
            raise AppError("Prepare node shell before registering its write.")
        return self.intent.target

    @property
    def observation(self) -> NodeShellObservation:
        return NodeShellObservation(
            self._state,
            self._code,
            self.node.name,
            self.intent.pod_name if self.intent else None,
            self.owned.uid if self.owned else None,
            self.intent.operation_id if self.intent else None,
        )

    async def durable_record(self) -> JournalRecord | None:
        """Read persisted receipt through this owner's still-held private lease."""
        if self._lease is None or self.intent is None:
            return None
        return next(
            (
                record
                for record in await self._lease.scan()
                if record.operation_id == self.intent.operation_id
            ),
            None,
        )

    def raise_failure(self) -> None:
        """Surface local ownership failures even through compact write history."""
        if self._durability_failed:
            raise AppError(
                "Node-shell ownership persistence failed; remote cleanup was attempted. "
                "Inspect retained recovery state."
            )

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        self.policy.require(Action.EXEC)
        if (
            self._stop_requested
            or not self.settings.enabled
            or not self.current()
            or (
                self._state not in {NodeShellState.READY, NodeShellState.RUNNING}
                and self.current_config() != self.config_generation
            )
            or self.node.session.context != self.client.context.name
            or self.client.configuration is None
        ):
            raise AppError("Node-shell target, configuration or connection changed; review again.")

    async def _identities(self, namespace_uid: str | None = None) -> str:
        self.require_current()
        node = await _get(self.client, "/api/v1/nodes/" + api_segment(self.node.name))
        self.require_current()
        validate_node(self.node, node)
        assert self.settings.namespace is not None
        namespace = await _get(
            self.client, "/api/v1/namespaces/" + api_segment(self.settings.namespace)
        )
        self.require_current()
        uid = _namespace_uid(namespace, self.settings.namespace)
        if namespace_uid is not None and uid != namespace_uid:
            raise AppError("The reviewed namespace UID changed; review again.")
        return uid

    async def prepare(self) -> NodeShellIntent:
        if self._preparing is not None:
            raise AppError("A node-shell review is already being prepared.")
        self._preparing = asyncio.current_task()
        try:
            return await self._prepare()
        finally:
            self._preparing = None

    async def _prepare(self) -> NodeShellIntent:
        self.require_current()
        if self.intent is not None:
            raise AppError("This node-shell owner already has one immutable review.")
        uid = await self._identities()
        fingerprint = await session_fingerprint(self.client)
        self.require_current()
        intent = new_intent(self.node, uid, self.settings, self.config_generation, fingerprint)
        receipt = await create_pod(self.client, intent, self.require_current, dry_run=True)
        self.require_current()
        if receipt.result.state is not MutationState.SUCCEEDED or receipt.profile is None:
            raise AppError(
                "Node-shell server dry-run refused the fixed profile: " + receipt.result.message
            )
        self.intent, self._profile = intent, receipt.profile
        return intent

    def confirm(self, intent: NodeShellIntent) -> Confirmation:
        self.require_current()
        if intent is not self.intent or self._admitted:
            raise AppError("Confirm this exact immutable node-shell review.")
        self._confirmation = Confirmation(intent.identity, uuid4())
        self._approved = intent
        return self._confirmation

    async def _write_record(self, state: JournalState, code: str) -> None:
        assert self._record is not None and self._lease is not None
        record = replace(
            self._record,
            state=state,
            pod_uid=self.owned.uid if self.owned else None,
            updated_at=max(int(time.time()), self._record.updated_at),
            result_code=code,
        )
        try:
            await self._lease.write(record)
        except (AppError, OSError):
            self._durability_failed = True
            self._code = "persistence_failed"
            raise
        self._record = record

    async def _create(self) -> MutationResult:
        assert self.intent is not None
        intent = self.intent
        self._lease = await self.journal.acquire()
        if any(
            record.connection_fingerprint == intent.connection_fingerprint
            for record in await self._lease.scan()
        ):
            raise AppError(
                "Resolve or explicitly forget pending records for this connection first."
            )
        now = int(time.time())
        self._record = JournalRecord(
            intent.operation_id,
            JournalState.PREPARED,
            self.node.session.context,
            intent.connection_fingerprint,
            str(self.settings.namespace),
            intent.namespace_uid,
            self.node.name,
            self.node.uid,
            intent.pod_name,
            None,
            str(self.settings.image).rsplit("sha256:", 1)[1].lower(),
            now,
            now,
        )
        try:
            await self._lease.write(self._record)
        except (AppError, OSError):
            self._durability_failed = True
            self._code = "persistence_failed"
            raise
        await self._identities(intent.namespace_uid)
        self.require_current()
        receipt = await create_pod(self.client, intent, self.require_current)
        self.owned = receipt.owned
        self._created_result = receipt.result
        if self.owned is not None:
            # Persist even when admission/spec validation failed. No exec may
            # begin before durable returned-UID ownership has completed.
            await self._write_record(JournalState.OWNED, "created")
            if receipt.profile != self._profile:
                self._code = "admission_drift"
                raise AppError(
                    "The admitted profile changed after review; shell execution is blocked."
                )
        elif receipt.result.state is MutationState.UNCERTAIN:
            await self._write_record(JournalState.CREATE_UNCERTAIN, "create_uncertain")
            self._code = "create_uncertain"
        else:
            await self._lease.remove(intent.operation_id)
            self._record = None
        return receipt.result

    def execute(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        if (
            confirmation is not self._confirmation
            or self.intent is None
            or self.intent is not self._approved
        ):
            return self._blocked()
        self._confirmation = self._approved = None
        self._admitted = True
        return self._execute()

    async def _blocked(self) -> MutationResult:
        return MutationResult(
            MutationState.BLOCKED, "An unused exact node-shell review is required."
        )

    async def _execute(self) -> MutationResult:
        self._running = asyncio.current_task()
        self._state = NodeShellState.CREATING
        creation: asyncio.Task[MutationResult] | None = None
        try:
            self.require_current()
            creation = asyncio.create_task(self._create())
            result = await asyncio.shield(creation)
            if result.state is not MutationState.SUCCEEDED or self.owned is None:
                await self.close()
                return result
            self._state = NodeShellState.WAITING
            await self._ready()
            self._state, self._code = NodeShellState.READY, "ready"
            return result
        except asyncio.CancelledError:
            self._stop_requested = True
            if creation is not None:
                await finish_owned(asyncio.gather(creation, return_exceptions=True))
            self._code = "interrupted"
            await self.close()
            return self._created_result or MutationResult(
                MutationState.CANCELLED, "Cancelled before diagnostic Pod creation started."
            )
        except (AppError, ConnectionProblem, TimeoutError, OSError) as error:
            if self._code == "prepared":
                self._code = (
                    "denied"
                    if isinstance(error, HttpProblem) and error.status == 403
                    else "not_found"
                    if isinstance(error, HttpProblem) and error.status == 404
                    else "unreachable"
                    if isinstance(error, ConnectionProblem)
                    else "failed"
                )
            await self.close()
            return self._created_result or MutationResult(
                MutationState.BLOCKED,
                "Node-shell preparation/revalidation failed; no create was sent.",
            )
        finally:
            self._running = None

    async def _pod(self, *, require_ready: bool = False) -> dict[str, object]:
        self.require_current()
        assert self.intent is not None and self.owned is not None
        pod = await _get(self.client, pod_path(self.owned))
        self.require_current()
        metadata = resource_object(pod.get("metadata"))
        if metadata.get("uid") != self.owned.uid or metadata.get("deletionTimestamp") is not None:
            raise AppError("The diagnostic Pod UID disappeared or changed; exec is blocked.")
        spec = resource_object(pod.get("spec"))
        scheduled = bool(spec.get("nodeName"))
        if admitted_profile(self.intent, pod, scheduled=scheduled) != self._profile:
            self._code = "admission_drift"
            raise AppError("The diagnostic execution profile changed; exec is blocked.")
        status = resource_object(pod.get("status", {}))
        statuses = status.get("containerStatuses", [])
        if not isinstance(statuses, list):
            raise AppError("Diagnostic Pod readiness response is malformed.")
        for item in statuses:
            state = resource_object(resource_object(item).get("state", {}))
            if (
                len(state) > 1
                or state.keys() - {"running", "waiting", "terminated"}
                or ("running" in state and not isinstance(state["running"], dict))
            ):
                raise AppError("Diagnostic container running evidence is malformed.")
            waiting = resource_object(state.get("waiting", {}))
            if "terminated" in state or waiting.get("reason") in {
                "ErrImagePull",
                "ImagePullBackOff",
                "InvalidImageName",
                "CreateContainerConfigError",
                "CreateContainerError",
                "RunContainerError",
                "CrashLoopBackOff",
            }:
                raise AppError("The diagnostic container failed to start; no policy was relaxed.")
        running = (
            scheduled
            and status.get("phase") == "Running"
            and len(statuses) == 1
            and resource_object(statuses[0]).get("name") == CONTAINER
            and "running" in resource_object(resource_object(statuses[0]).get("state", {}))
        )
        if status.get("phase") in {"Succeeded", "Failed"}:
            raise AppError("The diagnostic Pod completed before exec.")
        if require_ready and not running:
            raise AppError("The diagnostic Pod is no longer running on the reviewed Node.")
        return {"running": running}

    async def _ready(self) -> None:
        try:
            async with asyncio.timeout(self.settings.startup_timeout_seconds):
                while not (await self._pod())["running"]:
                    await asyncio.sleep(POLL_SECONDS)
        except TimeoutError:
            self._code = "startup_timeout"
            raise AppError(
                "Diagnostic Pod startup timed out; scheduling policies were left unchanged."
            ) from None

    async def shell(self) -> tuple[ShellSession, ShellRequest]:
        if self._shell_reserved:
            raise AppError("A diagnostic shell is already opening or running.")
        self._shell_reserved = True
        self._shell_preparing = asyncio.current_task()
        try:
            return await self._shell()
        finally:
            self._shell_preparing = None

    async def _shell(self) -> tuple[ShellSession, ShellRequest]:
        try:
            self.require_current()
            if self._state is not NodeShellState.READY:
                raise AppError("Node shell requires a ready, owned diagnostic Pod.")
            assert self.intent is not None and self.owned is not None
            await self._identities(self.intent.namespace_uid)
            await self._pod(require_ready=True)
            shell = ShellService(
                self.client,
                self.owned.target(self.intent),
                self.policy,
                self.current,
                shell=EXEC_ARGV,
                environment=self.environment,
                directory=self.directory,
            )
            request = shell.capture(CONTAINER)
            return NodeShellTerminal(self, shell), request
        except BaseException:
            await self.close()
            raise

    async def _cleanup(self) -> None:
        try:
            await self._cleanup_remote()
        finally:
            try:
                if self._lease is not None:
                    try:
                        await self._lease.close()
                    except (AppError, OSError):
                        self._durability_failed = True
                        self._code = "persistence_failed"
                        raise
                    else:
                        self._lease = None
            finally:
                if self._retired is not None:
                    self._retired(self)
        self.raise_failure()

    async def _cleanup_remote(self) -> None:
        self._state = NodeShellState.CLEANING
        if self.owned is not None and not self._delete_attempted:
            self._delete_attempted = True
            assert self._lease is not None and self._record is not None

            # This capability belongs only to the original reviewed create and
            # its returned UID. Policy tightening stops exec but cannot orphan it.
            def authorize_cleanup() -> None:
                if self.client.configuration is None:
                    raise AppError("Owned cleanup connection is closed.")

            try:
                await self._write_record(JournalState.CLEANUP_PENDING, "cleanup_pending")
            except (AppError, OSError):
                self._code = "persistence_failed"
            try:
                result = await delete_pod(self.client, self.owned, authorize_cleanup)
                if result.state is MutationState.DENIED:
                    self._code = "delete_denied"
                elif result.state not in {MutationState.ACCEPTED, MutationState.NOT_FOUND}:
                    self._code = "delete_uncertain"
                async with asyncio.timeout(CLEANUP_SECONDS):
                    while True:
                        try:
                            pod = await _get(self.client, pod_path(self.owned))
                            absent = _observed_pod_uid(pod, self.owned) != self.owned.uid
                        except HttpProblem as error:
                            if error.status != 404:
                                raise
                            absent = True
                        if absent:
                            try:
                                await self._lease.remove(self._record.operation_id)
                            except (AppError, OSError):
                                self._durability_failed = True
                                self._code = "persistence_failed"
                                raise
                            self._record = None
                            break
                        if result.state not in {
                            MutationState.ACCEPTED,
                            MutationState.CONFLICT,
                            MutationState.UNCERTAIN,
                            MutationState.NOT_FOUND,
                        }:
                            break
                        await asyncio.sleep(POLL_SECONDS)
            except (AppError, ConnectionProblem, TimeoutError, OSError):
                if self._code not in {"delete_denied", "persistence_failed"}:
                    self._code = "cleanup_pending"
        elif (
            self._record is not None
            and self._record.state is JournalState.PREPARED
            and (
                self._created_result is None
                or self._created_result.state is not MutationState.UNCERTAIN
            )
        ):
            # A known pre-request refusal is removable; a crash-prepared record
            # encountered during a later startup remains unresolved instead.
            assert self._lease is not None
            try:
                await self._lease.remove(self._record.operation_id)
            except (AppError, OSError):
                self._durability_failed = True
                self._code = "persistence_failed"
                raise
            self._record = None
        if self._record is not None:
            self._state = NodeShellState.PENDING
            if self.owned is not None:
                try:
                    await self._write_record(JournalState.CLEANUP_PENDING, self._code)
                except (AppError, OSError):
                    self._code = "persistence_failed"
        else:
            self._state = NodeShellState.CLOSED

    async def close(self) -> None:
        self._stop_requested = True
        caller = asyncio.current_task()
        for task in (self._terminal, self._running, self._preparing, self._shell_preparing):
            if task is not None and task is not caller and not task.done():
                task.cancel()
                await finish_owned(asyncio.gather(task, return_exceptions=True))
        if self._closing is None:
            self._closing = asyncio.create_task(self._cleanup())
        await finish_owned(self._closing)


class NodeShellTerminal:
    def __init__(self, owner: NodeShellService, shell: ShellService) -> None:
        self.owner, self.shell = owner, shell
        self._started = False

    @property
    def client(self) -> KubernetesSession:
        return self.owner.client

    def require_current(self) -> None:
        self.owner.require_current()
        self.shell.require_current()

    @asynccontextmanager
    async def stage(self, request: ShellRequest) -> AsyncIterator[ProcessCommand]:
        if self._started or self.owner._terminal is not None:
            raise AppError("This diagnostic terminal has already been admitted.")
        self._started = True
        self.owner._terminal = asyncio.current_task()
        try:
            self.require_current()
            assert self.owner.intent is not None
            await self.owner._identities(self.owner.intent.namespace_uid)
            await self.owner._pod(require_ready=True)
            async with self.shell.stage(request) as command:
                self.require_current()
                self.owner._state, self.owner._code = NodeShellState.RUNNING, "running"
                async with asyncio.timeout(self.owner.settings.session_timeout_seconds):
                    yield command
                self.owner._code = "completed"
        except TimeoutError:
            self.owner._code = "session_timeout"
            raise AppError("The reviewed node-shell session deadline expired.") from None
        except asyncio.CancelledError:
            self.owner._code = "interrupted"
            raise
        finally:
            self.owner._terminal = None
            await self.owner.close()


class NodeShellManager:
    """One retained live owner, with bounded metadata after owner drainage."""

    def __init__(self, journal: NodeShellJournal | None = None) -> None:
        self.journal = journal or NodeShellJournal()
        self._active: NodeShellService | None = None
        self._records: deque[NodeShellObservation] = deque(maxlen=32)
        self._closed = False

    @property
    def active_count(self) -> int:
        return int(self._active is not None)

    @property
    def records(self) -> tuple[NodeShellObservation, ...]:
        return (*self._records, *((self._active.observation,) if self._active else ()))

    def _retire(self, service: NodeShellService) -> None:
        if service is self._active:
            self._records.append(service.observation)
            self._active = None

    def create(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        node: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        settings: NodeShellSettings,
        config_generation: int,
        current_config: Callable[[], int],
        environment: Mapping[str, str],
        directory: Path,
    ) -> NodeShellService:
        if self._closed or self._active is not None:
            raise AppError("A node-shell owner is already active or the manager is closing.")
        service = NodeShellService(
            client,
            resource,
            node,
            policy,
            current,
            settings=settings,
            config_generation=config_generation,
            current_config=current_config,
            environment=environment,
            directory=directory,
            journal=self.journal,
            retired=self._retire,
        )
        service.require_current()
        self._active = service
        return service

    async def scan(self) -> tuple[JournalRecord, ...]:
        if self._active is not None and self._active._lease is not None:
            return await self._active._lease.scan()
        return await self.journal.scan()

    async def close_for_client(self, client: KubernetesSession) -> None:
        if self._active is not None and self._active.client is client:
            await self._active.close()

    async def close(self) -> None:
        self._closed = True
        if self._active is not None:
            await self._active.close()
