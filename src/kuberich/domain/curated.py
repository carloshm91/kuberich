"""Finite curated facts and the named families' read-only action boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kuberich.domain.curated_navigation import CuratedLink
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.table_values import Column, Value
from kuberich.errors import AppError

MAX_CURATED_CELL_CHARACTERS = 256
MAX_CURATED_DETAIL_ROWS = 256
MAX_CURATED_DETAIL_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class CuratedFamily:
    group: str
    resource: str
    kind: str
    namespaced: bool
    versions: frozenset[str]
    aliases: tuple[str, ...]
    fields: tuple[Column, ...]


@dataclass(frozen=True, slots=True)
class CuratedCells:
    values: tuple[tuple[str, Value], ...]
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DetailSection:
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    omitted_rows: int = 0


@dataclass(frozen=True, slots=True)
class CuratedDetails:
    sections: tuple[DetailSection, ...]
    links: tuple[CuratedLink, ...]
    notices: tuple[str, ...] = ()


READ_ONLY_FAMILIES = frozenset(
    {
        ("autoscaling", "horizontalpodautoscalers"),
        ("autoscaling.k8s.io", "verticalpodautoscalers"),
        ("policy", "poddisruptionbudgets"),
        ("networking.k8s.io", "networkpolicies"),
        ("discovery.k8s.io", "endpointslices"),
        ("networking.k8s.io", "ingressclasses"),
        ("scheduling.k8s.io", "priorityclasses"),
        ("node.k8s.io", "runtimeclasses"),
        ("coordination.k8s.io", "leases"),
        ("", "resourcequotas"),
        ("", "limitranges"),
        ("admissionregistration.k8s.io", "mutatingwebhookconfigurations"),
        ("admissionregistration.k8s.io", "validatingwebhookconfigurations"),
        ("", "serviceaccounts"),
        ("rbac.authorization.k8s.io", "roles"),
        ("rbac.authorization.k8s.io", "clusterroles"),
        ("rbac.authorization.k8s.io", "rolebindings"),
        ("rbac.authorization.k8s.io", "clusterrolebindings"),
        ("", "events"),
        ("events.k8s.io", "events"),
    }
)


def curated_read_only(resource: ApiResource) -> bool:
    """Registry enrollment cannot widen the existing generic action scope."""
    return (resource.group, resource.name) in READ_ONLY_FAMILIES


def matches_family(family: CuratedFamily, resource: ApiResource) -> bool:
    return (resource.group, resource.name, resource.kind, resource.namespaced) == (
        family.group,
        family.resource,
        family.kind,
        family.namespaced,
    ) and resource.version in family.versions


def require_curated_record(
    resource: ApiResource, record: ResourceRecord, families: tuple[CuratedFamily, ...]
) -> tuple[CuratedFamily, dict[str, Any]]:
    """Only a full record with its real served descriptor reaches extraction."""
    family = next((item for item in families if matches_family(item, resource)), None)
    if family is None or record.metadata_only:
        raise AppError("Curated fields are unavailable for this resource descriptor or record.")
    manifest = record.manifest
    if (
        manifest.get("apiVersion", resource.api_version) != resource.api_version
        or manifest.get("kind", resource.kind) != resource.kind
        or resource.namespaced != (record.namespace is not None)
    ):
        raise AppError("Curated record identity does not match the served resource.")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise AppError("Curated record metadata is unavailable.")
    namespace = metadata.get("namespace")
    if namespace == "":
        namespace = None
    if (
        metadata.get("name") != record.name
        or metadata.get("uid") != record.uid
        or namespace != record.namespace
        or metadata.get("resourceVersion") != record.resource_version
    ):
        raise AppError("Curated record metadata does not match its captured identity.")
    manifest.setdefault("apiVersion", resource.api_version)
    manifest.setdefault("kind", resource.kind)
    return family, manifest


def _sources() -> tuple[
    tuple[
        tuple[CuratedFamily, ...],
        Callable[[ApiResource, ResourceRecord], CuratedCells],
        Callable[[ApiResource, ResourceRecord], CuratedDetails],
    ],
    ...,
]:
    # Family modules depend on these records, not on the standard table registry.
    from kuberich.domain import curated_access, curated_policy, curated_scaling

    return (
        (curated_scaling.FAMILIES, curated_scaling.cells, curated_scaling.details),
        (curated_policy.FAMILIES, curated_policy.cells, curated_policy.details),
        (curated_access.FAMILIES, curated_access.cells, curated_access.details),
    )


def curated_families() -> tuple[CuratedFamily, ...]:
    return tuple(family for families, _, _ in _sources() for family in families)


def known_family(group: str, plural: str) -> CuratedFamily | None:
    return next(
        (
            family
            for family in curated_families()
            if (family.group, family.resource) == (group, plural)
        ),
        None,
    )


def supported_family(resource: ApiResource) -> CuratedFamily | None:
    family = known_family(resource.group, resource.name)
    return family if family is not None and matches_family(family, resource) else None


def curated_cells(resource: ApiResource, record: ResourceRecord) -> CuratedCells:
    for families, cells, _ in _sources():
        if any(matches_family(family, resource) for family in families):
            return cells(resource, record)
    raise AppError("Curated fields are unavailable for this resource version.")


def curated_details(resource: ApiResource, record: ResourceRecord) -> CuratedDetails:
    for families, _, details in _sources():
        if any(matches_family(family, resource) for family in families):
            return details(resource, record)
    raise AppError("Curated details are unavailable for this resource version.")
