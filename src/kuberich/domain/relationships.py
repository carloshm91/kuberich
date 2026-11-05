"""Immutable relationship publications and bounded, transport-free Kubernetes facts."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from kuberich.domain.connections import namespace_name
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    Discovery,
    ResourceRecord,
    resource_name,
    split_api_version,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError

MAX_RELATIONSHIP_DEPTH = 8
MAX_RELATIONSHIP_NODES = 512
MAX_RELATIONSHIP_EDGES = 1024
MAX_RELATIONSHIP_ITEMS = 10000
MAX_RELATIONSHIP_BYTES = 16 * 1024 * 1024
MAX_FACT_ITEMS = 10000
MAX_FACT_BYTES = 1024 * 1024

type RelationshipPath = tuple[str, ...]
type RelationshipIdentity = tuple[str, str, str | None, str, str | None]


class RelationshipMode(StrEnum):
    XRAY = "xray"
    USED_BY = "usedby"


class RelationKind(StrEnum):
    CONTROLLER_OWNER = "controller_owner"
    OWNER = "owner"
    SELECTOR = "selector"
    ENDPOINT = "endpoint"
    NODE = "node"
    REFERENCE = "reference"


class RelationDirection(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"


class RelationshipEvidence(StrEnum):
    DECLARED = "declared"
    OBSERVED = "observed"
    INFERRED = "inferred"


class RelationshipStatus(StrEnum):
    LOADING = "loading"
    READY = "ready"
    FORBIDDEN = "forbidden"
    MISSING = "missing"
    REPLACED = "replaced"
    INVALID = "invalid"
    CYCLE = "cycle"
    UNAVAILABLE = "unavailable"
    TRUNCATED = "truncated"
    FAILED = "failed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class RelationshipRef:
    api_version: str
    kind: str
    namespace: str | None
    name: str
    uid: str | None
    resource: ApiResource | None


@dataclass(frozen=True, slots=True)
class RelationshipScope:
    root: ResourceTarget
    resource: ApiResource
    namespace: str | None
    mode: RelationshipMode


@dataclass(frozen=True, slots=True)
class RelationshipRequest:
    scope: RelationshipScope
    revision: int
    expanded: frozenset[RelationshipPath]


@dataclass(frozen=True, slots=True)
class RelationshipRow:
    path: RelationshipPath
    ref: RelationshipRef
    relation: RelationKind | None
    direction: RelationDirection | None
    evidence: RelationshipEvidence | None
    status: RelationshipStatus
    observed_uid: str | None
    details: tuple[str, ...]
    expandable: bool


@dataclass(frozen=True, slots=True)
class RelationshipSource:
    family: str
    namespace: str | None
    status: RelationshipStatus
    collection: CollectionState | None
    resource_version: str | None
    detail: str
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RelationshipSnapshot:
    request: RelationshipRequest
    rows: tuple[RelationshipRow, ...]
    sources: tuple[RelationshipSource, ...]
    requests_used: int
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class RelationshipBookmark:
    root: RelationshipRef
    mode: RelationshipMode
    expanded: frozenset[RelationshipPath]


@dataclass(frozen=True, slots=True)
class DeclaredReference:
    target: RelationshipRef
    path: str
    optional: bool
    defaulted: bool = False


@dataclass(frozen=True, slots=True)
class OwnerReference:
    target: RelationshipRef
    path: str
    controller: bool
    status: RelationshipStatus
    detail: str


@dataclass(frozen=True, slots=True)
class EndpointReference:
    target: RelationshipRef | None
    path: str
    ready: bool | None
    ports: tuple[str, ...]
    details: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LabelRequirement:
    key: str
    operator: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RelationshipSelector:
    requirements: tuple[LabelRequirement, ...]
    empty_matches: bool = True


def reference_for(resource: ApiResource, record: ResourceRecord) -> RelationshipRef:
    return RelationshipRef(
        resource.api_version, resource.kind, record.namespace, record.name, record.uid, resource
    )


def resolve_reference(discovery: Discovery, ref: RelationshipRef) -> RelationshipRef:
    """Resolve a GVK without guessed plurals; version fallback preserves one family."""
    group, version = split_api_version(ref.api_version)
    candidates = tuple(
        item for item in discovery.resources if item.group == group and item.kind == ref.kind
    )
    exact = tuple(item for item in candidates if item.version == version)
    matching = exact or candidates
    if len({item.name for item in matching}) > 1:
        raise AppError("Relationship kind is ambiguous in discovery.")
    return replace(ref, resource=matching[0] if matching else None)


def relationship_object_key(ref: RelationshipRef) -> tuple[str, str, str | None, str]:
    group, _ = split_api_version(ref.api_version)
    return (
        ref.resource.group if ref.resource is not None else group,
        ref.resource.name if ref.resource is not None else "kind:" + ref.kind,
        ref.namespace,
        ref.name,
    )


def relationship_identity(ref: RelationshipRef) -> RelationshipIdentity:
    return (*relationship_object_key(ref), ref.uid)


def reference_status(ref: RelationshipRef, record: ResourceRecord | None) -> RelationshipStatus:
    if record is None:
        return RelationshipStatus.MISSING
    if record.name != ref.name or record.namespace != ref.namespace:
        return RelationshipStatus.INVALID
    if ref.uid is not None and record.uid != ref.uid:
        return RelationshipStatus.REPLACED
    return RelationshipStatus.READY


def relationship_cycle(ref: RelationshipRef, ancestors: tuple[RelationshipRef, ...]) -> bool:
    """Only ancestors on this branch count; shared descendants remain independent."""
    return relationship_identity(ref) in {relationship_identity(item) for item in ancestors}


def relationship_path_key(path: RelationshipPath) -> str:
    return hashlib.sha256(json.dumps(path, ensure_ascii=True).encode()).hexdigest()


def relationship_actionable(row: RelationshipRow) -> bool:
    return (
        row.status == RelationshipStatus.READY
        and row.ref.resource is not None
        and "get" in row.ref.resource.verbs
        and bool(row.observed_uid)
        and (row.ref.uid is None or row.ref.uid == row.observed_uid)
    )


def relationship_manifest(record: ResourceRecord) -> dict[str, Any]:
    if record.metadata_only or record.size_bytes > MAX_RELATIONSHIP_BYTES:
        raise AppError("Incomplete or excessive relationship contents.")
    return record.manifest


def fact_mapping(value: Any) -> dict[str, Any]:
    """Strict schema traversal; malformed/excessive facts make collection incomplete."""
    if not isinstance(value, dict) or len(value) > MAX_FACT_ITEMS:
        raise AppError("Invalid or excessive relationship mapping.")
    return value


def fact_list(value: Any) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_FACT_ITEMS:
        raise AppError("Invalid or excessive relationship list.")
    return value


def fact_name(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 253:
        raise AppError("Invalid or excessive relationship identifier.")
    return resource_name(value)


def _reference(value: Any, namespace: str | None) -> RelationshipRef:
    data = fact_mapping(value)
    kind = data.get("kind")
    group, version = split_api_version(data.get("apiVersion", "v1" if kind == "Pod" else None))
    api_version = f"{group}/{version}" if group else version
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind):
        raise AppError("Invalid relationship kind.")
    uid = data.get("uid")
    if uid is not None:
        uid = fact_name(uid)
    scope = data.get("namespace", namespace)
    if scope is not None:
        scope = namespace_name(fact_name(scope))
    return RelationshipRef(api_version, kind, scope, fact_name(data.get("name")), uid, None)


def owner_references(
    resource: ApiResource, record: ResourceRecord, discovery: Discovery
) -> tuple[OwnerReference, ...]:
    raw = fact_mapping(relationship_manifest(record).get("metadata")).get("ownerReferences", [])
    owners = fact_list(raw)
    if len(owners) > 128:
        raise AppError("Excessive relationship owner references.")
    result = []
    for index, value in enumerate(owners):
        path = f"metadata.ownerReferences[{index}]"
        try:
            data = fact_mapping(value)
            # OwnerReference GVK and UID are mandatory, never defaulted to Pod/name-only.
            if not all(key in data for key in ("apiVersion", "kind", "uid")):
                raise AppError("Owner identity is incomplete.")
            ref = resolve_reference(discovery, _reference(data, record.namespace))
            if ref.uid is None or type(data.get("controller", False)) is not bool:
                raise AppError("Owner identity is invalid.")
            owner = ref.resource
            status = RelationshipStatus.READY
            detail = "Declared owner; expected UID must match the observed object."
            if owner is None:
                status, detail = RelationshipStatus.UNAVAILABLE, "Owner kind was not discovered."
            elif owner.namespaced:
                if not resource.namespaced or ref.namespace != record.namespace:
                    status, detail = RelationshipStatus.INVALID, "Invalid namespaced owner scope."
            elif data.get("namespace") is not None:
                status, detail = (
                    RelationshipStatus.INVALID,
                    "Cluster owner cannot have a namespace.",
                )
            else:
                ref = replace(ref, namespace=None)
            result.append(OwnerReference(ref, path, data.get("controller", False), status, detail))
        except AppError:
            result.append(
                OwnerReference(
                    RelationshipRef(
                        "v1", "InvalidOwner", record.namespace, "invalid-owner", None, None
                    ),
                    path,
                    False,
                    RelationshipStatus.INVALID,
                    "Malformed owner identity or ambiguous discovery; ownership is unproven.",
                )
            )
    return tuple(result)


def _label(value: Any, *, key: bool) -> str:
    limit = 317 if key else 63
    if not isinstance(value, str) or len(value) > limit:
        raise AppError("Invalid relationship label.")
    parts = value.split("/") if key else [value]
    if len(parts) > 2:
        raise AppError("Invalid relationship label.")
    name = parts[-1]
    if (
        (key and not name)
        or len(name) > 63
        or (name and not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?", name))
    ):
        raise AppError("Invalid relationship label.")
    if len(parts) == 2 and (
        not parts[0]
        or len(parts[0]) > 253
        or not re.fullmatch(
            r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*", parts[0]
        )
    ):
        raise AppError("Invalid relationship label prefix.")
    return value


def _labels(value: Any) -> tuple[tuple[str, str], ...]:
    data = fact_mapping(value)
    if sum(len(str(key)) + len(str(item)) for key, item in data.items()) > MAX_FACT_BYTES:
        raise AppError("Excessive relationship labels.")
    return tuple((_label(key, key=True), _label(item, key=False)) for key, item in data.items())


def resource_labels(record: ResourceRecord) -> tuple[tuple[str, str], ...]:
    return _labels(fact_mapping(relationship_manifest(record).get("metadata")).get("labels", {}))


def native_selector(resource: ApiResource, record: ResourceRecord) -> RelationshipSelector | None:
    """Use structured Kubernetes selectors, independently of the CLI filter grammar."""
    family = (resource.group, resource.name)
    direct = family in {("", "services"), ("", "replicationcontrollers")}
    structured = family in {
        ("apps", "deployments"),
        ("apps", "replicasets"),
        ("apps", "statefulsets"),
        ("apps", "daemonsets"),
        ("batch", "jobs"),
    }
    if not direct and not structured:
        return None
    spec = fact_mapping(relationship_manifest(record).get("spec"))
    if "selector" not in spec or spec["selector"] is None:
        return None
    raw = fact_mapping(spec["selector"])
    if not direct and set(raw) - {"matchLabels", "matchExpressions"}:
        raise AppError("Invalid relationship selector fields.")
    labels = _labels(raw if direct else raw.get("matchLabels", {}))
    result = [LabelRequirement(key, "In", (value,)) for key, value in labels]
    value_count = 0
    if not direct:
        for item in fact_list(raw.get("matchExpressions", [])):
            expression = fact_mapping(item)
            key = _label(expression.get("key"), key=True)
            operator = expression.get("operator")
            raw_values = fact_list(expression.get("values", []))
            value_count += len(raw_values)
            if value_count > MAX_FACT_ITEMS:
                raise AppError("Excessive relationship selector values.")
            values = tuple(_label(value, key=False) for value in raw_values)
            if operator not in ("In", "NotIn", "Exists", "DoesNotExist") or (
                (operator in {"In", "NotIn"}) != bool(values)
            ):
                raise AppError("Invalid relationship selector expression.")
            result.append(LabelRequirement(key, operator, values))
    if (
        len(result) > MAX_FACT_ITEMS
        or sum(len(item.key) + sum(map(len, item.values)) for item in result) > MAX_FACT_BYTES
    ):
        raise AppError("Excessive relationship selector.")
    return RelationshipSelector(tuple(result), family != ("", "services"))


def selector_matches(selector: RelationshipSelector, labels: Mapping[str, str]) -> bool:
    fields = dict(_labels(dict(labels)))
    if not selector.requirements:
        return selector.empty_matches
    for item in selector.requirements:
        present = item.key in fields
        if item.operator == "In":
            matched = present and fields[item.key] in item.values
        elif item.operator == "NotIn":
            matched = not present or fields[item.key] not in item.values
        elif item.operator == "Exists":
            matched = present
        elif item.operator == "DoesNotExist":
            matched = not present
        else:
            raise AppError("Invalid relationship selector operator.")
        if not matched:
            return False
    return True


def node_reference(resource: ApiResource, record: ResourceRecord) -> DeclaredReference | None:
    if (resource.group, resource.name) != ("", "pods"):
        return None
    name = fact_mapping(relationship_manifest(record).get("spec")).get("nodeName")
    if name in (None, ""):
        return None
    return DeclaredReference(
        RelationshipRef("v1", "Node", None, fact_name(name), None, None), "spec.nodeName", False
    )


def endpoint_service_names(resource: ApiResource, record: ResourceRecord) -> tuple[str, ...]:
    family = (resource.group, resource.name)
    if family == ("", "endpoints"):
        return (record.name,)
    if family != ("discovery.k8s.io", "endpointslices"):
        return ()
    labels = fact_mapping(
        fact_mapping(relationship_manifest(record).get("metadata")).get("labels", {})
    )
    name = labels.get("kubernetes.io/service-name")
    return () if name is None else (fact_name(name),)


def _ports(raw: Any) -> tuple[str, ...]:
    result = []
    for value in fact_list(raw):
        data = fact_mapping(value)
        port = data.get("port")
        if port is not None and (type(port) is not int or not 1 <= port <= 65535):
            raise AppError("Invalid endpoint port.")
        protocol = data.get("protocol", "TCP")
        name = data.get("name", "")
        if protocol not in ("TCP", "UDP", "SCTP") or not isinstance(name, str):
            raise AppError("Invalid endpoint port metadata.")
        if name:
            fact_name(name)
        result.append(f"{name or '-'}:{port if port is not None else '?'} / {protocol}")
    return tuple(result)


def endpoint_references(
    resource: ApiResource, record: ResourceRecord
) -> tuple[EndpointReference, ...]:
    family = (resource.group, resource.name)
    groups: list[tuple[str, Any, bool | None, tuple[str, ...]]] = []
    if family == ("discovery.k8s.io", "endpointslices"):
        manifest = relationship_manifest(record)
        groups.append(
            ("endpoints", manifest.get("endpoints", []), None, _ports(manifest.get("ports", [])))
        )
    elif family == ("", "endpoints"):
        for index, raw in enumerate(fact_list(relationship_manifest(record).get("subsets", []))):
            subset = fact_mapping(raw)
            ports = _ports(subset.get("ports", []))
            for field, ready_flag in (("addresses", True), ("notReadyAddresses", False)):
                groups.append(
                    (f"subsets[{index}].{field}", subset.get(field, []), ready_flag, ports)
                )
    else:
        return ()
    result = []
    for path, raw, ready, ports in groups:
        for index, value in enumerate(fact_list(raw)):
            data = fact_mapping(value)
            condition = ready
            if family == ("discovery.k8s.io", "endpointslices"):
                condition = fact_mapping(data.get("conditions", {})).get("ready")
                if condition is not None and type(condition) is not bool:
                    raise AppError("Invalid endpoint readiness.")
            details = ["Reported backend; IP alone does not establish Pod identity."]
            if family == ("discovery.k8s.io", "endpointslices"):
                conditions = fact_mapping(data.get("conditions", {}))
                for field in ("serving", "terminating"):
                    flag = conditions.get(field)
                    if flag is not None and type(flag) is not bool:
                        raise AppError("Invalid endpoint condition.")
                    details.append(
                        f"{field}={str(flag).lower() if flag is not None else 'unknown'}"
                    )
            target = data.get("targetRef")
            ref = None if target is None else _reference(target, record.namespace)
            result.append(
                EndpointReference(
                    ref,
                    f"{path}[{index}].targetRef",
                    condition,
                    ports,
                    tuple(details),
                )
            )
            if len(result) > MAX_FACT_ITEMS:
                raise AppError("Excessive relationship endpoints.")
    return tuple(result)
