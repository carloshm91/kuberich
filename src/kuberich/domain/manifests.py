"""Frozen local manifests and exact, discovered Kubernetes mutation decisions."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from difflib import unified_diff
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

import yaml

from kuberich.domain.connections import namespace_name
from kuberich.domain.editing import edited_intent, parse_manifest, parse_manifest_documents
from kuberich.domain.exports import DirectoryRef, FileIdentity
from kuberich.domain.inspection import redacted
from kuberich.domain.mutations import MutationIntent, MutationResult, MutationState, status_result
from kuberich.domain.operations import ResourceIntent
from kuberich.domain.resources import (
    ApiResource,
    Discovery,
    ResourceRecord,
    api_segment,
    resource_name,
    resource_object,
    split_api_version,
)
from kuberich.domain.targets import MutationTarget, ResourceAddress, ResourceTarget, SessionIdentity
from kuberich.errors import AppError

MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MANIFEST_RESOURCES = 100
MAX_MANIFEST_FILES = 256
MAX_MANIFEST_DEPTH = 32
MAX_MANIFEST_ENTRIES = 2048
MAX_PREVIEW_BYTES = 256 * 1024
LAST_APPLIED = "kubectl.kubernetes.io/last-applied-configuration"
_SERVER_METADATA = frozenset(
    {
        "uid",
        "resourceVersion",
        "managedFields",
        "creationTimestamp",
        "generation",
        "deletionTimestamp",
        "deletionGracePeriodSeconds",
        "selfLink",
    }
)
_MUTABLE_METADATA = frozenset({"annotations", "labels", "finalizers", "ownerReferences"})

type ManifestSourceKind = Literal["file", "directory", "kustomize"]
type ManifestAction = Literal["apply", "delete", "create"]
type ManifestCreatePolicy = Literal["apply", "create-only"]
type DraftSourceKind = Literal["template", "clipboard", "paste", "file"]
type ManifestChange = Literal["create", "update", "delete", "unchanged", "absent", "refused"]


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestFileSnapshot:
    relative_path: str
    identity: FileIdentity
    sha256: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestEntry:
    relative_path: str
    kind: Literal["directory", "manifest", "kustomization", "unavailable"]
    identity: FileIdentity
    problem: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestListing:
    root: DirectoryRef
    relative_directory: str
    entries: tuple[ManifestEntry, ...]
    limited: bool
    skipped: int


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestDocument:
    ordinal: int
    source_path: str
    api_version: str
    kind: str
    name: str
    namespace: str | None
    body: bytes = field(repr=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class FrozenManifestSource:
    identity: UUID
    root: DirectoryRef
    kind: ManifestSourceKind
    relative_path: str
    files: tuple[ManifestFileSnapshot, ...]
    documents: tuple[ManifestDocument, ...]
    source_sha256: str = field(repr=False)
    rendered_sha256: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class ManifestSource(Protocol):
    """Only frozen source identity and documents cross into cluster mutation."""

    identity: UUID
    documents: tuple[ManifestDocument, ...]
    source_sha256: str = field(repr=False)


@dataclass(frozen=True, kw_only=True, slots=True)
class FrozenDraftSource:
    identity: UUID
    kind: DraftSourceKind
    title: str
    generation: int
    documents: tuple[ManifestDocument, ...]
    source_sha256: str = field(repr=False)
    rendered_sha256: str = field(repr=False)
    body: bytes = field(repr=False)
    private_preview: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class CreatedResourceReceipt:
    """Persistent metadata from a verified HTTP 201, never a dry-run identity."""

    resource: ApiResource
    target: ResourceTarget
    resource_version: str


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestScope:
    session: SessionIdentity
    namespace: str | None


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestCreateIntent:
    identity: UUID
    target: ResourceAddress
    resource: ApiResource
    body: bytes = field(repr=False)
    policy: ManifestCreatePolicy = "apply"

    @property
    def path(self) -> str:
        return self.resource.path(self.target.namespace)

    @property
    def effects(self) -> tuple[str, ...]:
        return (f"create {self.target.resource}/{self.target.name}",)


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestPlanItem:
    document: ManifestDocument
    resource: ApiResource
    target: MutationTarget
    change: ManifestChange
    request: MutationIntent | ResourceIntent | ManifestCreateIntent | None
    validation: MutationResult
    preview_pages: tuple[str, ...]
    resource_version: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestPlan:
    identity: UUID
    source_identity: UUID
    source_sha256: str = field(repr=False)
    scope: ManifestScope
    action: ManifestAction
    items: tuple[ManifestPlanItem, ...]

    @property
    def effects(self) -> tuple[str, ...]:
        return tuple(
            f"{item.change} {item.resource.api_version}/{item.target.resource}/{item.target.name} "
            f"namespace={item.target.namespace or '(cluster)'} "
            f"UID={item.target.uid or '(not captured)'} "
            f"resourceVersion={item.resource_version or '(not captured)'}"
            for item in self.items
        )

    @property
    def targets(self) -> tuple[MutationTarget, ...]:
        """Metadata-only admission snapshot, including reviewed absent names."""
        return tuple(item.target for item in self.items)

    @property
    def ready(self) -> bool:
        return bool(self.items) and all(
            item.validation.state is MutationState.SUCCEEDED for item in self.items
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestDisclosureIntent:
    identity: UUID
    source: ManifestFileSnapshot
    root: DirectoryRef


@dataclass(frozen=True, kw_only=True, slots=True)
class ManifestSaveIntent:
    identity: UUID
    original: ManifestFileSnapshot
    root: DirectoryRef
    body: bytes = field(repr=False)
    preview_pages: tuple[str, ...]


def canonical_manifest(value: Any) -> bytes:
    """Finite JSON is the immutable transport format; never return parser excerpts."""
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Manifest values must be finite JSON-compatible UTF-8.") from None


def manifest_documents(data: bytes, *, source_path: str) -> tuple[ManifestDocument, ...]:
    values = parse_manifest_documents(
        data, max_bytes=MAX_SOURCE_BYTES, max_documents=MAX_MANIFEST_RESOURCES
    )
    expanded: list[dict[str, Any]] = []
    for value in values:
        if value.get("apiVersion") == "v1" and value.get("kind") == "List":
            if set(value) - {"apiVersion", "kind", "metadata", "items"} or not isinstance(
                value.get("items"), list
            ):
                raise AppError("A Kubernetes List must contain ordinary resource items.")
            expanded.extend(resource_object(item) for item in value["items"])
        else:
            expanded.append(value)
        if len(expanded) > MAX_MANIFEST_RESOURCES:
            raise AppError("Manifest source exceeds 100 resources; split the input.")
    if not expanded:
        raise AppError("Manifest source contains no resources.")
    result: list[ManifestDocument] = []
    for ordinal, value in enumerate(expanded, 1):
        api_version = value.get("apiVersion")
        split_api_version(api_version)
        assert isinstance(api_version, str)
        kind = value.get("kind")
        if (
            not isinstance(kind, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind) is None
            or kind.endswith("List")
        ):
            raise AppError(
                "Manifest requires one exact resource kind; nested or arbitrary Lists are unsupported."
            )
        metadata = resource_object(value.get("metadata"))
        name = resource_name(metadata.get("name"))
        if "status" in value or _SERVER_METADATA.intersection(metadata):
            raise AppError("Local manifests cannot supply status or server-owned metadata.")
        namespace = metadata.get("namespace")
        if namespace == "":
            del metadata["namespace"]
            namespace = None
        if namespace is not None:
            namespace = namespace_name(namespace)
        body = canonical_manifest(value)
        if len(body) > MAX_MANIFEST_BYTES:
            raise AppError("Each manifest resource must fit within 1 MiB.")
        result.append(
            ManifestDocument(
                ordinal=ordinal,
                source_path=source_path,
                api_version=api_version,
                kind=kind,
                name=name,
                namespace=namespace,
                body=body,
            )
        )
    if sum(len(item.body) for item in result) > MAX_SOURCE_BYTES:
        raise AppError("Expanded manifest source exceeds 8 MiB.")
    return tuple(result)


def resolve_manifest(
    document: ManifestDocument, discovery: Discovery, scope: ManifestScope
) -> tuple[ApiResource, ResourceAddress, bytes]:
    group, version = split_api_version(document.api_version)
    candidates = tuple(
        resource
        for resource in discovery.resources
        if resource.group == group
        and resource.version == version
        and resource.kind == document.kind
    )
    if len(candidates) != 1:
        raise AppError("Manifest GVK is unavailable or ambiguous in captured discovery.")
    resource = candidates[0]
    api_segment(resource.name)
    if (
        "get" not in resource.verbs
        or not {"create", "patch", "delete"}.intersection(resource.verbs)
        or "/" in resource.name
    ):
        raise AppError("Manifest requires a discovered, readable persistent resource endpoint.")
    namespace = document.namespace
    if resource.namespaced:
        namespace = namespace if namespace is not None else scope.namespace
        if namespace is None:
            raise AppError("Choose an explicit destination namespace for this manifest.")
        namespace = namespace_name(namespace)
    elif namespace is not None:
        raise AppError("A cluster-scoped manifest cannot contain a namespace.")
    value = parse_manifest(document.body)
    metadata = resource_object(value.get("metadata"))
    if namespace is not None:
        metadata["namespace"] = namespace
    target = ResourceAddress(
        session=scope.session,
        group=resource.group,
        resource=resource.name,
        namespace=namespace,
        name=document.name,
    )
    return resource, target, canonical_manifest(value)


def _without_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_nulls(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_without_nulls(item) for item in value]
    return value


def create_manifest_intent(
    resource: ApiResource,
    target: ResourceAddress,
    body: bytes,
    *,
    policy: ManifestCreatePolicy = "apply",
) -> ManifestCreateIntent:
    value = parse_manifest(body)
    metadata = resource_object(value.get("metadata"))
    if (
        resource.group != target.group
        or resource.name != target.resource
        or "create" not in resource.verbs
        or resource.namespaced != (target.namespace is not None)
        or value.get("apiVersion") != resource.api_version
        or value.get("kind") != resource.kind
        or metadata.get("name") != target.name
        or metadata.get("namespace") != target.namespace
        or _SERVER_METADATA.intersection(metadata)
        or "status" in value
        or policy not in {"apply", "create-only"}
        or (policy == "create-only" and "generateName" in metadata)
    ):
        raise AppError("Create body does not match the exact discovered resource address.")
    annotations = resource_object(metadata.setdefault("annotations", {}))
    if any(not isinstance(item, str) for item in annotations.values()):
        raise AppError("Manifest annotations must contain strings.")
    annotations.pop(LAST_APPLIED, None)
    if policy == "apply":
        annotations[LAST_APPLIED] = canonical_manifest(value).decode("utf-8") + "\n"
    if (
        sum(
            len(key.encode("utf-8")) + len(item.encode("utf-8"))
            for key, item in annotations.items()
        )
        > 256 * 1024
    ):
        raise AppError("Combined manifest annotations exceed 256 KiB.")
    # Pinned kubectl records the desired input before pruning map nulls.
    # Array positions (including null entries) remain unchanged.
    # Apply preserves kubectl's established null-pruning merge semantics.
    # Create-only submits literal nulls unchanged for authoritative server handling.
    request = canonical_manifest(_without_nulls(value) if policy == "apply" else value)
    if len(request) > MAX_MANIFEST_BYTES:
        raise AppError(
            "Created resource including apply annotation exceeds 1 MiB."
            if policy == "apply"
            else "Created resource request exceeds 1 MiB."
        )
    return ManifestCreateIntent(
        identity=uuid4(), target=target, resource=resource, body=request, policy=policy
    )


def manifest_update_intent(
    resource: ApiResource, target: ResourceTarget, baseline: ResourceRecord, server_preview: bytes
) -> MutationIntent | None:
    value = parse_manifest(server_preview)
    metadata = resource_object(value.get("metadata"))
    if (
        value.get("apiVersion") != resource.api_version
        or value.get("kind") != resource.kind
        or metadata.get("name") != target.name
        or metadata.get("namespace") != target.namespace
        or metadata.get("uid") != target.uid
        or metadata.get("resourceVersion") != baseline.resource_version
    ):
        raise AppError("Server preview identity/version differs from the captured baseline.")
    before = resource_object(baseline.manifest.get("metadata"))
    value.pop("status", None)
    value["metadata"] = {
        **{
            key: item
            for key, item in before.items()
            if key not in _MUTABLE_METADATA and key != "managedFields"
        },
        **{key: item for key, item in metadata.items() if key in _MUTABLE_METADATA},
    }
    return edited_intent(resource, target, baseline, canonical_manifest(value))


def manifest_pages(text: str) -> tuple[str, ...]:
    pages: list[str] = []
    current: list[str] = []
    size = 0
    for character in text:
        length = len(character.encode("utf-8"))
        if size + length > MAX_PREVIEW_BYTES:
            pages.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += length
    pages.append("".join(current))
    return tuple(pages)


def _preview_document(data: bytes) -> tuple[str, tuple[bytes, ...]]:
    values = parse_manifest_documents(
        data, max_bytes=MAX_SOURCE_BYTES, max_documents=MAX_MANIFEST_RESOURCES
    )
    safe: list[Any] = []
    normalized: list[bytes] = []
    for value in values:
        value.pop("status", None)
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("managedFields", None)
        normalized.append(canonical_manifest(value))
        # Redact List children with their own kinds, before the outer envelope.
        if value.get("kind") == "List" and isinstance(value.get("items"), list):
            value["items"] = [
                redacted(
                    item,
                    secret=isinstance(item, dict) and item.get("kind") in {"Secret", "ConfigMap"},
                )
                for item in value["items"]
            ]
        safe.append(redacted(value, secret=value.get("kind") in {"Secret", "ConfigMap"}))
    return yaml.safe_dump_all(safe, allow_unicode=True, sort_keys=False, width=100), tuple(
        normalized
    )


def manifest_preview(
    before: bytes | None, after: bytes, *, private: bool = False
) -> tuple[str, ...]:
    if private:
        return (
            "Content withheld: this template declares sensitive input. "
            "Submitted, server-returned and edited content remain private. "
            "Review the separate exact destination metadata; use explicit trusted-editor disclosure to inspect values.\n",
        )
    new, current = _preview_document(after)
    if before is None:
        return manifest_pages(new)
    old, previous = _preview_document(before)
    if current == previous:
        return ("Unchanged; no request is required.\n",)
    difference = "".join(
        unified_diff(
            old.splitlines(True),
            new.splitlines(True),
            fromfile="live / original",
            tofile="reviewed",
        )
    )
    return manifest_pages(
        difference or "Changed values are hidden by the preview's redaction policy.\n"
    )


def manifest_config_preview(data: bytes) -> tuple[str, ...]:
    """Configuration is structure-only: generator literals and inline patches are data."""
    values = parse_manifest_documents(
        data, max_bytes=MAX_MANIFEST_BYTES, max_documents=MAX_MANIFEST_RESOURCES
    )
    if not values:
        raise AppError("Local configuration contains no YAML mappings.")

    def structure(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: structure(item) for key, item in value.items()}
        if isinstance(value, list):
            return [structure(item) for item in value]
        return "[REDACTED]"

    return manifest_pages(
        yaml.safe_dump_all(
            [redacted(structure(value)) for value in values], allow_unicode=True, sort_keys=False
        )
    )


def manifest_source_digest(files: tuple[ManifestFileSnapshot, ...]) -> str:
    return hashlib.sha256(
        canonical_manifest([[item.relative_path, item.sha256] for item in files])
    ).hexdigest()


def _status_field(value: Any) -> str | None:
    # Admission field strings can contain arbitrary Secret/map keys. Only
    # familiar schema tokens and numeric indexes are safe to publish.
    fields = frozenset(
        {
            "metadata",
            "name",
            "namespace",
            "labels",
            "annotations",
            "finalizers",
            "ownerReferences",
            "spec",
            "replicas",
            "selector",
            "matchLabels",
            "template",
            "containers",
            "initContainers",
            "ephemeralContainers",
            "image",
            "imagePullPolicy",
            "ports",
            "containerPort",
            "protocol",
            "env",
            "value",
            "valueFrom",
            "configMapKeyRef",
            "secretKeyRef",
            "key",
            "resources",
            "requests",
            "limits",
            "volumes",
            "volumeMounts",
            "mountPath",
            "readOnly",
            "serviceAccountName",
            "nodeName",
            "type",
            "clusterIP",
            "clusterIPs",
            "ipFamilies",
            "ipFamilyPolicy",
            "externalTrafficPolicy",
            "internalTrafficPolicy",
            "targetPort",
            "port",
            "storageClassName",
            "accessModes",
            "volumeMode",
            "volumeName",
            "capacity",
            "claimRef",
            "persistentVolumeClaim",
            "claimName",
            "minReplicas",
            "maxReplicas",
            "scaleTargetRef",
            "metrics",
            "policyTypes",
            "ingress",
            "egress",
            "from",
            "to",
            "roleRef",
            "subjects",
            "rules",
            "apiGroups",
            "verbs",
            "resourceNames",
        }
    )
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        return None
    parts = value.split(".")
    if len(parts) > 16:
        return None
    for part in parts:
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)(?:\[([0-9]{1,3})\])?", part)
        if match is None or match[1] not in fields:
            return None
    return value


def manifest_status(status: int, data: bytes) -> MutationResult:
    """Only allowlisted machine codes cross the admission-error display boundary."""
    result = status_result(status)
    reasons = {
        "Unauthorized",
        "Forbidden",
        "NotFound",
        "AlreadyExists",
        "Conflict",
        "Invalid",
        "BadRequest",
        "Timeout",
        "ServerTimeout",
        "TooManyRequests",
        "ServiceUnavailable",
        "InternalError",
        "MethodNotAllowed",
        "RequestEntityTooLarge",
        "UnsupportedMediaType",
    }
    causes = {
        "FieldValueNotFound",
        "FieldValueRequired",
        "FieldValueDuplicate",
        "FieldValueInvalid",
        "FieldValueNotSupported",
        "FieldValueForbidden",
        "FieldValueTooLong",
        "FieldValueTooMany",
        "TypeInvalid",
        "UnexpectedServerResponse",
    }
    codes: list[str] = []
    if 0 < len(data) <= 65536:
        try:
            value = parse_manifest_documents(data, max_bytes=65536, max_documents=1)
            if len(value) == 1 and value[0].get("kind") == "Status":
                reason = value[0].get("reason")
                if isinstance(reason, str) and reason in reasons:
                    codes.append(reason)
                details = value[0].get("details")
                if isinstance(details, dict) and isinstance(details.get("causes"), list):
                    for cause in details["causes"][:16]:
                        if (
                            isinstance(cause, dict)
                            and isinstance(cause.get("reason"), str)
                            and cause["reason"] in causes
                        ):
                            codes.append(cause["reason"])
                            path = _status_field(cause.get("field"))
                            if path is not None:
                                codes.append(path)
        except AppError:
            pass
    suffix = " Codes: " + ", ".join(dict.fromkeys(codes)) + "." if codes else ""
    return MutationResult(
        result.state,
        f"API request refused or unresolved (HTTP {status}).{suffix} Freeform server details withheld; no automatic retry.",
    )
