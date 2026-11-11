"""Finite live identity reads through the existing captured Kubernetes client."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import HttpProblem
from kuberich.domain.helm import HelmProblem, HelmReleaseKey, HelmRequest, helm_cell
from kuberich.domain.helm_lifecycle import helm_release_owns
from kuberich.domain.resources import ApiResource, api_segment
from kuberich.errors import AppError
from kuberich.services.resources import ResourceReader, parse_owned


def _identity(value: object) -> str:
    if not isinstance(value, str):
        raise AppError("Helm destination has no stable identity.")
    return helm_cell(value)


def _size(body: dict[str, Any]) -> int:
    return len(json.dumps(body, allow_nan=False).encode())


@dataclass(frozen=True, slots=True)
class HelmDestination:
    resource: ApiResource
    namespace: str | None
    name: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.resource.api_version}/{self.resource.kind}/{self.namespace or '(cluster)'}/{self.name}"


@dataclass(frozen=True, slots=True, repr=False)
class HelmLiveObject(HelmDestination):
    body: dict[str, Any] | None
    uid: str | None
    resource_version: str | None
    retained_bytes: int


async def namespace_identity(
    client: KubernetesSession, namespace: str, guard: Callable[[], None]
) -> str:
    guard()
    data = await client.get_json(
        "/api/v1/namespaces/" + api_segment(namespace), max_bytes=1024 * 1024
    )
    guard()
    meta, status = data.get("metadata"), data.get("status")
    if (
        data.get("apiVersion") != "v1"
        or data.get("kind") != "Namespace"
        or not isinstance(meta, dict)
        or meta.get("name") != namespace
        or meta.get("deletionTimestamp") is not None
        or not isinstance(status, dict)
        or status.get("phase") != "Active"
    ):
        raise AppError("Select an existing active namespace before preparing Helm changes.")
    return _identity(meta.get("uid"))


async def manifest_destinations(
    client: KubernetesSession,
    request: HelmRequest,
    documents: tuple[dict[str, Any], ...],
    guard: Callable[[], None],
    *,
    default_namespace: str | None = None,
) -> tuple[HelmDestination, ...]:
    guard()
    if len(documents) > 256:
        raise AppError("Helm live comparison exceeds its document limit.")
    if not documents:
        return ()
    discovery = await ResourceReader(client).discover()
    guard()
    result = []
    seen: set[str] = set()
    for document in documents:
        api, kind, meta = document.get("apiVersion"), document.get("kind"), document.get("metadata")
        matching = [
            resource
            for resource in discovery.resources
            if resource.api_version == api and resource.kind == kind
        ]
        if len(matching) != 1 or not isinstance(meta, dict):
            raise AppError("Helm destination type is not uniquely served by current discovery.")
        resource = matching[0]
        if "get" not in resource.verbs:
            raise AppError("Helm live comparison requires readable discovered destinations.")
        name = api_segment(meta.get("name"))
        declared_namespace = meta.get("namespace")
        namespace = None
        if resource.namespaced:
            if declared_namespace is None or declared_namespace == "":
                namespace = (
                    default_namespace if default_namespace is not None else request.scope.namespace
                )
            elif isinstance(declared_namespace, str):
                namespace = declared_namespace
            else:
                raise AppError("Helm destination namespace must be text, empty or null.")
        if resource.namespaced and not isinstance(namespace, str):
            raise AppError("Helm namespaced destinations need a concrete namespace.")
        if not resource.namespaced and declared_namespace is not None and declared_namespace != "":
            raise AppError("Cluster-scoped Helm destinations cannot contain a namespace.")
        path = resource.path(namespace) + "/" + name
        if path in seen:
            raise AppError("Helm rendered destinations are duplicate or ambiguous.")
        seen.add(path)
        result.append(HelmDestination(resource, namespace, name, path))
    return tuple(result)


async def live_objects(
    client: KubernetesSession,
    request: HelmRequest,
    documents: tuple[dict[str, Any], ...],
    guard: Callable[[], None],
    *,
    default_namespace: str | None = None,
    known: tuple[HelmLiveObject, ...] = (),
) -> tuple[HelmLiveObject, ...]:
    destinations = await manifest_destinations(
        client, request, documents, guard, default_namespace=default_namespace
    )
    result = []
    cached = {item.path: item for item in known}
    if len(set(cached) | {item.path for item in destinations}) > 256:
        raise AppError("Helm live comparison exceeds its combined document limit.")
    retained = sum(item.retained_bytes for item in known)
    for destination in destinations:
        resource, namespace, name, path = (
            destination.resource,
            destination.namespace,
            destination.name,
            destination.path,
        )
        if path in cached:
            result.append(cached[path])
            continue
        guard()
        try:
            body = await client.get_json(path, max_bytes=8 * 1024 * 1024 - retained)
        except HttpProblem as error:
            if error.status != 404:
                raise HelmProblem(
                    "forbidden" if error.status == 403 else "unavailable",
                    "Helm live destination could not be read; no complete review is available.",
                ) from None
            body = None
        guard()
        uid = version = None
        size = 0
        if body is not None:
            info = body.get("metadata")
            if (
                body.get("apiVersion") != resource.api_version
                or body.get("kind") != resource.kind
                or not isinstance(info, dict)
                or info.get("name") != name
                or info.get("namespace") != namespace
            ):
                raise AppError("Helm live destination response has a different identity.")
            uid, version = _identity(info.get("uid")), _identity(info.get("resourceVersion"))
            size = await parse_owned(partial(_size, body))
            retained += size
            if retained >= 8 * 1024 * 1024:
                raise AppError("Helm live comparison exceeds its combined byte budget.")
        result.append(HelmLiveObject(resource, namespace, name, path, body, uid, version, size))
    return tuple(result)


def require_release_ownership(live: HelmLiveObject, address: HelmReleaseKey) -> None:
    if live.body is None:
        return
    if not helm_release_owns(live.body, address):
        raise AppError("A live Helm destination has different or unverifiable release ownership.")
