"""Own reviewed irreversible debug appends, serial observations and local attach."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakSet

from kuberich.adapters.ephemeral_debug import AppendReceipt, append_container
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.ephemeral_debug import (
    AppendIdentity,
    ContainerInstance,
    DebugObservation,
    EphemeralDebugIntent,
    EphemeralDebugOptions,
    debug_session_row,
    discover_ephemeral,
    inspect_debug_instance,
    prepare_intent,
    session_rows,
    validate_current,
    verify_debug_declaration,
    verify_debug_instance,
)
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.processes import ProcessCommand
from kuberich.domain.resources import ApiResource, api_segment
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.attach import AttachService
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned
from kuberich.services.shell import ShellRequest, ShellSession

POLL_SECONDS = 0.5
STARTUP_SECONDS = 60.0


@dataclass(frozen=True, slots=True, repr=False)
class EphemeralDebugReview:
    intent: EphemeralDebugIntent
    profile: bytes

    @property
    def identity(self) -> UUID:
        return self.intent.identity

    @property
    def effects(self) -> tuple[str, ...]:
        return self.intent.effects


@dataclass(frozen=True, slots=True)
class DebugOutcome:
    identity: UUID
    name: str
    result: MutationResult
    append: AppendIdentity | None


@dataclass(frozen=True, slots=True)
class EphemeralDebugObservation:
    remote: DebugObservation | None
    outcomes: tuple[DebugOutcome, ...]
    observed_at: float | None
    stale: bool
    code: str
    attaching: str | None


class EphemeralDebugService:
    """A MutationSource and retained owner; cleanup never changes a remote object."""

    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        environment: Mapping[str, str],
        directory: Path,
        retired: Callable[[EphemeralDebugService], None] | None = None,
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current = policy, current
        self.environment, self.directory = dict(environment), directory.absolute()
        self.intent: EphemeralDebugReview | None = None
        self._confirmation: Confirmation | None = None
        self._approved: EphemeralDebugReview | None = None
        self._outcomes: deque[DebugOutcome] = deque(maxlen=32)
        self._receipts: dict[str, tuple[EphemeralDebugReview, AppendIdentity]] = {}
        self._observation = EphemeralDebugObservation(None, (), None, True, "unobserved", None)
        self._listeners: set[Callable[[EphemeralDebugObservation], None]] = set()
        self._reads = asyncio.Lock()
        self._jobs: set[asyncio.Task[Any]] = set()
        self._collector: asyncio.Task[None] | None = None
        self._closing: asyncio.Task[None] | None = None
        self._attachment: EphemeralDebugTerminal | None = None
        self._terminal: asyncio.Task[Any] | None = None
        self._preparing = False
        self._executing = False
        self._closed = False
        self._retired = retired

    @property
    def observation(self) -> EphemeralDebugObservation:
        return self._observation

    @property
    def operation_count(self) -> int:
        return len(self._jobs) + int(self._collector is not None) + int(self._terminal is not None)

    def subscribe(
        self, listener: Callable[[EphemeralDebugObservation], None]
    ) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _publish(self, **changes: Any) -> None:
        self._observation = replace(self._observation, outcomes=tuple(self._outcomes), **changes)
        if not self._closed and self.current():
            for listener in tuple(self._listeners):
                try:
                    listener(self._observation)
                except Exception:
                    self._listeners.discard(listener)

    def require_observable(self) -> None:
        self.policy.require(Action.READ)
        r, t = self.resource, self.target
        if (
            (r.group, r.version, r.name, r.kind, r.namespaced) != ("", "v1", "pods", "Pod", True)
            or "get" not in r.verbs
            or (t.group, t.resource, t.container) != ("", "pods", None)
            or t.namespace is None
            or self._closed
            or not self.current()
            or self.client.context.name != t.session.context
            or self.client.configuration is None
        ):
            raise AppError("Debug inspection requires this captured readable core/v1 Pod.")

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        self.policy.require(Action.ATTACH)
        self.require_observable()

    def _register(self) -> asyncio.Task[Any]:
        task = asyncio.current_task()
        assert task is not None
        self._jobs.add(task)
        return task

    async def _pod(self) -> dict[str, object]:
        self.require_observable()
        async with self._reads:
            self.require_observable()
            assert self.target.namespace is not None
            pod = await self.client.get_json(
                self.resource.path(self.target.namespace) + "/" + api_segment(self.target.name)
            )
            self.require_observable()
            return pod

    async def observe(self) -> EphemeralDebugObservation:
        """One bounded current-client GET; errors retain visibly stale prior rows."""
        task = self._register()
        try:
            pod = await self._pod()
            remote = await parse_owned(lambda: session_rows(self.target, pod))
            self.require_observable()
            self._publish(remote=remote, observed_at=time.time(), stale=False, code="observed")
            await self._monitor(pod)
            return self.observation
        except (AppError, ConnectionProblem, HttpProblem, TimeoutError) as error:
            self._publish(
                stale=True,
                code="denied"
                if isinstance(error, HttpProblem) and error.status == 403
                else "not_found"
                if isinstance(error, HttpProblem) and error.status == 404
                else "unavailable",
            )
            await self._stop_attachment("observation_unavailable")
            raise
        finally:
            self._jobs.discard(task)

    def start(self) -> None:
        """Start one serial collector while the owning screen or terminal is open."""
        self.require_observable()
        if self._collector is None:
            self._collector = asyncio.create_task(self._collect())

    async def _collect(self) -> None:
        try:
            while not self._closed:
                try:
                    await self.observe()
                except (AppError, ConnectionProblem, HttpProblem, TimeoutError):
                    if not self.current() or self.client.configuration is None:
                        return
                await asyncio.sleep(POLL_SECONDS)
        finally:
            self._collector = None

    async def prepare(self, options: EphemeralDebugOptions) -> EphemeralDebugReview:
        self.require_current()
        if self._preparing or self._executing:
            raise AppError("A debug review or append is already active.")
        self._preparing = True
        self.intent = self._confirmation = self._approved = None
        task = self._register()
        try:
            async with self._reads:
                self.require_current()
                discovery = await self.client.get_json("/api/v1")
                self.require_current()
                await parse_owned(lambda: discover_ephemeral(discovery))
            pod = await self._pod()
            draft = await parse_owned(lambda: prepare_intent(self.target, pod, options))
            self.require_current()
            receipt = await append_container(self.client, draft, self.require_current, dry_run=True)
            self.require_current()
            if receipt.result.state is not MutationState.SUCCEEDED or receipt.profile is None:
                raise AppError(receipt.result.message)
            review = EphemeralDebugReview(draft, receipt.profile)
            self.intent = review
            return review
        finally:
            self._preparing = False
            self._jobs.discard(task)

    def confirm(self, review: EphemeralDebugReview) -> Confirmation:
        self.require_current()
        if review is not self.intent or not isinstance(review, EphemeralDebugReview):
            raise AppError("Confirm the exact successful server dry-run review.")
        self._confirmation = Confirmation(review.identity, uuid4())
        self._approved = review
        return self._confirmation

    def execute(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        """Consume the exact one-use review before returning the first coroutine."""
        review = self.intent
        if (
            review is None
            or confirmation is not self._confirmation
            or review is not self._approved
            or not isinstance(confirmation, Confirmation)
        ):
            return self._blocked()
        self._confirmation = self._approved = None
        return self._execute(review)

    async def _blocked(self) -> MutationResult:
        return MutationResult(
            MutationState.BLOCKED, "An unused exact debug confirmation is required."
        )

    def _record(self, review: EphemeralDebugReview, receipt: AppendReceipt) -> None:
        self._outcomes.append(
            DebugOutcome(
                review.identity, review.intent.options.name, receipt.result, receipt.append
            )
        )
        retained = {outcome.name for outcome in self._outcomes}
        self._receipts = {k: value for k, value in self._receipts.items() if k in retained}
        if receipt.append is not None and receipt.profile == review.profile:
            self._receipts[review.intent.options.name] = review, receipt.append
        self._publish(code="appended" if receipt.append is not None else receipt.result.state.value)

    async def _append(self, review: EphemeralDebugReview) -> AppendReceipt:
        receipt = await append_container(
            self.client,
            review.intent,
            self.require_current,
            expected_profile=review.profile,
        )
        self._record(review, receipt)
        return receipt

    def _unsent(self, review: EphemeralDebugReview, result: MutationResult) -> MutationResult:
        self._record(review, AppendReceipt(result, None, None))
        return result

    async def _execute(self, review: EphemeralDebugReview) -> MutationResult:
        task = self._register()
        write: asyncio.Task[AppendReceipt] | None = None
        admitted = False
        try:
            self.require_current()
            if self._executing or review is not self.intent:
                return self._unsent(review, await self._blocked())
            self._executing = True
            admitted = True
            pod = await self._pod()
            await parse_owned(lambda: validate_current(review.intent, pod))
            self.require_current()
            write = asyncio.create_task(self._append(review))
            receipt = await asyncio.shield(write)
            if (
                receipt.result.state is MutationState.SUCCEEDED
                and receipt.profile == review.profile
            ):
                try:
                    await self._ready(review)
                except (AppError, ConnectionProblem, HttpProblem, TimeoutError):
                    return MutationResult(
                        MutationState.PARTIAL,
                        "The addition is permanent; startup or fresh identity verification failed. "
                        "Inspect sessions before attaching; no retry or rollback occurred.",
                    )
            return receipt.result
        except asyncio.CancelledError:
            if write is not None:
                await finish_owned(write)
                return write.result().result
            return self._unsent(
                review,
                MutationResult(MutationState.CANCELLED, "Stopped before append; no write started."),
            )
        except HttpProblem as error:
            return self._unsent(
                review,
                MutationResult(
                    MutationState.DENIED
                    if error.status == 403
                    else MutationState.NOT_FOUND
                    if error.status == 404
                    else MutationState.REJECTED,
                    "Pod revalidation refused; no append was sent.",
                ),
            )
        except ConnectionProblem as error:
            return self._unsent(
                review,
                MutationResult(
                    MutationState.TIMEOUT
                    if error.state is ConnectionState.TIMEOUT
                    else MutationState.UNREACHABLE,
                    "Pod revalidation unavailable; no append sent.",
                ),
            )
        except TimeoutError:
            return self._unsent(
                review,
                MutationResult(
                    MutationState.TIMEOUT, "Pod revalidation timed out; no append sent."
                ),
            )
        except AppError:
            return self._unsent(
                review,
                MutationResult(
                    MutationState.BLOCKED if self.policy.read_only else MutationState.CONFLICT,
                    "Policy or reviewed Pod/target identity changed; prepare a fresh review.",
                ),
            )
        finally:
            if admitted:
                self._executing = False
            self._jobs.discard(task)

    async def _ready(self, review: EphemeralDebugReview) -> None:
        try:
            async with asyncio.timeout(STARTUP_SECONDS):
                await self._wait_ready(review)
        except TimeoutError:
            self._publish(code="startup_timeout")
            raise

    async def _wait_ready(self, review: EphemeralDebugReview) -> None:
        while True:
            self.require_current()
            pod = await self._pod()
            await parse_owned(partial(verify_debug_declaration, review.intent, pod, review.profile))
            remote = await parse_owned(partial(session_rows, self.target, pod))
            self._publish(remote=remote, observed_at=time.time(), stale=False, code="waiting")
            row = await parse_owned(
                partial(debug_session_row, self.target, pod, review.intent.options.name)
            )
            if row.state == "running":
                await parse_owned(
                    partial(verify_debug_instance, review.intent, pod, review.profile)
                )
                self._publish(code="ready")
                return
            if row.state == "terminated" or row.reason in {
                "ErrImagePull",
                "ImagePullBackOff",
                "InvalidImageName",
                "CreateContainerConfigError",
                "CreateContainerError",
                "RunContainerError",
                "CrashLoopBackOff",
            }:
                self._publish(code="start_failed")
                raise AppError("Debug container failed to start; the addition remains permanent.")
            await asyncio.sleep(POLL_SECONDS)

    async def prepare_shell(self, name: str) -> tuple[ShellSession, ShellRequest]:
        self.require_current()
        if self._attachment is not None:
            raise AppError("A debug terminal is already opening or active.")
        terminal = EphemeralDebugTerminal(self, name)
        self._attachment = terminal
        task = self._register()
        try:
            pod = await self._pod()
            terminal.evidence = await parse_owned(
                lambda: inspect_debug_instance(self.target, pod, name)
            )
            if name in self._receipts:
                review, _ = self._receipts[name]
                await parse_owned(lambda: verify_debug_instance(review.intent, pod, review.profile))
                terminal.review = review
            elif any(o.name == name for o in self._outcomes):
                raise AppError(
                    "This addition has no verified admitted receipt; attachment is blocked."
                )
            self.require_current()
            request = terminal.attach.capture(name)
            terminal.request = request
            terminal.require_current()
            self._publish(attaching=name, code="attach_prepared")
            self.start()
            return terminal, request
        except BaseException:
            self._attachment = None
            raise
        finally:
            self._jobs.discard(task)

    async def _monitor(self, pod: object) -> None:
        terminal = self._attachment
        if terminal is None:
            return
        try:
            self.require_current()
            if terminal.evidence is not None:
                await parse_owned(partial(terminal.verify, pod))
        except AppError:
            await self._stop_attachment("attachment_identity_changed")

    async def _stop_attachment(self, code: str) -> None:
        task = self._terminal
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._attachment = None
        self._publish(attaching=None, code=code)

    async def _stop(self) -> None:
        await self._stop_attachment("closed")
        caller = asyncio.current_task()
        jobs = tuple(t for t in (*self._jobs, self._collector) if t is not None and t is not caller)
        for task in jobs:
            task.cancel()
        await finish_owned(asyncio.gather(*jobs, return_exceptions=True))
        self._listeners.clear()
        if self._retired is not None:
            self._retired(self)

    async def stop_owned(self) -> None:
        self._closed = True
        if self._closing is None:
            self._closing = asyncio.create_task(self._stop())
        caller = asyncio.current_task()
        if caller is self._terminal or caller in self._jobs:
            # This task must unwind its own lease before the cleanup child can
            # drain it. Awaiting that child here would create a dependency cycle.
            raise asyncio.CancelledError
        await finish_owned(self._closing)

    async def close(self) -> None:
        await self.stop_owned()


class EphemeralDebugTerminal:
    """A one-use ShellSession lease around AttachService and its private staging."""

    def __init__(self, owner: EphemeralDebugService, name: str) -> None:
        self.owner, self.name = owner, name
        self.attach = AttachService(
            owner.client,
            owner.target,
            owner.policy,
            owner.current,
            environment=owner.environment,
            directory=owner.directory,
        )
        self.evidence: tuple[ContainerInstance, ContainerInstance | None, bytes] | None = None
        self.request: ShellRequest | None = None
        self.review: EphemeralDebugReview | None = None
        self._started = False

    @property
    def client(self) -> KubernetesSession:
        return self.owner.client

    def require_current(self) -> None:
        self.owner.require_current()
        if self.owner._attachment is not self:
            raise AppError("This local debug terminal lease is no longer active.")
        self.attach.require_current()

    def verify(self, pod: object) -> None:
        if (
            self.evidence is None
            or inspect_debug_instance(self.owner.target, pod, self.name) != self.evidence
        ):
            raise AppError(
                "Debug declaration, target or running instance changed; attachment stopped."
            )
        if self.review is not None:
            verify_debug_instance(self.review.intent, pod, self.review.profile)

    @asynccontextmanager
    async def stage(self, request: ShellRequest) -> AsyncIterator[ProcessCommand]:
        self.require_current()
        if request is not self.request:
            raise AppError("This terminal requires its exact prepared debug attach request.")
        if self._started or self.owner._terminal is not None:
            raise AppError("This debug terminal has already been admitted.")
        self._started = True
        self.owner._terminal = asyncio.current_task()
        try:
            await parse_owned(partial(self.verify, await self.owner._pod()))
            async with self.attach.stage(request) as command:
                self.require_current()
                self.owner._publish(code="attached")
                yield command
        finally:
            self.owner._terminal = None
            if self.owner._attachment is self:
                self.owner._attachment = None
            self.owner._publish(attaching=None, code="detached")


class EphemeralDebugManager:
    """Retain one screen/terminal owner until all local work has drained."""

    def __init__(self) -> None:
        self._active: EphemeralDebugService | None = None
        self._records: deque[DebugOutcome] = deque(maxlen=32)
        self._retired: WeakSet[KubernetesSession] = WeakSet()
        self._closed = False

    @property
    def active_count(self) -> int:
        return int(self._active is not None)

    @property
    def records(self) -> tuple[DebugOutcome, ...]:
        return (*self._records, *(self._active.observation.outcomes if self._active else ()))[-32:]

    def _retire(self, service: EphemeralDebugService) -> None:
        if self._active is service:
            self._records.extend(service.observation.outcomes)
            self._active = None

    def create(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        environment: Mapping[str, str],
        directory: Path,
    ) -> EphemeralDebugService:
        if self._closed or self._active is not None or client in self._retired:
            raise AppError("A debug owner is already active or closing.")
        service = EphemeralDebugService(
            client,
            resource,
            target,
            policy,
            current,
            environment=environment,
            directory=directory,
            retired=self._retire,
        )
        service.require_observable()
        self._active = service
        return service

    async def close_for_client(self, client: KubernetesSession) -> None:
        self._retired.add(client)
        if self._active is not None and self._active.client is client:
            await self._active.stop_owned()

    async def close(self) -> None:
        self._closed = True
        if self._active is not None:
            await self._active.stop_owned()
