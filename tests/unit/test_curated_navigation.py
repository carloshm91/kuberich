"""Declared collection predicates keep literal identity and exact API schemas."""

from dataclasses import FrozenInstanceError, replace

import pytest

from kuberich.domain.curated_navigation import (
    AllResources,
    CollectionDestination,
    CuratedLink,
    DeclaredObjectReference,
    IngressClassName,
    LabelsMatch,
    PodRuntimeClass,
    ReferenceDestination,
    ResolvedCollectionBookmark,
)
from kuberich.domain.relationships import (
    LabelRequirement,
    RelationshipSelector,
    structured_selector,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.errors import AppError

PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
INGRESSES = ApiResource("networking.k8s.io", "v1", "ingresses", "Ingress", True, PODS.verbs)


def record(resource=PODS, *, spec=None, labels=None):
    return resource_record(
        resource,
        {
            "apiVersion": resource.api_version,
            "kind": resource.kind,
            "metadata": {
                "name": "owned",
                "namespace": "team",
                "uid": "owned-uid",
                "labels": {} if labels is None else labels,
            },
            "spec": spec,
        },
    )


def test_explicit_all_and_validated_structured_labels_do_not_use_the_text_filter_language():
    supplied = record(labels={"app": "owned", "tier": "api"})
    assert AllResources().matches(PODS, supplied)
    selector = structured_selector(
        {
            "matchLabels": {"app": "owned"},
            "matchExpressions": [{"key": "tier", "operator": "In", "values": ["api"]}],
        }
    )
    predicate = LabelsMatch(selector)
    assert predicate.matches(PODS, supplied)
    assert not predicate.matches(PODS, record(labels={"app": "other"}))
    assert not predicate.matches(PODS, record(labels=[]))
    assert not LabelsMatch(RelationshipSelector((LabelRequirement("app", "invalid", ()),))).matches(
        PODS, supplied
    )


@pytest.mark.parametrize("empty_matches", [False, True])
def test_empty_selector_meaning_is_owned_by_the_declared_family(empty_matches):
    selector = structured_selector({}, empty_matches=empty_matches)
    assert LabelsMatch(selector).matches(PODS, record()) is empty_matches


@pytest.mark.parametrize(
    "resource,predicate,field",
    [
        (PODS, PodRuntimeClass("sandbox.runtime"), "runtimeClassName"),
        (INGRESSES, IngressClassName("owned-class"), "ingressClassName"),
    ],
)
def test_field_predicates_bind_actual_version_kind_scope_and_full_literal_name(
    resource, predicate, field
):
    supplied = record(resource, spec={field: predicate.name})
    assert predicate.matches(resource, supplied)
    for change in (
        {"group": "other.example"},
        {"version": "v99"},
        {"name": "other"},
        {"kind": "Other"},
        {"namespaced": False},
    ):
        assert not predicate.matches(replace(resource, **change), supplied)
    assert not predicate.matches(resource, replace(supplied, metadata_only=True))
    assert not predicate.matches(
        resource, record(resource, spec={field: predicate.name + "-other"})
    )
    assert not predicate.matches(resource, record(resource, spec=None))
    assert not predicate.matches(resource, record(resource, spec=[]))
    assert not predicate.matches(
        resource, record(replace(resource, version="v2"), spec={field: predicate.name})
    )
    assert not predicate.matches(
        resource, record(replace(resource, kind="Other"), spec={field: predicate.name})
    )


@pytest.mark.parametrize("constructor", [PodRuntimeClass, IngressClassName])
@pytest.mark.parametrize("invalid", ["", "Upper", "../other", "owned%20class", "x" * 254, None])
def test_field_predicates_reject_invalid_literals_instead_of_clipping_identity(
    constructor, invalid
):
    with pytest.raises(AppError):
        constructor(invalid)


def test_declared_references_and_collection_bookmarks_preserve_exact_scope_and_query():
    reference = DeclaredObjectReference("apps", "v1", "Deployment", "team", "owned", "owned-uid")
    link = CuratedLink(
        "target", "Declared target", "spec.scaleTargetRef", ReferenceDestination(reference, True)
    )
    assert link.destination.ref is reference and link.destination.require_uid
    with pytest.raises(FrozenInstanceError):
        reference.name = "other"
    predicate = LabelsMatch(structured_selector({"matchLabels": {"app": "owned"}}))
    destination = CollectionDestination("", "pods", "v1", "selected-namespace", None, predicate)
    query = ResourceQuery(label_selector="app=owned")
    bookmark = ResolvedCollectionBookmark(PODS, "team", destination.predicate, query)
    assert bookmark.resource is PODS and bookmark.namespace == "team" and bookmark.query is query
    assert bookmark.predicate.matches(PODS, record(labels={"app": "owned"}))
