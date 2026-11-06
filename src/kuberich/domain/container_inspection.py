"""Value-free container inspection records and bounded, explicit projections."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from kuberich.domain.configuration_data import DataKey
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError

type ContainerField = Literal["containers", "initContainers", "ephemeralContainers"]
type ContainerKind = Literal["App", "Init", "Sidecar", "Ephemeral"]
type SourceKind = Literal["ConfigMap", "Secret"]
type EntryId = tuple[Literal["env", "envFrom"], int, str | None]
type SourceState = Literal[
    "available",
    "not-found",
    "forbidden",
    "timed-out",
    "unreachable",
    "invalid",
    "unsupported",
    "not-collected-limit",
]
type PrecedenceState = Literal["effective", "overridden", "skipped", "unknown"]
type ResolutionState = Literal[
    "text-resolvable-hidden",
    "empty-hidden",
    "binary",
    "unresolved",
    "invalid",
]
type EnvOrigin = Literal[
    "literal",
    "configmap-key",
    "secret-key",
    "env-from-configmap",
    "env-from-secret",
    "field-ref",
    "resource-field-ref",
    "file-key-ref",
    "unsupported",
]

MAX_REFERENCES = 32
MAX_ENV_ROWS = 4096
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_GET_BYTES = 2 * 1024 * 1024
MAX_RESOLUTION_BYTES = 1024 * 1024
MAX_DEPENDENCY_EDGES = 65536
MAX_METADATA_BYTES = 1024 * 1024
MAX_METADATA_CELL = 4096
MAX_READS = 64
OBSERVATION_NOTICE = (
    "Resolved from current API configuration; actual process environment is not observed"
)


class ReasonCode(StrEnum):
    SOURCE_NOT_FOUND = "source-not-found"
    SOURCE_FORBIDDEN = "source-forbidden"
    SOURCE_TIMED_OUT = "source-timed-out"
    SOURCE_UNREACHABLE = "source-unreachable"
    SOURCE_INVALID = "source-invalid"
    SOURCE_UNSUPPORTED = "source-unsupported"
    REFERENCE_LIMIT = "reference-limit"
    ROW_LIMIT = "row-limit"
    INPUT_LIMIT = "input-limit"
    METADATA_LIMIT = "metadata-limit"
    RESOLUTION_LIMIT = "resolution-limit"
    DEPENDENCY_LIMIT = "dependency-limit"
    READ_LIMIT = "read-limit"
    INVALID_DECLARATION = "invalid-declaration"
    INVALID_NAME = "invalid-name"
    MISSING_KEY = "missing-key"
    OPTIONAL_MISSING = "optional-missing"
    UNKNOWN_BINDING = "unknown-binding"
    UNKNOWN_VARIABLE = "unknown-variable-service-injection-unobserved"
    BINARY_VALUE = "binary-value"
    NUL_VALUE = "nul-value"
    UNSUPPORTED_RUNTIME_SOURCE = "unsupported-runtime-source"
    UNSUPPORTED_FIELD = "unsupported-field"
    MISSING_FIELD = "missing-field"
    RUNTIME_FIELD = "runtime-field"
    UNSUPPORTED_RESOURCE = "unsupported-resource"
    MISSING_RESOURCE = "missing-resource"
    MISSING_CONTAINER = "missing-container"
    NODE_DEPENDENT = "node-dependent"
    INVALID_QUANTITY = "invalid-quantity"
    QUANTITY_LIMIT = "quantity-limit"
    STALE_BINDING = "stale-binding"
    ENTRY_UNAVAILABLE = "entry-unavailable"


@dataclass(frozen=True, slots=True)
class ContainerIdentity:
    field: ContainerField
    name: str
    kind: ContainerKind


@dataclass(frozen=True, slots=True)
class SourceRef:
    kind: SourceKind
    namespace: str
    name: str


@dataclass(frozen=True, slots=True)
class ObjectBinding:
    api_version: str
    kind: str
    namespace: str
    name: str
    uid: str
    resource_version: str
    payload_sha256: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SourceUse:
    path: str
    optional: bool
    prefix: str
    key: str | None


@dataclass(frozen=True, slots=True)
class SourceObservation:
    ref: SourceRef
    state: SourceState
    binding: ObjectBinding | None
    keys: tuple[DataKey, ...]
    observed_at: datetime
    references: tuple[SourceUse, ...]


@dataclass(frozen=True, slots=True)
class Dependency:
    name: str
    entry: EntryId | None
    reason: ReasonCode | None


@dataclass(frozen=True, slots=True)
class ResourceSelector:
    container_name: str | None
    resource: str
    divisor: str


@dataclass(frozen=True, slots=True)
class EnvEntry:
    id: EntryId
    name: str
    path: str
    origin: EnvOrigin
    source: SourceRef | None
    key: str | None
    prefix: str
    optional: bool
    field_path: str | None
    resource_selector: ResourceSelector | None
    dependencies: tuple[Dependency, ...]
    precedence: PrecedenceState
    resolution: ResolutionState
    reason: ReasonCode | None


@dataclass(frozen=True, slots=True)
class ImageFacts:
    declared: str | None
    pull_policy: str | None
    status_image: str | None
    image_id: str | None
    container_id: str | None
    pull_secret_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InspectionSnapshot:
    id: UUID
    target: ResourceTarget
    container: ContainerIdentity
    pod: ObjectBinding
    sources: tuple[SourceObservation, ...]
    entries: tuple[EnvEntry, ...]
    image: ImageFacts
    started_at: datetime
    observed_at: datetime
    complete: bool
    reads: int
    notices: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class SourceRead:
    ref: SourceRef
    state: SourceState
    record: ResourceRecord | None = field(repr=False)
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ReferencePlan:
    refs: tuple[SourceRef, ...]
    total: int
    limited: bool


@dataclass(frozen=True, slots=True)
class MetadataRow:
    key: str
    cells: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetadataTable:
    columns: tuple[str, ...]
    rows: tuple[MetadataRow, ...]


@dataclass(frozen=True, slots=True)
class ResolvedValue:
    text: str | None = field(repr=False)
    complete: bool
    reasons: tuple[ReasonCode, ...]


def object_binding(record: ResourceRecord, *, kind: str) -> ObjectBinding:
    """Validate a full core object and bind canonical content, UID and version."""
    data = record.manifest
    meta = data.get("metadata")
    if (
        record.metadata_only
        or record.size_bytes > MAX_GET_BYTES
        or data.get("apiVersion") != "v1"
        or data.get("kind") != kind
        or not isinstance(meta, dict)
    ):
        raise AppError("Invalid full container inspection object.")
    values = tuple(meta.get(key) for key in ("namespace", "name", "uid", "resourceVersion"))
    if any(
        not isinstance(value, str) or not value or len(value) > MAX_METADATA_CELL
        for value in values
    ):
        raise AppError("Container inspection requires bounded object identity and version.")
    namespace, name, uid, version = values
    if (namespace, name, uid, version) != (
        record.namespace,
        record.name,
        record.uid,
        record.resource_version,
    ):
        raise AppError("Container inspection object identity is inconsistent.")
    canonical = json.dumps(
        data, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    return ObjectBinding(
        "v1",
        kind,
        str(namespace),
        str(name),
        str(uid),
        str(version),
        hashlib.sha256(canonical.encode()).hexdigest(),
    )


def container_declaration(data: dict[str, Any], container: ContainerIdentity) -> dict[str, Any]:
    """Locate exactly one captured family/name/kind without status-position inference."""
    if (
        not isinstance(container.name, str)
        or not container.name
        or len(container.name) > MAX_METADATA_CELL
    ):
        raise AppError("The captured container identity is invalid; reload required.")
    spec = data.get("spec")
    raw = spec.get(container.field) if isinstance(spec, dict) else None
    matches = (
        [item for item in raw if isinstance(item, dict) and item.get("name") == container.name]
        if isinstance(raw, list)
        else []
    )
    if len(matches) != 1:
        raise AppError("The captured container is unavailable; reload required.")
    result = matches[0]
    kind = (
        "App"
        if container.field == "containers"
        else "Ephemeral"
        if container.field == "ephemeralContainers"
        else "Sidecar"
        if result.get("restartPolicy") == "Always"
        else "Init"
    )
    if container.kind != kind or container.field not in {
        "containers",
        "initContainers",
        "ephemeralContainers",
    }:
        raise AppError("The captured container kind changed; reload required.")
    return result


def reference_plan(pod: ResourceRecord, container: ContainerIdentity) -> ReferencePlan:
    from kuberich.domain.container_environment import collect_references

    refs, _ = collect_references(pod, container)
    return ReferencePlan(tuple(refs)[:MAX_REFERENCES], len(refs), len(refs) > MAX_REFERENCES)


def build_inspection(
    pod: ResourceRecord,
    container: ContainerIdentity,
    sources: tuple[SourceRead, ...],
    *,
    target: ResourceTarget,
    snapshot_id: UUID,
    started_at: datetime,
    observed_at: datetime,
    reads: int,
) -> InspectionSnapshot:
    from kuberich.domain.container_environment import build_snapshot

    return build_snapshot(
        pod,
        container,
        sources,
        target=target,
        snapshot_id=snapshot_id,
        started_at=started_at,
        observed_at=observed_at,
        reads=reads,
    )


def resolve_selected(
    snapshot: InspectionSnapshot,
    entry: EntryId,
    pod: ResourceRecord,
    sources: tuple[SourceRead, ...],
) -> ResolvedValue:
    from kuberich.domain.container_environment import resolve_entry

    return resolve_entry(snapshot, entry, pod, sources)


def _table(columns: tuple[str, ...], rows: tuple[MetadataRow, ...]) -> MetadataTable:
    bounded = tuple(
        MetadataRow(
            row.key,
            tuple(
                cell if len(cell) <= MAX_METADATA_CELL else "(metadata omitted: limit)"
                for cell in row.cells
            ),
        )
        for row in rows
    )
    if sum(len(cell.encode()) for row in bounded for cell in row.cells) > MAX_METADATA_BYTES:
        return MetadataTable(
            columns, (MetadataRow("limit", tuple("(metadata omitted: limit)" for _ in columns)),)
        )
    return MetadataTable(columns, bounded)


def metadata_table(
    snapshot: InspectionSnapshot, section: Literal["environment", "image", "sources"]
) -> MetadataTable:
    """Project an explicit value-free allowlist; never serialize the snapshot."""
    if section == "environment":
        return _table(
            ("NAME", "PATH", "SOURCE", "PRECEDENCE", "RESOLUTION", "REASON", "DEPENDENCIES"),
            tuple(
                MetadataRow(
                    str(entry.id),
                    (
                        entry.name,
                        entry.path,
                        entry.origin + (":" + entry.source.name if entry.source else ""),
                        entry.precedence,
                        entry.resolution,
                        entry.reason.value if entry.reason else "",
                        ", ".join(dependency.name for dependency in entry.dependencies),
                    ),
                )
                for entry in snapshot.entries
            ),
        )
    if section == "image":
        facts = snapshot.image
        return _table(
            ("ORIGIN", "FIELD", "VALUE"),
            tuple(
                MetadataRow(
                    origin + ":" + name,
                    (origin, name, value if value is not None else "unavailable"),
                )
                for origin, name, value in (
                    ("declaration", "image", facts.declared),
                    ("declaration", "imagePullPolicy", facts.pull_policy),
                    ("status", "image", facts.status_image),
                    ("status", "imageID", facts.image_id),
                    ("status", "containerID", facts.container_id),
                    ("declaration", "imagePullSecrets", ", ".join(facts.pull_secret_names)),
                )
            ),
        )
    rows = []
    for ordinal, source in enumerate(snapshot.sources):
        binding = source.binding
        rows.append(
            MetadataRow(
                str(ordinal),
                (
                    source.ref.kind,
                    source.ref.namespace,
                    source.ref.name,
                    source.state,
                    binding.uid if binding else "",
                    binding.resource_version if binding else "",
                    source.observed_at.isoformat(),
                    "; ".join(
                        f"{use.path} optional={use.optional} prefix={use.prefix} key={use.key or ''}"
                        for use in source.references
                    ),
                    "; ".join(
                        f"{key.section}:{key.name} ({key.size} bytes, {'binary' if key.binary else 'text'})"
                        for key in source.keys
                    ),
                ),
            )
        )
    return _table(
        ("KIND", "NAMESPACE", "NAME", "STATE", "UID", "VERSION", "OBSERVED", "REFERENCES", "KEYS"),
        tuple(rows),
    )
