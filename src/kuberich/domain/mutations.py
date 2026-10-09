"""Immutable conditional JSON patches and public write outcomes, independent of UI."""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NoReturn
from uuid import UUID, uuid4

from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_PATCH_BYTES = 1024 * 1024


def _nonfinite(value: str) -> NoReturn:
    raise ValueError("Nonfinite JSON is invalid.")


def decode_patch(body: bytes) -> list[dict[str, Any]]:
    if not isinstance(body, bytes) or not 1 <= len(body) <= MAX_PATCH_BYTES:
        raise AppError("Mutation JSON must be immutable and bounded to 1 MiB.")
    try:
        data = json.loads(body, parse_constant=_nonfinite)
        if not isinstance(data, list) or not 3 <= len(data) <= 130:
            raise ValueError
        json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return [resource_object(item) for item in data]
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Mutation JSON must contain bounded patch operations.") from None


def mutation_path(
    resource: ApiResource, target: ResourceTarget, subresource: str | None = None
) -> str:
    if resource.group:
        api_segment(resource.group)
    api_segment(resource.version)
    api_segment(resource.name)
    if (
        target.group != resource.group
        or target.resource != resource.name
        or target.container is not None
        or type(resource.namespaced) is not bool
        or resource.namespaced != (target.namespace is not None)
        or "get" not in resource.verbs
        or (subresource is None and "patch" not in resource.verbs)
    ):
        raise AppError("Mutation requires an explicitly scoped, readable and patchable target.")
    path = resource.path(target.namespace) + "/" + api_segment(target.name)
    if subresource is not None:
        if (
            subresource != "scale"
            or resource.group != "apps"
            or resource.name not in {"deployments", "replicasets", "statefulsets"}
        ):
            raise AppError("Only the supported workload scale subresource is allowed.")
        path += "/scale"
    return path


def _change_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 1024:
        raise AppError("Patch paths must be bounded JSON pointers.")
    validate_argument(value)
    if re.search(r"~(?![01])", value):
        raise AppError("Invalid JSON pointer escape.")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in value[1:].split("/")]
    if parts[0] in {"apiVersion", "kind", "status"} or (
        parts[0] == "metadata"
        and (
            len(parts) < 2
            or parts[1] not in {"annotations", "labels", "finalizers", "ownerReferences"}
        )
    ):
        raise AppError("Patch cannot replace resource identity, managed metadata or status.")
    return value


@dataclass(frozen=True, repr=False)
class MutationIntent:
    target: ResourceTarget
    resource: ApiResource
    resource_version: str
    body: bytes = field(repr=False)
    identity: UUID = field(default_factory=uuid4)
    subresource: str | None = None

    def __post_init__(self) -> None:
        mutation_path(self.resource, self.target, self.subresource)
        validate_argument(self.resource_version)
        if len(self.resource_version) > 1024 or not isinstance(self.identity, UUID):
            raise AppError("Mutation version/identity is invalid.")
        operations = decode_patch(self.body)
        expected = [
            {"op": "test", "path": "/metadata/uid", "value": self.target.uid},
            {"op": "test", "path": "/metadata/resourceVersion", "value": self.resource_version},
        ]
        if operations[:2] != expected:
            raise AppError("Mutation requires server-side UID and version tests first.")
        for item in operations[2:]:
            if self.subresource is not None and (
                len(operations) != 3
                or item.get("path") != "/spec/replicas"
                or item.get("op") not in {"add", "replace"}
                or type(item.get("value")) is not int
                or not 0 <= item["value"] <= 2147483647
            ):
                raise AppError("Scale can change only a validated replica count.")
            operation = item.get("op")
            if operation not in {"add", "replace", "remove"}:
                raise AppError("Unsupported mutation patch operation.")
            _change_path(item.get("path"))
            fields = {"op", "path"} if operation == "remove" else {"op", "path", "value"}
            if set(item) != fields:
                raise AppError("Patch operation has missing or unexpected fields.")

    @property
    def path(self) -> str:
        return mutation_path(self.resource, self.target, self.subresource)

    @property
    def effects(self) -> tuple[str, ...]:
        # Values/manifests never enter public status or history.
        return tuple(f"{item['op']} {item['path']}" for item in decode_patch(self.body)[2:])


def patch_intent(
    resource: ApiResource,
    target: ResourceTarget,
    record: ResourceRecord,
    changes: list[dict[str, Any]],
    *,
    subresource: str | None = None,
) -> MutationIntent:
    target.require_current(target.session, uid=record.uid or "")
    if (
        record.name != target.name
        or record.namespace != target.namespace
        or record.resource_version is None
    ):
        raise AppError("Mutation snapshot does not match the captured target/version.")
    operations = [
        {"op": "test", "path": "/metadata/uid", "value": target.uid},
        {"op": "test", "path": "/metadata/resourceVersion", "value": record.resource_version},
        *changes,
    ]
    try:
        body = json.dumps(
            operations, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Mutation values must be finite, bounded JSON.") from None
    return MutationIntent(target, resource, record.resource_version, body, subresource=subresource)


def annotation_key(value: str) -> str:
    if not isinstance(value, str):
        raise AppError("Annotation key must be text.")
    parts = value.split("/")
    name = parts[-1]
    valid = (
        len(parts) <= 2
        and 1 <= len(name) <= 63
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?", name) is not None
    )
    if len(parts) == 2:
        prefix = parts[0]
        valid = (
            valid
            and 1 <= len(prefix) <= 253
            and all(
                1 <= len(label) <= 63
                and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is not None
                for label in prefix.split(".")
            )
        )
    if not valid:
        raise AppError("Invalid Kubernetes annotation key.")
    return value


def annotation_intent(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, key: str, value: str
) -> MutationIntent:
    annotation_key(key)
    if not isinstance(value, str) or len(value) > 65536:
        raise AppError("Annotation value must be text of at most 65,536 characters.")
    metadata = resource_object(record.manifest.get("metadata"))
    existing = metadata.get("annotations")
    annotations = resource_object({} if existing is None else existing)
    if any(not isinstance(item, str) for item in annotations.values()):
        raise AppError("Existing annotation values are invalid.")
    merged = {**annotations, key: value}
    try:
        size = sum(len(k.encode("utf-8")) + len(v.encode("utf-8")) for k, v in merged.items())
    except UnicodeError:
        raise AppError("Annotation text must be valid UTF-8.") from None
    if size > 256 * 1024:
        raise AppError("Combined annotations exceed 256 KiB.")
    return patch_intent(
        resource, target, record, [{"op": "add", "path": "/metadata/annotations", "value": merged}]
    )


class MutationState(Enum):
    SUCCEEDED = "Succeeded"
    ACCEPTED = "Accepted; deletion pending"
    BLOCKED = "Blocked"
    STALE = "Stale target"
    DENIED = "Permission denied"
    AUTH_ERROR = "Authentication failed"
    CONFLICT = "Conflict"
    NOT_FOUND = "Target unavailable"
    REJECTED = "Rejected"
    TIMEOUT = "Timed out before write"
    CANCELLED = "Cancelled before write"
    UNREACHABLE = "Connection failed before write"
    UNCERTAIN = "Write outcome uncertain"


@dataclass(frozen=True)
class MutationResult:
    state: MutationState
    message: str
    items: tuple[tuple[ResourceTarget, "MutationResult"], ...] = ()


def status_result(status: int) -> MutationResult:
    states = {
        401: (
            MutationState.AUTH_ERROR,
            "Authentication refused (401). Connect again; the write was not retried.",
        ),
        403: (
            MutationState.DENIED,
            "Permission denied (403). Check patch access to this resource.",
        ),
        404: (MutationState.NOT_FOUND, "Target unavailable (404). Select the resource again."),
        409: (
            MutationState.CONFLICT,
            "Conflict (409). Read the current object and confirm a new change.",
        ),
        400: (MutationState.REJECTED, "Patch rejected (400). No automatic retry."),
        413: (MutationState.REJECTED, "Patch too large (413). No automatic retry."),
        422: (
            MutationState.REJECTED,
            "Patch rejected (422): a UID/version test or validation failed. Read the object again.",
        ),
    }
    state, message = states.get(
        status,
        (
            MutationState.UNCERTAIN,
            "The API did not establish the write result. Inspect the current object before making another change.",
        ),
    )
    return MutationResult(state, message)
