"""Discovered endpoints and immutable resource snapshots, without SDK or UI types."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kuberich.domain.connections import namespace_name
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_RESOURCE_ITEMS = 10000
MAX_RESOURCE_BYTES = 64 * 1024 * 1024


def resource_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AppError("Invalid Kubernetes resource mapping.")
    return value


def resource_text(value: Any) -> str:
    if not isinstance(value, str):
        raise AppError("Invalid Kubernetes resource text.")
    return validate_argument(value)


def api_segment(value: Any) -> str:
    result = resource_text(value)
    if len(result) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", result):
        raise AppError("Invalid API endpoint segment.")
    return result


def split_api_version(value: Any) -> tuple[str, str]:
    parts = resource_text(value).split("/")
    if len(parts) == 1:
        return "", api_segment(parts[0])
    if len(parts) != 2:
        raise AppError("Invalid API group/version.")
    return api_segment(parts[0]), api_segment(parts[1])


def string_list(value: Any, *, limit: int = 64) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > limit:
        raise AppError("Invalid or excessive Kubernetes string list.")
    return tuple(resource_text(item) for item in value)


@dataclass(frozen=True)
class ApiResource:
    group: str
    version: str
    name: str
    kind: str
    namespaced: bool
    verbs: frozenset[str]
    aliases: tuple[str, ...] = ()

    @property
    def api_version(self) -> str:
        return f"{self.group}/{self.version}" if self.group else self.version

    def path(self, namespace: str | None = None) -> str:
        prefix = f"/apis/{self.api_version}" if self.group else f"/api/{self.version}"
        if namespace is not None:
            if not self.namespaced:
                raise AppError("A cluster-scoped resource cannot use a namespace.")
            prefix += "/namespaces/" + namespace_name(namespace)
        return prefix + "/" + self.name


def api_resource(group_version: str, value: Any, *, aggregated: bool = False) -> ApiResource:
    group, version = split_api_version(group_version)
    data = resource_object(value)
    name = api_segment(data.get("resource" if aggregated else "name"))
    if aggregated:
        scope = data.get("scope")
        if scope not in ("Namespaced", "Cluster"):
            raise AppError("Invalid discovered resource scope.")
        namespaced = scope == "Namespaced"
        kind = resource_text(resource_object(data.get("responseKind")).get("kind"))
        singular = data.get("singularResource", "")
    else:
        namespaced = data.get("namespaced")
        if type(namespaced) is not bool:
            raise AppError("Invalid discovered resource scope.")
        kind = resource_text(data.get("kind"))
        singular = data.get("singularName", "")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind):
        raise AppError("Invalid discovered resource kind.")
    verbs = string_list(data.get("verbs"))
    if any(not re.fullmatch(r"[a-z]+", verb) for verb in verbs):
        raise AppError("Invalid discovered resource verb.")
    aliases = tuple(api_segment(alias) for alias in string_list(data.get("shortNames")))
    if singular != "":
        aliases = (api_segment(singular), *aliases)
    return ApiResource(group, version, name, kind, namespaced, frozenset(verbs), aliases)


@dataclass(frozen=True)
class DiscoveryIssue:
    source: str
    reason: str
    status: int | None = None


@dataclass(frozen=True, repr=False)
class Discovery:
    resources: tuple[ApiResource, ...]
    issues: tuple[DiscoveryIssue, ...] = ()

    @property
    def partial(self) -> bool:
        return bool(self.issues)

    def find(self, name: str, *, group: str = "", version: str | None = None) -> ApiResource:
        validate_argument(name)
        matching = tuple(
            resource
            for resource in self.resources
            if resource.group == group and (version is None or resource.version == version)
        )
        canonical = tuple(resource for resource in matching if resource.name == name)
        if canonical:
            return canonical[0]
        aliases = tuple(resource for resource in matching if name in resource.aliases)
        if len({resource.name for resource in aliases}) > 1:
            raise AppError("Resource alias is ambiguous; use its canonical name.")
        if aliases:
            return aliases[0]
        raise AppError("Resource/version was not discovered. Check discovery and permissions.")


@dataclass(frozen=True, repr=False)
class ResourceRecord:
    name: str
    uid: str | None
    namespace: str | None
    resource_version: str | None
    created_at: datetime | None
    _manifest: bytes = field(repr=False)

    @property
    def manifest(self) -> dict[str, Any]:
        """Return an independent manifest; callers cannot mutate the snapshot."""
        return resource_object(json.loads(self._manifest))

    @property
    def size_bytes(self) -> int:
        return len(self._manifest)


def resource_record(
    resource: ApiResource, value: Any, namespace: str | None = None
) -> ResourceRecord:
    data = resource_object(value)
    if (
        data.get("apiVersion", resource.api_version) != resource.api_version
        or data.get("kind", resource.kind) != resource.kind
    ):
        raise AppError("Resource item does not match the discovered type.")
    metadata = resource_object(data.get("metadata"))
    name = resource_text(metadata.get("name"))
    uid = metadata.get("uid")
    if uid is not None:
        uid = resource_text(uid)
    elif "watch" in resource.verbs:
        raise AppError("A watchable resource item has no UID.")
    if name in {".", ".."} or "/" in name or "%" in name:
        raise AppError("Invalid resource name.")
    scope = metadata.get("namespace")
    if resource.namespaced:
        scope = namespace_name(resource_text(scope))
        if namespace is not None and scope != namespace:
            raise AppError("Resource item belongs to another namespace.")
    elif scope is not None and scope != "":
        raise AppError("A cluster-scoped item contains a namespace.")
    else:
        scope = None
    rv = metadata.get("resourceVersion")
    if rv is not None:
        rv = resource_text(rv)
    elif "watch" in resource.verbs:
        raise AppError("A watchable resource item has no resourceVersion.")
    timestamp = metadata.get("creationTimestamp")
    created = None
    try:
        if timestamp is not None:
            created = datetime.fromisoformat(resource_text(timestamp).replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise AppError("Resource creationTimestamp must have a timezone.")
        manifest = json.dumps(
            {"apiVersion": resource.api_version, "kind": resource.kind, **data},
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise AppError("Invalid resource timestamp or manifest.") from None
    return ResourceRecord(name, uid, scope, rv, created, manifest)


@dataclass(frozen=True, repr=False)
class ResourceSnapshot:
    resource: ApiResource
    namespace: str | None
    resource_version: str | None
    items: tuple[ResourceRecord, ...]
