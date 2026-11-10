"""Exact one-use local-manifest review and sequential guarded cluster effects."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.manifests import (
    ManifestAdapter,
    ManifestAdapterPort,
    ManifestRequest,
    ManifestValidation,
)
from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    namespace_name,
)
from kuberich.domain.manifests import (
    FrozenManifestSource,
    ManifestAction,
    ManifestChange,
    ManifestPlan,
    ManifestPlanItem,
    ManifestScope,
    canonical_manifest,
    create_manifest_intent,
    manifest_preview,
    manifest_update_intent,
    resolve_manifest,
)
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.operations import DeleteOptions, ResourceIntent, delete_intent
from kuberich.domain.resources import Discovery, ResourceRecord
from kuberich.domain.targets import MutationTarget, ResourceAddress, ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.mutations import Confirmation
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned


def _record_bytes(record: ResourceRecord) -> bytes:
    return canonical_manifest(record.manifest)


def _failure(error: BaseException, read_only: bool) -> MutationResult:
    if isinstance(error, asyncio.CancelledError):
        return MutationResult(MutationState.CANCELLED, "Cancelled before write; no request sent.")
    if isinstance(error, HttpProblem):
        state = {
            401: MutationState.AUTH_ERROR,
            403: MutationState.DENIED,
            404: MutationState.NOT_FOUND,
            409: MutationState.CONFLICT,
        }.get(error.status, MutationState.REJECTED)
        return MutationResult(state, f"Revalidation refused (HTTP {error.status}); no write sent.")
    if isinstance(error, ConnectionProblem):
        return MutationResult(
            MutationState.TIMEOUT
            if error.state is ConnectionState.TIMEOUT
            else MutationState.UNREACHABLE,
            "Connection failed before write; no request sent.",
        )
    return MutationResult(
        MutationState.BLOCKED if read_only else MutationState.STALE,
        "Captured source, identity, scope or policy changed; no write sent.",
    )


class ManifestMutationService:
    def __init__(
        self,
        client: KubernetesSession,
        scope: ManifestScope,
        discovery: Discovery,
        policy: AccessPolicy,
        source: FrozenManifestSource,
        current: Callable[[], bool],
        require_source: Callable[[], Awaitable[None]],
        environment: Mapping[str, str],
        directory: Path,
        *,
        adapter: ManifestAdapterPort | None = None,
    ) -> None:
        self.client, self.scope, self.discovery, self.policy = client, scope, discovery, policy
        self.source = self._source = source
        self._scope = scope
        self.current, self.require_source = current, require_source
        self.adapter = adapter or ManifestAdapter(client, policy, environment, directory)
        self.intent: ManifestPlan | None = None
        self._target: MutationTarget | None = None
        self._confirmation: Confirmation | None = None
        self._approved: ManifestPlan | None = None
        self._versions: tuple[str | None, ...] = ()
        self._results: list[tuple[MutationTarget, MutationResult]] = []
        self._operations: set[asyncio.Task[object]] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._generation = 0

    @property
    def target(self) -> MutationTarget:
        if self._target is None:
            raise AppError("Prepare an exact manifest destination first.")
        return self._target

    @property
    def operation_count(self) -> int:
        return len(self._operations)

    @property
    def results(self) -> tuple[tuple[MutationTarget, MutationResult], ...]:
        return tuple(self._results)

    def require_current(self) -> None:
        self.policy.require(Action.MUTATE)
        if (
            self._closed
            or not self.current()
            or self.scope != self._scope
            or self.source is not self._source
            or self.client.context.name != self.scope.session.context
        ):
            raise AppError("Captured manifest source/connection changed; prepare again.")

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        self.require_current()
        task = asyncio.current_task()
        assert task is not None
        if self._operations:
            raise AppError("A manifest operation is already active.")
        self._operations.add(task)
        try:
            yield
        finally:
            self._operations.discard(task)

    def invalidate(self) -> None:
        self._generation += 1
        self.intent = self._confirmation = self._approved = None
        self._versions = ()

    def set_namespace(self, namespace: str | None) -> None:
        """Change only the explicit fallback for documents lacking a namespace."""
        self.require_current()
        if self._operations:
            raise AppError("Stop and drain the manifest operation before changing its namespace.")
        if namespace is not None:
            namespace_name(namespace)
        self.invalidate()
        self.scope = self._scope = ManifestScope(session=self.scope.session, namespace=namespace)

    def _guard(self, generation: int) -> None:
        self.require_current()
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if generation != self._generation:
            raise AppError("Manifest review was invalidated; prepare again.")

    async def prepare(self, action: ManifestAction) -> ManifestPlan:
        async with self._operation():
            self.invalidate()
            if action not in {"apply", "delete"}:
                raise AppError("Choose apply or delete for this manifest review.")
            generation = self._generation
            guard = partial(self._guard, generation)
            await self.require_source()
            guard()
            resolved = await parse_owned(
                lambda: tuple(
                    resolve_manifest(document, self.discovery, self.scope)
                    for document in self.source.documents
                )
            )
            guard()
            keys = [
                (address.group, address.resource, address.namespace, address.name)
                for _, address, _ in resolved
            ]
            if not keys or len(keys) != len(set(keys)):
                raise AppError("Manifest source must contain distinct exact resource destinations.")
            items: list[ManifestPlanItem] = []
            versions: list[str | None] = []
            for document, (resource, address, desired) in zip(
                self.source.documents, resolved, strict=True
            ):
                target: MutationTarget = address
                request: ManifestRequest | None = None
                receipt: ManifestValidation | None = None
                version = None
                change: ManifestChange = "refused"
                pages: tuple[str, ...] = ()
                try:
                    guard()
                    baseline = await self.adapter.read(resource, address, guard)
                    guard()
                    if baseline is None:
                        if action == "delete":
                            change = "absent"
                            validation = MutationResult(
                                MutationState.SUCCEEDED,
                                "Absent at review; no deletion request planned.",
                            )
                        else:
                            request = await parse_owned(
                                partial(create_manifest_intent, resource, address, desired)
                            )
                            change = "create"
                            receipt = await self.adapter.validate(request, guard)
                            validation = receipt.result
                            if receipt.body is not None:
                                pages = await parse_owned(
                                    partial(manifest_preview, None, receipt.body)
                                )
                    else:
                        target = ResourceTarget(
                            address.session,
                            address.group,
                            address.resource,
                            address.namespace,
                            address.name,
                            baseline.uid or "",
                        )
                        version = baseline.resource_version
                        before = await parse_owned(partial(_record_bytes, baseline))
                        if action == "delete":
                            request = await parse_owned(
                                partial(
                                    delete_intent,
                                    resource,
                                    target,
                                    baseline,
                                    DeleteOptions(propagation="Background"),
                                )
                            )
                            change = "delete"
                            receipt = await self.adapter.validate(request, guard)
                            validation = receipt.result
                            pages = await parse_owned(partial(manifest_preview, None, before))
                        else:
                            receipt = await self.adapter.preview_update(
                                resource, target, desired, baseline, guard
                            )
                            validation = receipt.result
                            if validation.state is MutationState.SUCCEEDED:
                                if receipt.body is None:
                                    raise AppError("Server preview returned no verified object.")
                                request = await parse_owned(
                                    partial(
                                        manifest_update_intent,
                                        resource,
                                        target,
                                        baseline,
                                        receipt.body,
                                    )
                                )
                                change = "unchanged" if request is None else "update"
                                if request is not None:
                                    receipt = await self.adapter.validate(request, guard)
                                    validation = receipt.result
                                if receipt.body is not None:
                                    pages = await parse_owned(
                                        partial(manifest_preview, before, receipt.body)
                                    )
                    if (
                        request is not None
                        and validation.state is MutationState.SUCCEEDED
                        and (receipt is None or receipt.body is None)
                    ):
                        raise AppError("Strict validation returned no verified response preview.")
                    guard()
                except (HttpProblem, ConnectionProblem, AppError) as error:
                    validation = _failure(error, self.policy.read_only)
                items.append(
                    ManifestPlanItem(
                        document=document,
                        resource=resource,
                        target=target,
                        change=change,
                        request=request,
                        resource_version=version,
                        validation=validation,
                        preview_pages=pages,
                    )
                )
                versions.append(version)
            await self.require_source()
            guard()
            self.intent = ManifestPlan(
                identity=uuid4(),
                source_identity=self.source.identity,
                source_sha256=self.source.source_sha256,
                scope=self.scope,
                action=action,
                items=tuple(items),
            )
            self._versions = tuple(versions)
            self._target = items[0].target
            self._results = []
            return self.intent

    def confirm(self, intent: ManifestPlan) -> Confirmation:
        if self._operations:
            raise AppError(
                "A manifest batch is already admitted; finish it or prepare a new review."
            )
        self._confirmation = self._approved = None
        self.require_current()
        if (
            not isinstance(intent, ManifestPlan)
            or intent is not self.intent
            or not intent.ready
            or intent.scope != self.scope
            or intent.source_identity != self.source.identity
            or intent.source_sha256 != self.source.source_sha256
        ):
            raise AppError("Confirmation requires this exact fully validated manifest plan.")
        self._approved = intent
        self._confirmation = Confirmation(intent.identity, uuid4())
        return self._confirmation

    async def _revalidate(
        self, item: ManifestPlanItem, version: str | None, guard: Callable[[], None]
    ) -> MutationResult | None:
        await self.require_source()
        guard()
        address = ResourceAddress(
            item.target.session,
            item.target.group,
            item.target.resource,
            item.target.namespace,
            item.target.name,
        )
        record = await self.adapter.read(item.resource, address, guard)
        guard()
        if isinstance(item.target, ResourceAddress):
            if record is not None:
                return MutationResult(
                    MutationState.CONFLICT, "Reviewed absent name now exists; no write sent."
                )
        elif record is None:
            return MutationResult(
                MutationState.NOT_FOUND, "Reviewed UID disappeared; no write sent."
            )
        elif record.uid != item.target.uid:
            return MutationResult(
                MutationState.STALE, "Reviewed name has a replacement UID; no write sent."
            )
        elif record.resource_version != version:
            return MutationResult(
                MutationState.CONFLICT, "Reviewed version changed; prepare and confirm again."
            )
        await self.require_source()
        guard()
        return None

    async def _observe(
        self, item: ManifestPlanItem, guard: Callable[[], None]
    ) -> tuple[MutationResult, bool]:
        cancelled = False
        try:
            address = ResourceAddress(
                item.target.session,
                item.target.group,
                item.target.resource,
                item.target.namespace,
                item.target.name,
            )
            record = await self.adapter.read(item.resource, address, guard)
            if record is None or record.uid != item.target.uid:
                return MutationResult(
                    MutationState.SUCCEEDED,
                    "Captured UID is gone; replacements left untouched. Dependent cleanup is not verified.",
                ), False
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass
        return MutationResult(
            MutationState.ACCEPTED,
            "Deletion accepted; completion/finalizers remain to be observed. No retry was sent.",
        ), cancelled

    def execute(self, confirmation: Confirmation) -> Coroutine[Any, Any, MutationResult]:
        """Admit synchronously so cancellation before coroutine entry cannot replay proof."""
        intent, approved, proof = self.intent, self._approved, self._confirmation
        # Every attempt consumes the proof synchronously, including forged submissions.
        self._confirmation = self._approved = None
        if (
            not isinstance(confirmation, Confirmation)
            or confirmation is not proof
            or intent is None
            or intent is not approved
            or not intent.ready
        ):
            return self._blocked()
        self.intent = None
        return self._execute(intent, self._generation, self._versions, [])

    async def _blocked(self) -> MutationResult:
        return MutationResult(
            MutationState.BLOCKED, "An unused exact manifest confirmation is required."
        )

    async def _execute(
        self,
        intent: ManifestPlan,
        generation: int,
        versions: tuple[str | None, ...],
        results: list[tuple[MutationTarget, MutationResult]],
    ) -> MutationResult:
        guard = partial(self._guard, generation)
        stopped: MutationResult | None = None
        try:
            async with self._operation():
                guard()
                self._results = results
                for item, version in zip(intent.items, versions, strict=True):
                    if stopped is not None:
                        results.append(
                            (
                                item.target,
                                MutationResult(
                                    MutationState.BLOCKED,
                                    "Unsent: batch stopped after an earlier failure or uncertainty.",
                                ),
                            )
                        )
                        continue
                    try:
                        result = await self._revalidate(item, version, guard)
                        if result is None:
                            result = (
                                MutationResult(
                                    MutationState.SUCCEEDED, "Reviewed no-op; no request sent."
                                )
                                if item.request is None
                                else await self.adapter.execute(item.request, guard)
                            )
                            if result.state is MutationState.ACCEPTED and isinstance(
                                item.request, ResourceIntent
                            ):
                                result, cancelled = await self._observe(item, guard)
                                if cancelled:
                                    stopped = MutationResult(
                                        MutationState.CANCELLED,
                                        "Stopped after accepted deletion; later requests remain unsent.",
                                    )
                    except (
                        asyncio.CancelledError,
                        HttpProblem,
                        ConnectionProblem,
                        AppError,
                    ) as error:
                        result = _failure(error, self.policy.read_only)
                    except Exception:
                        result = MutationResult(
                            MutationState.UNCERTAIN,
                            "Unexpected operation failure; inspect this target before a new review.",
                        )
                    results.append((item.target, result))
                    if result.state not in {MutationState.SUCCEEDED, MutationState.ACCEPTED}:
                        stopped = result
        except (asyncio.CancelledError, AppError) as error:
            stopped = _failure(error, self.policy.read_only)
            results.extend(
                (
                    item.target,
                    MutationResult(
                        MutationState.BLOCKED, "Unsent: batch stopped before this request."
                    ),
                )
                for item in intent.items[len(results) :]
            )
        if any(result.state is MutationState.UNCERTAIN for _, result in results):
            state = MutationState.UNCERTAIN
        elif stopped is not None:
            progressed = any(
                item.request is not None
                and result.state in {MutationState.SUCCEEDED, MutationState.ACCEPTED}
                for item, (_, result) in zip(intent.items, results, strict=True)
            )
            state = MutationState.PARTIAL if progressed else stopped.state
        else:
            state = (
                MutationState.ACCEPTED
                if any(result.state is MutationState.ACCEPTED for _, result in results)
                else MutationState.SUCCEEDED
            )
        return MutationResult(
            state,
            "Manifest batch stopped. Current operation: "
            + stopped.message
            + " Inspect per-resource outcomes before a new review."
            if stopped is not None
            else "Manifest batch finished; inspect per-resource outcomes.",
            tuple(results),
        )

    async def _close(self) -> None:
        self._closed = True
        self.invalidate()
        tasks = tuple(self._operations)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        await self.adapter.close()

    async def close(self) -> None:
        if self._closing is None or (
            self._closing.done()
            and not self._closing.cancelled()
            and self._closing.exception() is not None
        ):
            self._closing = asyncio.create_task(self._close())
        await finish_owned(self._closing)
