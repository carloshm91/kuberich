"""Bounded Helm CLI reads and metadata-only Kubernetes release identities."""

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.helm import (
    MAX_HELM_LIST_BYTES,
    MAX_HELM_OUTPUT_BYTES,
    HelmDocumentKind,
    HelmHistory,
    HelmList,
    HelmProblem,
    HelmProblemKind,
    HelmReleaseKey,
    HelmRequest,
    HelmRollbackIntent,
    HelmSettings,
    HelmStatus,
    HelmStorageIdentity,
    HelmVersion,
    helm_positive,
)
from kuberich.domain.helm_cli import (
    helm_document_argv,
    helm_environment,
    helm_history_argv,
    helm_list_argv,
    helm_rollback_argv,
    helm_status_argv,
    helm_version_argv,
    parse_helm_history,
    parse_helm_list,
    parse_helm_status,
    parse_helm_version,
    parse_storage_identity,
)
from kuberich.domain.helm_documents import helm_document_text
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, ProcessStatus
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import parse_owned

type HelmGuard = Callable[[], None]
METADATA_ACCEPT = "application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1"
METADATA_LIST_ACCEPT = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"
MAX_STORAGE_BYTES = 4 * 1024 * 1024
MAX_STORAGE_PAGES = 10
MAX_STORAGE_IDENTITIES = 2000


class HelmExecutionProblem(HelmProblem):
    """A safe write error with process evidence, never raw CLI output."""

    def __init__(
        self, kind: HelmProblemKind, message: str, *, may_have_started: bool, completed: bool
    ) -> None:
        super().__init__(kind, message)
        self.may_have_started, self.completed = may_have_started, completed


class HelmExecutionCancelled(asyncio.CancelledError):
    """Preserve cancellation while recording whether the write boundary was reached."""

    def __init__(self, may_have_started: bool) -> None:
        super().__init__()
        self.may_have_started = may_have_started


@dataclass(slots=True)
class _RunState:
    may_have_started: bool = False
    completed: bool = False


class HelmAdapterPort(Protocol):
    """Only typed, bounded observations leave the transport owner."""

    async def list(self, request: HelmRequest, guard: HelmGuard) -> HelmList: ...
    async def status(
        self, request: HelmRequest, key: HelmReleaseKey, revision: int, guard: HelmGuard
    ) -> HelmStatus: ...
    async def history(
        self, request: HelmRequest, key: HelmReleaseKey, guard: HelmGuard
    ) -> HelmHistory: ...
    async def document(
        self,
        request: HelmRequest,
        key: HelmReleaseKey,
        revision: int,
        kind: HelmDocumentKind,
        disclosed: bool,
        guard: HelmGuard,
    ) -> str: ...
    async def storage_identity(
        self, request: HelmRequest, key: HelmReleaseKey, revision: int, guard: HelmGuard
    ) -> HelmStorageIdentity: ...
    async def storage_history(
        self, request: HelmRequest, key: HelmReleaseKey, guard: HelmGuard
    ) -> tuple[HelmStorageIdentity, ...]: ...
    async def rollback(self, intent: HelmRollbackIntent, guard: HelmGuard) -> None: ...
    async def close(self) -> None: ...


def _failure(status: ProcessStatus, stderr: bytes) -> HelmProblem:
    if status is ProcessStatus.OUTPUT_LIMIT:
        return HelmProblem("output-limit", "Helm output exceeded its limit; narrow the scope.")
    if status is ProcessStatus.TIMED_OUT:
        return HelmProblem("timeout", "Helm command timed out; refresh before retrying.")
    # Recognize narrow machine-independent markers; never retain or echo tool output.
    text = stderr[:65536].lower()
    if b"forbidden" in text or b"cannot list resource" in text:
        return HelmProblem(
            "forbidden", "Helm access was forbidden; check release storage permissions."
        )
    if any(
        marker in text
        for marker in (b"unauthorized", b"authentication required", b"provide credentials")
    ):
        return HelmProblem(
            "authentication", "Helm authentication failed; complete provider login separately."
        )
    if b"release: not found" in text or b"release not found" in text:
        return HelmProblem("missing-release", "Helm release was not found; refresh the list.")
    return HelmProblem(
        "unavailable", "Helm command failed; refresh and check the selected connection."
    )


def _api_problem(problem: ConnectionProblem) -> HelmProblem:
    if isinstance(problem, HttpProblem):
        if problem.status == 403:
            return HelmProblem(
                "forbidden",
                "Helm storage metadata access was forbidden; identity-sensitive operations are disabled.",
            )
        if problem.status == 401:
            return HelmProblem(
                "authentication",
                "Release storage authentication failed; complete provider login separately.",
            )
        if problem.status == 404:
            return HelmProblem(
                "missing-release", "Helm storage identity disappeared; refresh the release."
            )
        if problem.status == 406:
            return HelmProblem(
                "unavailable",
                "The API does not support metadata-only release reads; identity-sensitive operations are disabled.",
            )
    if problem.state is ConnectionState.TIMEOUT:
        return HelmProblem("timeout", "Helm storage metadata read timed out; refresh the release.")
    return HelmProblem("unavailable", "Helm storage metadata read failed; refresh the release.")


def _storage_path(request: HelmRequest, key: HelmReleaseKey) -> str:
    if request.scope.namespace not in {None, key.namespace}:
        raise HelmProblem("stale", "Helm release does not belong to the captured namespace.")
    plural = "secrets" if request.scope.driver.value == "secret" else "configmaps"
    return f"/api/v1/namespaces/{quote(key.namespace, safe='')}/{plural}"


def _storage_page(
    data: Mapping[str, object], request: HelmRequest, key: HelmReleaseKey
) -> tuple[tuple[HelmStorageIdentity, ...], str, str, int]:
    invalid = HelmProblem("invalid-output", "Invalid Helm storage metadata; refresh the release.")
    if (
        data.get("apiVersion") != "meta.k8s.io/v1"
        or data.get("kind") != "PartialObjectMetadataList"
    ):
        raise HelmProblem(
            "unavailable",
            "The API did not return metadata-only release storage; identity-sensitive operations are disabled.",
        )
    metadata, items = data.get("metadata"), data.get("items")
    if not isinstance(metadata, dict) or not isinstance(items, list) or len(items) > 200:
        raise invalid
    resource_version, continuation = metadata.get("resourceVersion"), metadata.get("continue", "")
    if (
        not isinstance(resource_version, str)
        or not resource_version
        or len(resource_version) > 1024
    ):
        raise invalid
    if not isinstance(continuation, str) or len(continuation) > 8192:
        raise invalid
    remaining = metadata.get("remainingItemCount", 0)
    if type(remaining) is not int or remaining < 0 or (remaining > 0 and not continuation):
        raise invalid
    identities = []
    for item in items:
        if not isinstance(item, dict):
            raise invalid
        meta = item.get("metadata")
        labels = meta.get("labels") if isinstance(meta, dict) else None
        value = labels.get("version") if isinstance(labels, dict) else None
        if (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or len(value) > 10
        ):
            raise invalid
        identities.append(parse_storage_identity(item, key, request.scope.driver, int(value)))
    try:
        size = len(
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        )
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise invalid from None
    return tuple(identities), resource_version, continuation, size


class HelmAdapter:
    """Own processes and private delegated files without changing ambient state."""

    def __init__(
        self,
        client: KubernetesSession,
        policy: AccessPolicy,
        settings: HelmSettings,
        environment: Mapping[str, str],
        directory: Path,
    ) -> None:
        self.client, self.policy, self.settings = client, policy, settings
        self.environment = dict(environment)
        self.directory = directory.absolute()
        self._version: HelmVersion | None = None
        self._probe_lock = asyncio.Lock()
        self._runners = {
            limit: ProcessRunner(policy, output_limit=limit)
            for limit in (16384, MAX_HELM_LIST_BYTES, MAX_HELM_OUTPUT_BYTES)
        }
        self._closed = False

    def _check(self, request: HelmRequest | None, guard: HelmGuard, mutate: bool = False) -> None:
        self.policy.require(Action.MUTATE if mutate else Action.READ)
        guard()
        if self._closed:
            raise HelmProblem("stale", "Helm connection is closed; reopen the Helm view.")
        if request is not None and request.scope.driver is not self.settings.driver:
            raise HelmProblem(
                "unsupported-driver",
                "Helm request storage driver differs from the captured settings.",
            )

    async def version(self, guard: HelmGuard) -> HelmVersion:
        self._check(None, guard)
        async with self._probe_lock:
            self._check(None, guard)
            if self._version is None:
                command = ProcessCommand(
                    helm_version_argv(self.settings),
                    helm_environment(self.environment, self.settings.driver),
                    self.directory,
                    ProcessMode.CAPTURE,
                    ProcessPurpose.HELM_READ,
                )
                try:
                    result = await self._runners[16384].capture(command, timeout=5, guard=guard)
                except ExecutableUnavailable:
                    raise HelmProblem(
                        "missing-tool",
                        "Helm is unavailable; install supported Helm v3.22.1 or v4.3.1 and reopen this view.",
                    ) from None
                self._check(None, guard)
                if result.status is not ProcessStatus.SUCCEEDED:
                    raise _failure(result.status, result.stderr)
                self._version = await parse_owned(partial(parse_helm_version, result.stdout))
                self._check(None, guard)
            return self._version

    async def _run[T](
        self,
        request: HelmRequest,
        guard: HelmGuard,
        argv: Callable[[HelmVersion, Path], tuple[str, ...]],
        parser: Callable[[bytes], T],
        *,
        limit: int = MAX_HELM_OUTPUT_BYTES,
        timeout: float = 30,
        mutate: bool = False,
        state: _RunState | None = None,
    ) -> T:
        self._check(request, guard, mutate)
        version = await self.version(guard)
        self._check(request, guard, mutate)
        delegation = capture_delegation(
            self.client, self.environment, self.directory, prefix="helm"
        )
        async with stage_connection(delegation.path, delegation.configuration):
            self._check(request, guard, mutate)
            command = ProcessCommand(
                argv(version, delegation.path),
                helm_environment(
                    dict(delegation.environment), self.settings.driver, delegation.path
                ),
                delegation.directory,
                ProcessMode.CAPTURE,
                ProcessPurpose.HELM_MUTATE if mutate else ProcessPurpose.HELM_READ,
            )
            try:
                if state is not None:
                    state.may_have_started = True
                result = await self._runners[limit].capture(command, timeout=timeout, guard=guard)
            except ExecutableUnavailable:
                if state is not None:
                    state.may_have_started = False
                raise HelmProblem(
                    "missing-tool",
                    "Helm is unavailable; install supported Helm v3.22.1 or v4.3.1 and reopen this view.",
                ) from None
            if state is not None:
                state.completed = result.status in {ProcessStatus.SUCCEEDED, ProcessStatus.FAILED}
            self._check(request, guard, mutate)
            if result.status is not ProcessStatus.SUCCEEDED:
                raise _failure(result.status, result.stderr)
            parsed = await parse_owned(partial(parser, result.stdout))
            self._check(request, guard, mutate)
            return parsed

    async def list(self, request: HelmRequest, guard: HelmGuard) -> HelmList:
        return await self._run(
            request,
            guard,
            lambda version, path: helm_list_argv(self.settings, version, request.scope, path),
            partial(parse_helm_list, scope=request.scope),
            limit=MAX_HELM_LIST_BYTES,
        )

    async def status(
        self, request: HelmRequest, key: HelmReleaseKey, revision: int, guard: HelmGuard
    ) -> HelmStatus:
        return await self._run(
            request,
            guard,
            lambda version, path: helm_status_argv(
                self.settings, version, request.scope, path, key, revision
            ),
            partial(parse_helm_status, key=key, revision=revision),
        )

    async def history(
        self, request: HelmRequest, key: HelmReleaseKey, guard: HelmGuard
    ) -> HelmHistory:
        return await self._run(
            request,
            guard,
            lambda version, path: helm_history_argv(
                self.settings, version, request.scope, path, key
            ),
            parse_helm_history,
            limit=MAX_HELM_LIST_BYTES,
        )

    async def document(
        self,
        request: HelmRequest,
        key: HelmReleaseKey,
        revision: int,
        kind: HelmDocumentKind,
        disclosed: bool,
        guard: HelmGuard,
    ) -> str:
        return await self._run(
            request,
            guard,
            lambda version, path: helm_document_argv(
                self.settings, version, request.scope, path, key, revision, kind
            ),
            partial(helm_document_text, kind=kind, disclosed=disclosed),
        )

    async def storage_identity(
        self, request: HelmRequest, key: HelmReleaseKey, revision: int, guard: HelmGuard
    ) -> HelmStorageIdentity:
        self._check(request, guard)
        helm_positive(revision)
        path = (
            _storage_path(request, key)
            + "/"
            + quote(f"sh.helm.release.v1.{key.name}.v{revision}", safe="")
        )
        try:
            data = await self.client.get_json(
                path, max_bytes=MAX_STORAGE_BYTES, accept=METADATA_ACCEPT
            )
        except ConnectionProblem as problem:
            raise _api_problem(problem) from None
        self._check(request, guard)
        result = await parse_owned(
            partial(parse_storage_identity, data, key, request.scope.driver, revision)
        )
        self._check(request, guard)
        return result

    async def storage_history(
        self, request: HelmRequest, key: HelmReleaseKey, guard: HelmGuard
    ) -> tuple[HelmStorageIdentity, ...]:
        self._check(request, guard)
        path = _storage_path(request, key)
        params = {"labelSelector": f"owner=helm,name={key.name}", "limit": "200"}
        retained = 0
        identities: list[HelmStorageIdentity] = []
        seen: set[tuple[str, str]] = set()
        continuations: set[str] = set()
        collection_version: str | None = None
        for _ in range(MAX_STORAGE_PAGES):
            self._check(request, guard)
            try:
                data = await self.client.get_json(
                    path,
                    params=params,
                    max_bytes=MAX_STORAGE_BYTES - retained,
                    accept=METADATA_LIST_ACCEPT,
                )
            except ConnectionProblem as problem:
                raise _api_problem(problem) from None
            self._check(request, guard)
            page, version, continuation, size = await parse_owned(
                partial(_storage_page, data, request, key)
            )
            self._check(request, guard)
            retained += size
            if retained > MAX_STORAGE_BYTES or len(identities) + len(page) > MAX_STORAGE_IDENTITIES:
                raise HelmProblem(
                    "output-limit",
                    "Helm storage metadata limit reached; identity-sensitive operations are disabled.",
                )
            if collection_version is not None and version != collection_version:
                raise HelmProblem("stale", "Helm storage pagination changed; refresh the release.")
            collection_version = version
            for identity in page:
                marker = (identity.storage_name, identity.uid)
                if marker in seen or any(item.revision == identity.revision for item in identities):
                    raise HelmProblem(
                        "invalid-output", "Duplicate Helm storage identities; refresh the release."
                    )
                seen.add(marker)
                identities.append(identity)
            if not continuation:
                return tuple(sorted(identities, key=lambda item: item.revision))
            if continuation in continuations or retained >= MAX_STORAGE_BYTES:
                raise HelmProblem(
                    "output-limit",
                    "Helm storage pagination did not complete; identity-sensitive operations are disabled.",
                )
            continuations.add(continuation)
            params = {**params, "continue": continuation}
        raise HelmProblem(
            "output-limit",
            "Helm storage pagination limit reached; identity-sensitive operations are disabled.",
        )

    async def rollback(self, intent: HelmRollbackIntent, guard: HelmGuard) -> None:
        state = _RunState()
        try:
            await self._run(
                intent.target.request,
                guard,
                lambda version, path: helm_rollback_argv(self.settings, version, path, intent),
                lambda _: None,
                timeout=min(1800, 3 * intent.options.timeout_seconds + 30),
                mutate=True,
                state=state,
            )
        except asyncio.CancelledError:
            raise HelmExecutionCancelled(state.may_have_started) from None
        except HelmProblem as problem:
            raise HelmExecutionProblem(
                problem.kind,
                str(problem),
                may_have_started=state.may_have_started,
                completed=state.completed,
            ) from None
        except AppError:
            raise HelmExecutionProblem(
                "unavailable",
                "Helm rollback could not complete; refresh before another review.",
                may_have_started=state.may_have_started,
                completed=state.completed,
            ) from None

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(*(runner.close() for runner in self._runners.values()))
