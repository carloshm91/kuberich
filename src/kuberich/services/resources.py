"""Bounded API discovery and atomic, version-consistent collection reads."""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.resources import (
    MAX_RESOURCE_BYTES,
    MAX_RESOURCE_ITEMS,
    ApiResource,
    Discovery,
    DiscoveryIssue,
    ResourceSnapshot,
    api_resource,
    api_segment,
    resource_object,
    resource_record,
    resource_text,
    split_api_version,
)
from kuberich.errors import AppError

DISCOVERY_ACCEPT = (
    "application/json;g=apidiscovery.k8s.io;v=v2;as=APIGroupDiscoveryList,application/json"
)
MAX_VERSIONS = 128
MAX_RESOURCES = 8192
MAX_ITEMS = MAX_RESOURCE_ITEMS
MAX_PAGES = 256
MAX_SNAPSHOT_BYTES = MAX_RESOURCE_BYTES


def _entries(value: Any, limit: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise AppError("Invalid or excessive API discovery entries.")
    return value


def _descriptors(version: str, values: Any, *, aggregated: bool = False) -> tuple[ApiResource, ...]:
    resources = []
    seen: set[str] = set()
    for value in _entries(values, MAX_RESOURCES):
        data = resource_object(value)
        name = resource_text(data.get("resource" if aggregated else "name"))
        if "/" in name:
            parts = name.split("/")
            if len(parts) != 2:
                raise AppError("Invalid discovered subresource.")
            for part in parts:
                api_segment(part)
            continue
        resource = api_resource(version, data, aggregated=aggregated)
        if resource.name in seen:
            raise AppError("Duplicate discovered resource.")
        seen.add(resource.name)
        resources.append(resource)
    return tuple(resources)


@dataclass
class _Root:
    versions: list[str] = field(default_factory=list)
    resources: dict[str, tuple[ApiResource, ...]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    def add(self, version: str) -> None:
        split_api_version(version)
        if version in self.versions or len(self.versions) >= MAX_VERSIONS:
            raise AppError("Duplicate or excessive API versions.")
        self.versions.append(version)


def _root(path: str, payload: dict[str, Any]) -> _Root:
    result = _Root()
    if payload.get("kind") == "APIGroupDiscoveryList":
        if payload.get("apiVersion") != "apidiscovery.k8s.io/v2":
            raise AppError("Unsupported aggregated discovery version.")
        count = 0
        for value in _entries(payload.get("items"), MAX_VERSIONS):
            group = resource_object(value)
            # The core group has an empty name, which Kubernetes omits in JSON.
            name = resource_object(group.get("metadata")).get("name", "")
            if path == "/api":
                if name != "":
                    raise AppError("Core discovery contains a named API group.")
            else:
                name = api_segment(name)
            for entry in _entries(group.get("versions"), MAX_VERSIONS):
                data = resource_object(entry)
                version = api_segment(data.get("version"))
                gv = f"{name}/{version}" if name else version
                result.add(gv)
                freshness = data.get("freshness")
                if freshness == "Current":
                    resources = _descriptors(gv, data.get("resources"), aggregated=True)
                    count += len(resources)
                    if count > MAX_RESOURCES:
                        raise AppError("Discovery exceeds its resource limit.")
                    result.resources[gv] = resources
                elif freshness == "Stale":
                    result.requests.append(gv)
                else:
                    raise AppError("Invalid discovery freshness.")
    elif path == "/api":
        if payload.get("kind") != "APIVersions":
            raise AppError("Invalid core API discovery.")
        for version in _entries(payload.get("versions"), MAX_VERSIONS):
            result.add(api_segment(version))
        result.requests.extend(result.versions)
    else:
        if payload.get("kind") != "APIGroupList":
            raise AppError("Invalid API group discovery.")
        groups: set[str] = set()
        for entry in _entries(payload.get("groups"), MAX_VERSIONS):
            group = resource_object(entry)
            name = api_segment(group.get("name"))
            if name in groups:
                raise AppError("Duplicate API group.")
            groups.add(name)
            versions = []
            for value in _entries(group.get("versions"), MAX_VERSIONS):
                data = resource_object(value)
                version = api_segment(data.get("version"))
                gv = f"{name}/{version}"
                if data.get("groupVersion") != gv:
                    raise AppError("API group/version does not match its directory.")
                versions.append(gv)
            preferred = group.get("preferredVersion")
            if preferred:
                gv = resource_text(resource_object(preferred).get("groupVersion"))
                if gv not in versions:
                    raise AppError("Preferred API version is not advertised.")
                versions.remove(gv)
                versions.insert(0, gv)
            for gv in versions:
                result.add(gv)
                result.requests.append(gv)
    return result


def _issue(source: str, problem: ConnectionProblem) -> DiscoveryIssue:
    if isinstance(problem, HttpProblem):
        if problem.status == 401:
            raise problem
        return DiscoveryIssue(
            source, "forbidden" if problem.status == 403 else "unavailable", problem.status
        )
    if problem.state is not ConnectionState.API_ERROR:
        raise problem
    return DiscoveryIssue(source, "invalid")


class ResourceReader:
    """Uses one existing session; never loads credentials or selects a fallback."""

    def __init__(self, session: KubernetesSession) -> None:
        self.session = session

    async def _read(
        self, path: str, *, aggregate: bool = False
    ) -> dict[str, Any] | ConnectionProblem:
        try:
            return await self.session.get_json(
                path,
                max_bytes=2 * 1024 * 1024,
                accept=DISCOVERY_ACCEPT if aggregate else "application/json",
            )
        except ConnectionProblem as problem:
            return problem

    async def discover(self) -> Discovery:
        try:
            async with asyncio.timeout(self.session.timeout):
                async with asyncio.TaskGroup() as group:
                    core = group.create_task(self._read("/api", aggregate=True))
                    apis = group.create_task(self._read("/apis", aggregate=True))
                roots = []
                issues = []
                for path, task in (("/api", core), ("/apis", apis)):
                    value = task.result()
                    if isinstance(value, ConnectionProblem):
                        issues.append(_issue(path, value))
                        continue
                    try:
                        roots.append(_root(path, value))
                    except AppError:
                        issues.append(DiscoveryIssue(path, "invalid"))
                versions = [gv for root in roots for gv in root.versions]
                if len(versions) > MAX_VERSIONS or len(set(versions)) != len(versions):
                    raise AppError("Duplicate or excessive combined discovery versions.")
                resources = {gv: items for root in roots for gv, items in root.resources.items()}
                requests = [gv for root in roots for gv in root.requests]
                for offset in range(0, len(requests), 4):
                    batch = requests[offset : offset + 4]
                    async with asyncio.TaskGroup() as group:
                        tasks = [
                            group.create_task(self._read(("/apis/" if "/" in gv else "/api/") + gv))
                            for gv in batch
                        ]
                    for gv, task in zip(batch, tasks, strict=True):
                        value = task.result()
                        if isinstance(value, ConnectionProblem):
                            issues.append(_issue(gv, value))
                            continue
                        try:
                            if value.get("groupVersion") != gv:
                                raise AppError("Discovery version does not match its endpoint.")
                            resources[gv] = _descriptors(gv, value.get("resources"))
                        except AppError:
                            issues.append(DiscoveryIssue(gv, "invalid"))
                    if sum(len(items) for items in resources.values()) > MAX_RESOURCES:
                        raise AppError("Discovery exceeds its combined resource limit.")
                items = tuple(resource for gv in versions for resource in resources.get(gv, ()))
                if len(items) > MAX_RESOURCES:
                    raise AppError("Discovery exceeds its combined resource limit.")
                return Discovery(items, tuple(issues))
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT, "API discovery timed out; check --request-timeout."
            ) from None
        except AppError:
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid or excessive combined API discovery."
            ) from None

    async def list(
        self, resource: ApiResource, namespace: str | None = None, *, page_size: int = 100
    ) -> ResourceSnapshot:
        if "list" not in resource.verbs:
            raise AppError("This discovered resource does not advertise list support.")
        if type(page_size) is not int or not 1 <= page_size <= 500:
            raise AppError("Resource page size must be an integer from 1 through 500.")
        path = resource.path(namespace)
        try:
            async with asyncio.timeout(self.session.timeout):
                # An expired continuation restarts the whole collection once;
                # never mix old pages with the server's replacement token.
                restarted = False
                while True:
                    records = []
                    identities: set[tuple[str | None, str]] = set()
                    uids: set[str] = set()
                    tokens: set[str] = set()
                    token = ""
                    snapshot_version = None
                    total_bytes = 0
                    for page in range(MAX_PAGES):
                        try:
                            payload = await self.session.get_json(
                                path, params={"limit": str(page_size), "continue": token}
                            )
                        except HttpProblem as problem:
                            if problem.status == 410 and not restarted:
                                restarted = True
                                break
                            raise
                        if payload.get("apiVersion", resource.api_version) != resource.api_version:
                            raise AppError("Collection API version does not match discovery.")
                        metadata = resource_object(payload.get("metadata"))
                        rv = metadata.get("resourceVersion")
                        if rv is not None:
                            rv = resource_text(rv)
                        elif "watch" in resource.verbs:
                            raise AppError("A watchable collection has no resourceVersion.")
                        if page == 0:
                            snapshot_version = rv
                        elif rv != snapshot_version:
                            raise AppError("Collection resourceVersion changed between pages.")
                        values = payload.get("items")
                        if not isinstance(values, list) or len(values) > MAX_ITEMS:
                            raise AppError("Invalid or excessive resource collection.")
                        for value in values:
                            record = resource_record(resource, value, namespace)
                            identity = record.namespace, record.name
                            if (
                                record.uid is not None and record.uid in uids
                            ) or identity in identities:
                                raise AppError("Duplicate item in collection snapshot.")
                            if record.uid is not None:
                                uids.add(record.uid)
                            identities.add(identity)
                            total_bytes += record.size_bytes
                            records.append(record)
                        if len(records) > MAX_ITEMS or total_bytes > MAX_SNAPSHOT_BYTES:
                            raise AppError("Resource snapshot exceeds its item/memory limit.")
                        token = metadata.get("continue", "")
                        if not isinstance(token, str):
                            raise AppError("Invalid continuation token.")
                        if not token:
                            return ResourceSnapshot(
                                resource, namespace, snapshot_version, tuple(records)
                            )
                        resource_text(token)
                        if token in tokens:
                            raise AppError("Repeated continuation token.")
                        tokens.add(token)
                    else:
                        raise AppError("Resource snapshot exceeds its page limit.")
        except TimeoutError:
            raise ConnectionProblem(
                ConnectionState.TIMEOUT, "Resource listing timed out; check --request-timeout."
            ) from None
        except AppError:
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid or excessive resource collection snapshot."
            ) from None
