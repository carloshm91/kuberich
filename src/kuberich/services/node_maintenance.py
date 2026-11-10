"""One owned, finite, reviewed Node maintenance operation on a captured client."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import replace
from functools import partial
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_maintenance import evict_pod, patch_node
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.node_maintenance import (
    DrainOptions,
    MaintenanceMode,
    MaintenanceProgress,
    MaintenanceReview,
    NodeObservation,
    NodeState,
    PodProgress,
    PodReview,
    PodState,
    consent_blockers,
    eviction_body,
    matching_pdbs,
    node_patch,
    node_state,
    pod_facts,
)
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.relationships import RelationshipStatus, owner_references
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.processes import _finish_owned
from kuberich.services.resources import ResourceReader, parse_owned


class NodeMaintenanceService:
    """Implements MutationSource without broadening the generic batch-write port."""

    _active: WeakKeyDictionary[KubernetesSession, set[str]] = WeakKeyDictionary()

    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        discovery: Discovery,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.discovery, self.policy, self.current = discovery, policy, current
        self.clock, self.wall_clock, self.sleep = clock, wall_clock, sleep
        self.intent: MaintenanceReview | None = None
        self._proof: Confirmation | None = None
        self._approved: MaintenanceReview | None = None
        self._closed = False
        self._used_review: MaintenanceReview | None = None
        self._pending = False
        self._jobs: set[asyncio.Task[object]] = set()
        self._progress = MaintenanceProgress(
            (), NodeObservation(NodeState.UNKNOWN, wall_clock()), False
        )

    @property
    def progress(self) -> MaintenanceProgress:
        return self._progress

    @property
    def operation_count(self) -> int:
        return len(self._jobs)

    @property
    def is_live(self) -> bool:
        return bool(self.operation_count) or self._pending

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        r, t = self.resource, self.target
        if (
            (r.group, r.version, r.name, r.kind, r.namespaced) != ("", "v1", "nodes", "Node", False)
            or not {"get", "patch"}.issubset(r.verbs)
            or (t.group, t.resource, t.namespace, t.container) != ("", "nodes", None, None)
        ):
            raise AppError("Maintenance requires a captured readable and patchable core/v1 Node.")
        if self._closed or not self.current() or self.client.context.name != t.session.context:
            raise AppError("Maintenance target/connection changed. Select the Node again.")

    def _register(self) -> asyncio.Task[object]:
        task = asyncio.current_task()
        assert task is not None
        self._jobs.add(task)
        return task

    async def _node(self) -> ResourceRecord:
        self.require_current()
        record = await ResourceReader(self.client).get(self.resource, self.target.name)
        self.require_current()
        state = node_state(record, self.target)
        self._progress = replace(
            self._progress,
            node=NodeObservation(
                NodeState.CORDONED if state else NodeState.SCHEDULABLE,
                self.wall_clock(),
                record.uid,
            ),
        )
        return record

    def _pods_resource(self) -> ApiResource:
        r = self.discovery.find("pods", version="v1")
        if r.kind != "Pod" or not r.namespaced or not {"get", "list"}.issubset(r.verbs):
            raise AppError("Readable core/v1 Pod discovery is required.")
        return r

    async def _inventory(self, reader: ResourceReader) -> tuple[ResourceRecord, ...]:
        self.require_current()
        snapshot = await reader.list(
            self._pods_resource(),
            query=ResourceQuery(field_selector=f"spec.nodeName={self.target.name}"),
        )
        self.require_current()
        if not snapshot.collection.complete or snapshot.collection.limited:
            raise AppError("Node Pod inventory is incomplete; no drain can be confirmed.")
        # Validate every returned member, even exclusions and terminal Pods.
        await parse_owned(
            lambda: tuple(pod_facts(record, self.target) for record in snapshot.items)
        )
        return snapshot.items

    async def _eviction_supported(self, reader: ResourceReader) -> None:
        if reader.budget is not None:
            reader.budget.charge()
        data = await self.client.get_json("/api/v1")
        self.require_current()
        resources = data.get("resources")
        if not isinstance(resources, list) or len(resources) > 8192:
            raise AppError("Eviction subresource discovery is unavailable.")
        if not any(
            isinstance(r, dict)
            and r.get("name") == "pods/eviction"
            and r.get("kind") == "Eviction"
            and r.get("namespaced") is True
            and r.get("group") == "policy"
            and r.get("version") == "v1"
            and isinstance(r.get("verbs"), list)
            and "create" in r["verbs"]
            for r in resources
        ):
            raise AppError(
                "The server does not advertise policy/v1 Pod eviction; no fallback is allowed."
            )

    async def _review_pods(
        self, options: DrainOptions
    ) -> tuple[tuple[PodReview, ...], tuple[str, ...]]:
        reader = ResourceReader(self.client, budget=ReadBudget())
        await self._eviction_supported(reader)
        records = await self._inventory(reader)
        pdb_resource = self.discovery.find("poddisruptionbudgets", group="policy", version="v1")
        if not pdb_resource.namespaced or pdb_resource.kind != "PodDisruptionBudget":
            raise AppError("Exact policy/v1 PDB discovery is required.")
        pdbs: dict[str, tuple[ResourceRecord, ...]] = {}
        for namespace in sorted({r.namespace for r in records if r.namespace is not None}):
            snapshot = await reader.list(pdb_resource, namespace)
            self.require_current()
            if not snapshot.collection.complete or snapshot.collection.limited:
                raise AppError("PDB inventory is incomplete; no drain can be confirmed.")
            pdbs[namespace] = snapshot.items
        cache: dict[tuple[str, str, str | None, str], ResourceRecord | None] = {}
        result = []
        blockers: list[str] = []
        for record in records:
            mirror, terminating, phase, ready, storage, emptydir = await parse_owned(
                partial(pod_facts, record, self.target)
            )
            owners = await parse_owned(
                partial(owner_references, self._pods_resource(), record, self.discovery)
            )
            owner, managed, daemonset = "Unmanaged; recreation is not guaranteed", False, False
            errors = []
            if any(o.status is not RelationshipStatus.READY for o in owners):
                errors.append(
                    "Controller discovery/identity is unverified; force cannot override it."
                )
            controllers = [o for o in owners if o.controller]
            if len(controllers) > 1:
                errors.append("Multiple controller references are invalid.")
            elif controllers and not errors:
                ref = controllers[0].target
                descriptor = ref.resource
                assert descriptor is not None
                key = descriptor.api_version, descriptor.name, ref.namespace, ref.name
                try:
                    if key not in cache:
                        try:
                            cache[key] = await reader.get(descriptor, ref.name, ref.namespace)
                        except HttpProblem as error:
                            if error.status != 404:
                                raise
                            cache[key] = None
                    observed = cache[key]
                    self.require_current()
                    if observed is not None and (not observed.uid or not observed.resource_version):
                        raise AppError("Controller response identity is malformed.")
                    if observed is not None and observed.uid == ref.uid:
                        managed = True
                        owner = (
                            f"{descriptor.kind}/{ref.name} (UID verified; recovery not guaranteed)"
                        )
                        daemonset = (descriptor.group, descriptor.name) == ("apps", "daemonsets")
                    else:
                        owner = "Orphaned controller; recreation is not guaranteed"
                except (HttpProblem, ConnectionProblem, AppError):
                    errors.append("Controller read is unavailable; ownership remains unverified.")
            target = ResourceTarget(
                self.target.session, "", "pods", record.namespace, record.name, record.uid or ""
            )
            budgets = await parse_owned(
                partial(matching_pdbs, pdbs[record.namespace or ""], record)
            )
            pod = PodReview(
                target,
                record.resource_version or "",
                owner,
                managed,
                daemonset,
                mirror,
                terminating,
                phase,
                ready,
                storage,
                emptydir,
                budgets,
                tuple(errors),
                eviction_body(target, record.resource_version or ""),
                len(resource_object(record.manifest.get("metadata")).get("finalizers", [])),
            )
            result.append(pod)
            blockers.extend(
                f"{target.namespace}/{target.name}: {b}" for b in consent_blockers(pod, options)
            )
        return tuple(result), tuple(blockers)

    async def prepare(
        self, mode: MaintenanceMode, options: DrainOptions | None = None
    ) -> MaintenanceReview:
        self.require_current()
        options = DrainOptions() if options is None else options
        if not isinstance(mode, MaintenanceMode) or not isinstance(options, DrainOptions):
            raise AppError("Maintenance requires a valid mode and reviewed options.")
        if self.is_live or self.target.uid in self._active.get(self.client, set()):
            raise AppError("Stop and drain the existing Node maintenance operation first.")
        self.intent = self._proof = self._approved = None
        task = self._register()
        try:
            async with asyncio.timeout(min(30, options.timeout_seconds)):
                record = await self._node()
                patch = node_patch(self.resource, self.target, record, mode)
                pods: tuple[PodReview, ...] = ()
                blockers: tuple[str, ...] = ()
                if mode is MaintenanceMode.DRAIN:
                    try:
                        pods, blockers = await self._review_pods(options)
                    except (AppError, ConnectionProblem, HttpProblem, ReadBudgetExceeded):
                        blockers = (
                            "Complete Pod/controller/PDB preview is unavailable; resolve access or malformed evidence and review again.",
                        )
                self.require_current()
                review = MaintenanceReview(
                    mode,
                    self.target,
                    record.resource_version or "",
                    node_state(record, self.target),
                    options,
                    pods,
                    blockers,
                    patch,
                )
                self.intent = review
                self._progress = replace(
                    self._progress,
                    pods=tuple(
                        PodProgress(
                            p.target.uid,
                            p.target.namespace or "",
                            p.target.name,
                            PodState.SKIPPED
                            if p.retained
                            else PodState.TERMINATING
                            if p.terminating
                            else PodState.QUEUED,
                            "DaemonSet/mirror Pod remains running" if p.retained else "",
                        )
                        for p in pods
                    ),
                )
                return review
        finally:
            self._jobs.discard(task)

    def confirm(self, review: MaintenanceReview) -> Confirmation:
        self.require_current()
        if (
            review is not self.intent
            or not isinstance(review, MaintenanceReview)
            or review.blockers
            or review is self._used_review
        ):
            raise AppError("Confirm the exact complete, unblocked maintenance review.")
        self._proof = Confirmation(review.identity, uuid4())
        self._approved = review
        return self._proof

    def _pod_progress(
        self,
        uid: str,
        state: PodState,
        message: str = "",
        *,
        attempts: int | None = None,
        retry_at: float | None = None,
        http_status: int | None = None,
    ) -> None:
        self._progress = replace(
            self._progress,
            pods=tuple(
                replace(
                    p,
                    state=state,
                    message=message,
                    attempts=p.attempts if attempts is None else attempts,
                    retry_at=retry_at,
                    http_status=p.http_status if http_status is None else http_status,
                )
                if p.uid == uid
                else p
                for p in self._progress.pods
            ),
        )

    async def _pod(self, pod: PodReview) -> ResourceRecord | None:
        self.require_current()
        try:
            record = await ResourceReader(self.client).get(
                self._pods_resource(), pod.target.name, pod.target.namespace
            )
        except HttpProblem as error:
            if error.status != 404:
                raise
            return None
        self.require_current()
        return record if record.uid == pod.target.uid else None

    async def _guard_node(self) -> None:
        if not node_state(await self._node(), self.target):
            raise AppError("Node was externally uncordoned; further evictions stopped.")

    async def _drain(self, review: MaintenanceReview, deadline: float) -> MutationResult:
        pods = {p.target.uid: p for p in review.pods if not p.retained}
        due = {uid: self.clock() for uid in pods}
        while pods:
            self.require_current()
            if self.clock() >= deadline:
                return MutationResult(
                    MutationState.PARTIAL,
                    "Drain deadline reached; accepted work remains and scheduling is separately observed.",
                )
            for uid, pod in tuple(pods.items()):
                if self.clock() < due[uid]:
                    continue
                await self._guard_node()
                record = await self._pod(pod)
                if record is None:
                    self._pod_progress(uid, PodState.ABSENT, "Original reviewed Pod UID is absent.")
                    del pods[uid]
                    continue
                current = next(p for p in self._progress.pods if p.uid == uid)
                terminating = (
                    resource_object(record.manifest.get("metadata")).get("deletionTimestamp")
                    is not None
                )
                if current.state in {PodState.ACCEPTED, PodState.TERMINATING} or terminating:
                    self._pod_progress(
                        uid,
                        PodState.TERMINATING if terminating else current.state,
                        "Accepted/terminating Pod remains; no eviction replay.",
                    )
                    due[uid] = self.clock() + 1
                    continue
                if record.resource_version != pod.resource_version:
                    self._pod_progress(
                        uid, PodState.STALE, "Pod version changed; start a fresh review."
                    )
                    return MutationResult(
                        MutationState.CONFLICT,
                        "Reviewed Pod version changed; no rebase or replay was made.",
                    )
                self.require_current()
                attempt = await evict_pod(self.client, pod, self.require_current, self.wall_clock)
                count = current.attempts + 1
                # Publish the receipt before another await can observe cancellation.
                if attempt.result.state is MutationState.ACCEPTED:
                    self._pod_progress(
                        uid,
                        PodState.ACCEPTED,
                        attempt.result.message,
                        attempts=count,
                        http_status=attempt.status,
                    )
                    due[uid] = self.clock() + 1
                elif attempt.retry_seconds is not None:
                    due[uid] = self.clock() + attempt.retry_seconds
                    self._pod_progress(
                        uid,
                        PodState.RETRYING,
                        attempt.result.message,
                        attempts=count,
                        retry_at=due[uid],
                        http_status=attempt.status,
                    )
                else:
                    state = (
                        PodState.UNCERTAIN
                        if attempt.result.state is MutationState.UNCERTAIN
                        else PodState.FAILED
                    )
                    self._pod_progress(
                        uid,
                        state,
                        attempt.result.message,
                        attempts=count,
                        http_status=attempt.status,
                    )
                    if attempt.status == 404:
                        observed = await self._pod(pod)
                        if observed is None:
                            self._pod_progress(
                                uid,
                                PodState.ABSENT,
                                "Original UID absent after 404; no eviction credited.",
                            )
                            del pods[uid]
                            continue
                    return attempt.result
            if pods:
                wait = min(
                    max(0.0, min(due[uid] for uid in pods) - self.clock()),
                    max(0.0, deadline - self.clock()),
                )
                await self.sleep(wait)
        await self._guard_node()
        records = await self._inventory(ResourceReader(self.client))
        retained = {p.target.uid for p in review.pods if p.retained}
        if any(record.uid not in retained for record in records):
            return MutationResult(
                MutationState.PARTIAL,
                "Unreviewed Node Pod arrivals remain; a fresh drain review is required.",
            )
        return MutationResult(
            MutationState.SUCCEEDED,
            "Reviewed Pod UIDs absent; complete inventory and same Node observed cordoned. Retained DaemonSet/mirror Pods may remain.",
        )

    async def _run(self, review: MaintenanceReview) -> MutationResult:
        deadline = self.clock() + review.options.timeout_seconds
        async with asyncio.timeout(review.options.timeout_seconds):
            record = await self._node()
            if record.resource_version != review.node_resource_version:
                return MutationResult(
                    MutationState.CONFLICT, "Node version changed; read and confirm a new review."
                )
            if review.mode is MaintenanceMode.DRAIN:
                records = await self._inventory(ResourceReader(self.client))
                original = {p.target.uid: p for p in review.pods}
                for pod in records:
                    if (
                        pod.uid not in original
                        or pod.resource_version != original[pod.uid].resource_version
                    ):
                        return MutationResult(
                            MutationState.CONFLICT,
                            "Node Pod membership/version changed before cordon; prepare a fresh review.",
                        )
            desired = review.mode is not MaintenanceMode.UNCORDON
            if node_state(record, self.target) is not desired:
                self.require_current()
                result = await patch_node(self.client, review.patch, self.require_current, desired)
                if result.state is not MutationState.SUCCEEDED:
                    return result
            if review.mode is MaintenanceMode.DRAIN:
                return await self._drain(review, deadline)
            observed = await self._node()
            if node_state(observed, self.target) is not desired:
                return MutationResult(
                    MutationState.CONFLICT,
                    "Node scheduling changed after the operation; review again.",
                )
            return MutationResult(
                MutationState.SUCCEEDED,
                "Node freshly observed " + ("cordoned." if desired else "schedulable."),
            )

    async def _final_observation(self) -> None:
        # Preserve the original client and bound teardown; never reconnect for observation.
        try:
            if not self.current() or self.client.api is None:
                raise AppError("Captured connection retired.")
            async with asyncio.timeout(min(5.0, self.client.timeout)):
                record = await ResourceReader(self.client).get(self.resource, self.target.name)
                if record.uid != self.target.uid:
                    state = NodeState.REPLACED
                else:
                    state = (
                        NodeState.CORDONED
                        if node_state(record, self.target)
                        else NodeState.SCHEDULABLE
                    )
                observation = NodeObservation(state, self.wall_clock(), record.uid)
        except HttpProblem as error:
            observation = NodeObservation(
                NodeState.ABSENT if error.status == 404 else NodeState.UNKNOWN, self.wall_clock()
            )
        except (AppError, ConnectionProblem, TimeoutError):
            observation = NodeObservation(NodeState.UNKNOWN, self.wall_clock())
        self._progress = replace(self._progress, node=observation)

    def execute(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        review = self.intent
        if (
            review is None
            or confirmation is not self._proof
            or review is not self._approved
            or not isinstance(confirmation, Confirmation)
            or review.blockers
        ):
            return self._blocked()
        self._proof = self._approved = None
        self._used_review = review
        self._pending = True
        return self._execute(review)

    async def _blocked(self) -> MutationResult:
        return MutationResult(
            MutationState.BLOCKED,
            "An unused confirmation for the exact complete review is required.",
        )

    async def _execute(self, review: MaintenanceReview) -> MutationResult:
        self._pending = False
        task = self._register()
        active = self._active.setdefault(self.client, set())
        admitted = False
        try:
            self.require_current()
            if self.target.uid in active:
                return MutationResult(
                    MutationState.BLOCKED, "Another maintenance operation owns this Node."
                )
            active.add(self.target.uid)
            admitted = True
            self._progress = replace(self._progress, running=True)
            try:
                result = await self._run(review)
            except asyncio.CancelledError:
                result = MutationResult(
                    MutationState.PARTIAL
                    if any(p.attempts for p in self._progress.pods)
                    else MutationState.CANCELLED,
                    "Maintenance stopped; completed evictions remain. Uncordon is a separate reviewed operation.",
                )
            except TimeoutError:
                result = MutationResult(
                    MutationState.PARTIAL,
                    "Drain deadline reached; completed or uncertain effects remain.",
                )
            except HttpProblem as error:
                result = MutationResult(
                    MutationState.DENIED if error.status == 403 else MutationState.REJECTED,
                    "API observation refused; further writes stopped.",
                )
            except ConnectionProblem:
                result = MutationResult(
                    MutationState.UNREACHABLE,
                    "API observation unavailable; further writes stopped.",
                )
            except AppError:
                result = MutationResult(
                    MutationState.BLOCKED if self.policy.read_only else MutationState.STALE,
                    "Write policy, Node identity, or observed scheduling changed; further writes stopped.",
                )
            self._progress = replace(
                self._progress,
                pods=tuple(
                    replace(
                        p,
                        state=PodState.NOT_SENT,
                        message="No further eviction sent; new review required.",
                        retry_at=None,
                    )
                    if p.state in {PodState.QUEUED, PodState.RETRYING}
                    else p
                    for p in self._progress.pods
                ),
            )
            final = asyncio.create_task(self._final_observation())
            await _finish_owned(final)
            return MutationResult(
                result.state,
                result.message
                + " Final Node: "
                + self._progress.node.state.value
                + f" (observed at {self._progress.node.observed_at:.3f}).",
            )
        except AppError:
            return MutationResult(
                MutationState.BLOCKED if self.policy.read_only else MutationState.STALE,
                "Maintenance admission refused; no write started.",
            )
        finally:
            if admitted:
                active.discard(self.target.uid)
            self._progress = replace(self._progress, running=False)
            self._jobs.discard(task)

    async def close(self) -> None:
        self._closed = True
        self._pending = False
        jobs = tuple(task for task in self._jobs if task is not asyncio.current_task())
        for task in jobs:
            task.cancel()
        await _finish_owned(asyncio.gather(*jobs, return_exceptions=True))
