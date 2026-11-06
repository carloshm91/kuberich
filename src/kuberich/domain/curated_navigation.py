"""Closed, literal destinations for explicit curated-resource navigation."""

from dataclasses import dataclass
from typing import Literal

from kuberich.domain.authorization import AuthorizationIntent
from kuberich.domain.events import EventGroupMembers
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipRef,
    RelationshipSelector,
    resource_labels,
    selector_matches,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment
from kuberich.errors import AppError


@dataclass(frozen=True, slots=True)
class AllResources:
    def matches(self, resource: ApiResource, record: ResourceRecord) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class LabelsMatch:
    selector: RelationshipSelector

    def matches(self, resource: ApiResource, record: ResourceRecord) -> bool:
        try:
            return selector_matches(self.selector, dict(resource_labels(record)))
        except AppError:
            return False


def _field_matches(
    resource: ApiResource,
    record: ResourceRecord,
    expected: tuple[str, str, str],
    field: str,
    value: str,
) -> bool:
    if (
        (resource.api_version, resource.name, resource.kind) != expected
        or not resource.namespaced
        or record.metadata_only
    ):
        return False
    manifest = record.manifest
    if (
        manifest.get("apiVersion", resource.api_version) != resource.api_version
        or manifest.get("kind", resource.kind) != resource.kind
    ):
        return False
    spec = manifest.get("spec")
    return isinstance(spec, dict) and spec.get(field) == value


@dataclass(frozen=True, slots=True)
class PodRuntimeClass:
    name: str

    def __post_init__(self) -> None:
        api_segment(self.name)

    def matches(self, resource: ApiResource, record: ResourceRecord) -> bool:
        return _field_matches(
            resource, record, ("v1", "pods", "Pod"), "runtimeClassName", self.name
        )


@dataclass(frozen=True, slots=True)
class IngressClassName:
    name: str

    def __post_init__(self) -> None:
        api_segment(self.name)

    def matches(self, resource: ApiResource, record: ResourceRecord) -> bool:
        return _field_matches(
            resource,
            record,
            ("networking.k8s.io/v1", "ingresses", "Ingress"),
            "ingressClassName",
            self.name,
        )


type CuratedPredicate = (
    AllResources | LabelsMatch | PodRuntimeClass | IngressClassName | EventGroupMembers
)


@dataclass(frozen=True, slots=True)
class DeclaredObjectReference:
    group: str
    version: str | None
    kind: str
    namespace: str | None
    name: str
    uid: str | None = None


@dataclass(frozen=True, slots=True)
class ReferenceDestination:
    ref: RelationshipRef | DeclaredObjectReference
    require_uid: bool


@dataclass(frozen=True, slots=True)
class CollectionDestination:
    group: str
    resource: str
    version: str | None
    scope: Literal["object-namespace", "selected-namespace", "cluster"]
    namespace: str | None
    predicate: CuratedPredicate


@dataclass(frozen=True, slots=True)
class RelationshipDestination:
    mode: RelationshipMode


@dataclass(frozen=True, slots=True)
class AuthorizationDestination:
    intent: AuthorizationIntent


type CuratedDestination = (
    ReferenceDestination
    | CollectionDestination
    | RelationshipDestination
    | AuthorizationDestination
)


@dataclass(frozen=True, slots=True)
class CuratedLink:
    key: str
    label: str
    provenance: str
    destination: CuratedDestination | None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedCollectionBookmark:
    resource: ApiResource
    namespace: str | None
    predicate: CuratedPredicate
    query: ResourceQuery
