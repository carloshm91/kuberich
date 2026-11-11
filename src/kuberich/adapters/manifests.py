"""Owned server previews and non-replayed, strictly validated manifest writes."""

import asyncio
import json
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Any, Protocol

from kuberich.adapters.editing import ManifestFile, file_worker
from kuberich.adapters.kubernetes import KubernetesSession, decode_json
from kuberich.adapters.mutations import guarded_request
from kuberich.adapters.operations import operation_receipt
from kuberich.domain.connections import HttpProblem
from kuberich.domain.manifests import (
    CreatedResourceReceipt,
    ManifestCreateIntent,
    create_manifest_intent,
    manifest_status,
)
from kuberich.domain.mutations import MutationIntent, MutationResult, MutationState
from kuberich.domain.operations import ResourceAction, ResourceIntent, operation_json
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, ProcessStatus
from kuberich.domain.resources import (
    ApiResource,
    ResourceRecord,
    api_segment,
    resource_object,
    resource_record,
)
from kuberich.domain.targets import ResourceAddress, ResourceTarget
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import parse_owned

type ManifestRequest = MutationIntent | ResourceIntent | ManifestCreateIntent
type ManifestGuard = Callable[[], None]


@dataclass(frozen=True, repr=False)
class ManifestValidation:
    result: MutationResult
    body: bytes | None = field(default=None, repr=False)
    created: CreatedResourceReceipt | None = None


@dataclass(frozen=True)
class ManifestCreationResult:
    result: MutationResult
    receipt: CreatedResourceReceipt | None = None


class ManifestAdapterPort(Protocol):
    async def read(
        self, resource: ApiResource, address: ResourceAddress, guard: ManifestGuard
    ) -> ResourceRecord | None: ...
    async def preview_update(
        self,
        resource: ApiResource,
        target: ResourceTarget,
        desired: bytes,
        baseline: ResourceRecord,
        guard: ManifestGuard,
    ) -> ManifestValidation: ...
    async def validate(
        self, intent: ManifestRequest, guard: ManifestGuard
    ) -> ManifestValidation: ...
    async def execute(self, intent: ManifestRequest, guard: ManifestGuard) -> MutationResult: ...
    async def execute_creation(
        self, intent: ManifestCreateIntent, guard: ManifestGuard
    ) -> ManifestCreationResult: ...
    async def close(self) -> None: ...


def _object(
    data: bytes,
    resource: ApiResource,
    address: ResourceAddress | ResourceTarget,
    *,
    existing: bool,
    version: str | None = None,
) -> ResourceRecord:
    try:
        value = decode_json(data)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Server returned an invalid manifest response.") from None
    if value.get("apiVersion") != resource.api_version or value.get("kind") != resource.kind:
        raise AppError("Server returned a different manifest type.")
    if not existing:
        # A create dry-run is an address preview, not a persisted watch snapshot.
        # API strategies may omit/empty these transient server-generated fields.
        metadata = resource_object(value.get("metadata"))
        value = {
            **value,
            "metadata": {
                key: item
                for key, item in metadata.items()
                if key not in {"uid", "resourceVersion"} or item not in {None, ""}
            },
        }
        resource = replace(resource, verbs=resource.verbs - {"watch"})
    record = resource_record(resource, value, address.namespace)
    if record.name != address.name or record.namespace != address.namespace:
        raise AppError("Server returned a different manifest destination.")
    if existing and (not record.uid or not record.resource_version):
        raise AppError("Server returned an object without persistent identity/version.")
    if isinstance(address, ResourceTarget) and record.uid != address.uid:
        raise AppError("Server returned a different manifest UID.")
    if version is not None and record.resource_version != version:
        raise AppError("Server preview returned a different manifest version.")
    return record


def _helper_failure(status: ProcessStatus, stderr: bytes) -> MutationResult:
    state = {
        ProcessStatus.CANCELLED: MutationState.CANCELLED,
        ProcessStatus.TIMED_OUT: MutationState.TIMEOUT,
    }.get(status, MutationState.REJECTED)
    lower = stderr[:65536].lower()
    for marker, category in (
        (b"(forbidden)", MutationState.DENIED),
        (b"(unauthorized)", MutationState.AUTH_ERROR),
        (b"(conflict)", MutationState.CONFLICT),
        (b"(notfound)", MutationState.NOT_FOUND),
    ):
        if marker in lower:
            state = category
            break
    return MutationResult(
        state,
        f"Server apply preview refused: {state.value}. Freeform helper details withheld; no write sent.",
    )


class ManifestAdapter:
    def __init__(
        self,
        client: KubernetesSession,
        policy: AccessPolicy,
        environment: Mapping[str, str],
        directory: Path,
    ) -> None:
        self.client, self.policy = client, policy
        self.environment, self.directory = dict(environment), directory.absolute()
        self.runner = ProcessRunner(policy, output_limit=8 * 1024 * 1024)
        self._closed = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._drafts: set[ManifestFile] = set()
        self._closing: asyncio.Task[None] | None = None

    async def _owned[T](self, operation: Callable[[], Coroutine[Any, Any, T]]) -> T:
        if self._closed:
            raise AppError("Manifest adapter is closed.")
        task = asyncio.create_task(operation())
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            if not task.cancelled() and task.exception() is None:
                return task.result()
            raise
        finally:
            self._tasks.discard(task)

    def _check(self, guard: ManifestGuard) -> None:
        self.policy.require(Action.MUTATE)
        if self._closed:
            raise AppError("Manifest adapter is closed.")
        guard()

    async def read(
        self, resource: ApiResource, address: ResourceAddress, guard: ManifestGuard
    ) -> ResourceRecord | None:
        return await self._owned(partial(self._read, resource, address, guard))

    async def _read(
        self, resource: ApiResource, address: ResourceAddress, guard: ManifestGuard
    ) -> ResourceRecord | None:
        self._check(guard)
        if (
            resource.group != address.group
            or resource.name != address.resource
            or resource.namespaced != (address.namespace is not None)
            or "get" not in resource.verbs
        ):
            raise AppError("Manifest read requires an exact readable discovered destination.")
        path = resource.path(address.namespace) + "/" + api_segment(address.name)
        try:
            value = await self.client.get_json(path)
        except HttpProblem as error:
            self._check(guard)
            if error.status == 404:
                return None
            raise
        self._check(guard)
        data = await parse_owned(partial(json.dumps, value, allow_nan=False))
        record = await parse_owned(
            partial(_object, data.encode(), resource, address, existing=True)
        )
        self._check(guard)
        return record

    async def preview_update(
        self,
        resource: ApiResource,
        target: ResourceTarget,
        desired: bytes,
        baseline: ResourceRecord,
        guard: ManifestGuard,
    ) -> ManifestValidation:
        return await self._owned(
            partial(self._preview_update, resource, target, desired, baseline, guard)
        )

    async def _preview_update(
        self,
        resource: ApiResource,
        target: ResourceTarget,
        desired: bytes,
        baseline: ResourceRecord,
        guard: ManifestGuard,
    ) -> ManifestValidation:
        self._check(guard)
        await self.client.refresh_credentials()
        self._check(guard)
        material = capture_delegation(
            self.client, self.environment, self.directory, prefix="manifest"
        )

        def create() -> ManifestFile:
            draft = ManifestFile(desired)
            self._drafts.add(draft)
            return draft

        def discard(draft: ManifestFile) -> None:
            draft.close()
            self._drafts.discard(draft)

        try:
            draft = await file_worker(create, discard=discard)
        except OSError:
            raise AppError("Private manifest preview file preparation or cleanup failed.") from None
        try:
            async with stage_connection(material.path, material.configuration):
                self._check(guard)
                variables = dict(material.environment)
                variables.update(KUBECONFIG=str(material.path), KUBECTL_KUBERC="false")
                command = ProcessCommand(
                    (
                        "kubectl",
                        f"--kubeconfig={material.path}",
                        f"--context={target.session.context}",
                        *(
                            (f"--namespace={target.namespace}",)
                            if target.namespace is not None
                            else ()
                        ),
                        f"--cache-dir={draft.path.parent / 'cache'}",
                        f"--request-timeout={min(self.client.timeout, 60):g}s",
                        "apply",
                        "--server-side=false",
                        "--dry-run=server",
                        "--validate=strict",
                        "--field-manager=kuberich-manifests",
                        "--output=json",
                        f"--filename={draft.path}",
                    ),
                    tuple(variables.items()),
                    material.directory,
                    ProcessMode.CAPTURE,
                    ProcessPurpose.MANIFEST_PREVIEW,
                    target,
                )
                try:
                    result = await self.runner.capture(
                        command, timeout=min(self.client.timeout, 60), guard=guard
                    )
                except ExecutableUnavailable:
                    return ManifestValidation(
                        MutationResult(
                            MutationState.REJECTED,
                            "kubectl is unavailable; strict server apply preview is required.",
                        )
                    )
                self._check(guard)
                if result.status is not ProcessStatus.SUCCEEDED:
                    return ManifestValidation(_helper_failure(result.status, result.stderr))
                await parse_owned(
                    partial(
                        _object,
                        result.stdout,
                        resource,
                        target,
                        existing=True,
                        version=baseline.resource_version,
                    )
                )
                self._check(guard)
                return ManifestValidation(
                    MutationResult(
                        MutationState.SUCCEEDED,
                        "Server client-side apply preview passed; no write sent.",
                    ),
                    result.stdout,
                )
        finally:
            await self._remove_draft(draft)

    async def _remove_draft(self, draft: ManifestFile) -> None:
        try:
            await file_worker(draft.close)
        except OSError:
            raise AppError("Private manifest preview cleanup could not be confirmed.") from None
        self._drafts.discard(draft)

    async def _request(
        self,
        intent: ManifestRequest,
        guard: ManifestGuard,
        *,
        dry_run: bool,
    ) -> ManifestValidation:
        self._check(guard)
        if isinstance(intent, ManifestCreateIntent) and intent.policy == "create-only":
            verified = await parse_owned(
                partial(
                    create_manifest_intent,
                    intent.resource,
                    intent.target,
                    intent.body,
                    policy="create-only",
                )
            )
            self._check(guard)
            if verified.body != intent.body:
                raise AppError("Create-only request differs from its canonical reviewed input.")
        captured: list[bytes] = []
        created: list[CreatedResourceReceipt] = []

        def receipt(data: bytes) -> MutationResult | None:
            if isinstance(intent, ResourceIntent):
                value = decode_json(data)
                if value.get("kind") != "Status":
                    _object(
                        data,
                        intent.resource,
                        intent.target,
                        existing=True,
                        version=intent.resource_version if dry_run else None,
                    )
                result = operation_receipt(data, intent)
                if dry_run:
                    captured.append(data)
                    return None
                return result
            record = _object(
                data,
                intent.resource,
                intent.target,
                existing=not dry_run or isinstance(intent, MutationIntent),
                version=intent.resource_version
                if dry_run and isinstance(intent, MutationIntent)
                else None,
            )
            if dry_run:
                captured.append(data)
                return None
            if isinstance(intent, ManifestCreateIntent):
                assert record.uid is not None and record.resource_version is not None
                created.append(
                    CreatedResourceReceipt(
                        resource=intent.resource,
                        target=ResourceTarget(
                            intent.target.session,
                            intent.target.group,
                            intent.target.resource,
                            intent.target.namespace,
                            intent.target.name,
                            record.uid,
                        ),
                        resource_version=record.resource_version,
                    )
                )
                return MutationResult(
                    MutationState.SUCCEEDED,
                    f"Created {intent.target.resource}/{intent.target.name}; UID: {record.uid}. No retry was made.",
                )
            return None

        patch = isinstance(intent, MutationIntent)
        create = isinstance(intent, ManifestCreateIntent)
        if isinstance(intent, ResourceIntent) and intent.action is not ResourceAction.DELETE:
            raise AppError("Manifest operations admit only explicit deletion intents.")
        body = intent.body
        if dry_run and isinstance(intent, ResourceIntent):
            # Kubernetes decodes a nonempty DeleteOptions body instead of its
            # query options. Put the non-persistence directive in that body;
            # the immutable confirmed DELETE retains its original preconditions.
            body = await parse_owned(
                lambda: operation_json({**decode_json(intent.body), "dryRun": ["All"]})
            )
        result = await guarded_request(
            self.client,
            partial(self._check, guard),
            method="PATCH" if patch else "POST" if create else "DELETE",
            path=intent.path,
            body=body,
            content_type="application/json-patch+json" if patch else "application/json",
            accepted=(200,) if patch else (201,) if create else (200, 202),
            receipt=receipt,
            dry_run=dry_run,
            error_receipt=manifest_status,
        )
        return ManifestValidation(
            result, captured[0] if captured else None, created[0] if created else None
        )

    async def validate(self, intent: ManifestRequest, guard: ManifestGuard) -> ManifestValidation:
        return await self._owned(partial(self._request, intent, guard, dry_run=True))

    async def execute(self, intent: ManifestRequest, guard: ManifestGuard) -> MutationResult:
        return (await self._owned(partial(self._request, intent, guard, dry_run=False))).result

    async def execute_creation(
        self, intent: ManifestCreateIntent, guard: ManifestGuard
    ) -> ManifestCreationResult:
        if intent.policy != "create-only":
            raise AppError("Creation requires an exact create-only request.")
        response = await self._owned(partial(self._request, intent, guard, dry_run=False))
        return ManifestCreationResult(response.result, response.created)

    async def _close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        await self.runner.close()
        for draft in tuple(self._drafts):
            await self._remove_draft(draft)

    async def close(self) -> None:
        if self._closing is None or (
            self._closing.done()
            and not self._closing.cancelled()
            and self._closing.exception() is not None
        ):
            self._closing = asyncio.create_task(self._close())
        await finish_owned(self._closing)
