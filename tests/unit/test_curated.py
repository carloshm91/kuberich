"""Curated extraction binds full descriptors; enrollment never widens effects."""

import json
from dataclasses import replace

import pytest

from kuberich.domain.curated import (
    READ_ONLY_FAMILIES,
    CuratedFamily,
    curated_cells,
    curated_details,
    curated_read_only,
    matches_family,
    require_curated_record,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_record
from kuberich.domain.table_values import Column
from kuberich.errors import AppError

FAMILY = CuratedFamily(
    "autoscaling",
    "horizontalpodautoscalers",
    "HorizontalPodAutoscaler",
    True,
    frozenset({"v1", "v2"}),
    ("hpa",),
    (Column("desired", True),),
)
RESOURCE = ApiResource(
    FAMILY.group, "v2", FAMILY.resource, FAMILY.kind, True, frozenset({"get", "list", "watch"})
)


def record(resource=RESOURCE, *, normalized=True):
    return resource_record(
        resource,
        {
            **({"apiVersion": resource.api_version, "kind": resource.kind} if normalized else {}),
            "metadata": {
                "name": "owned",
                "uid": "owned-uid",
                "resourceVersion": "owned-version",
                **({"namespace": "team"} if resource.namespaced else {}),
            },
            "spec": {},
        },
    )


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_full_supported_descriptors_and_normalized_records_reach_extraction(version):
    resource = replace(RESOURCE, version=version)
    for normalized in (True, False):
        supplied = record(resource, normalized=normalized)
        family, manifest = require_curated_record(resource, supplied, (FAMILY,))
        assert family is FAMILY and manifest["metadata"]["uid"] == supplied.uid
        assert matches_family(FAMILY, resource)


@pytest.mark.parametrize(
    "change",
    [
        {"group": "unrelated.example"},
        {"version": "v99"},
        {"name": "other"},
        {"kind": "Other"},
        {"namespaced": False},
    ],
)
def test_same_name_or_similar_schema_never_substitutes_for_an_exact_descriptor(change):
    resource = replace(RESOURCE, **change)
    assert not matches_family(FAMILY, resource)
    with pytest.raises(AppError, match="unavailable"):
        require_curated_record(resource, record(), (FAMILY,))


def test_compact_records_and_unrecognized_profiles_never_use_server_cells():
    with pytest.raises(AppError, match="unavailable"):
        require_curated_record(RESOURCE, replace(record(), metadata_only=True), (FAMILY,))
    with pytest.raises(AppError, match="unavailable"):
        require_curated_record(RESOURCE, record(), ())


@pytest.mark.parametrize("change", [{"version": "v1"}, {"kind": "Other"}])
def test_contradictory_record_type_is_rejected_before_fields_are_read(change):
    with pytest.raises(AppError, match="identity"):
        require_curated_record(RESOURCE, record(replace(RESOURCE, **change)), (FAMILY,))


def test_scope_must_match_even_for_an_otherwise_valid_record():
    with pytest.raises(AppError, match="identity"):
        require_curated_record(RESOURCE, replace(record(), namespace=None), (FAMILY,))
    family = CuratedFamily(
        "scheduling.k8s.io",
        "priorityclasses",
        "PriorityClass",
        False,
        frozenset({"v1"}),
        (),
        (Column("priority", True),),
    )
    cluster = ApiResource(family.group, "v1", family.resource, family.kind, False, RESOURCE.verbs)
    assert require_curated_record(cluster, record(cluster), (family,))[0] is family


@pytest.mark.parametrize("field", ["name", "uid", "namespace", "resourceVersion", "mapping"])
def test_payload_metadata_cannot_replace_the_captured_record_identity(field):
    supplied = record()
    payload = supplied.manifest
    if field == "mapping":
        payload["metadata"] = []
    else:
        payload["metadata"][field] = "replacement"
    contradictory = ResourceRecord(
        supplied.name,
        supplied.uid,
        supplied.namespace,
        supplied.resource_version,
        supplied.created_at,
        json.dumps(payload).encode(),
    )
    with pytest.raises(AppError, match="metadata"):
        require_curated_record(RESOURCE, contradictory, (FAMILY,))


def test_empty_cluster_namespace_is_normalized_without_changing_the_captured_record():
    family = CuratedFamily(
        "scheduling.k8s.io",
        "priorityclasses",
        "PriorityClass",
        False,
        frozenset({"v1"}),
        (),
        (Column("priority", True),),
    )
    resource = ApiResource(family.group, "v1", family.resource, family.kind, False, RESOURCE.verbs)
    payload = record(resource).manifest
    payload["metadata"]["namespace"] = ""
    supplied = resource_record(resource, payload)
    selected, manifest = require_curated_record(resource, supplied, (family,))
    assert (
        selected is family
        and supplied.namespace is None
        and manifest["metadata"]["namespace"] == ""
    )


@pytest.mark.parametrize("group,name", sorted(READ_ONLY_FAMILIES))
def test_named_family_effect_guard_is_independent_of_version_scope_and_advertised_verbs(
    group, name
):
    resource = ApiResource(
        group, "unrecognized", name, "OtherKind", False, frozenset({"delete", "patch"})
    )
    assert curated_read_only(resource)
    assert not curated_read_only(replace(resource, group="unrelated.example"))


def test_existing_workload_actions_are_outside_the_new_family_restriction():
    assert not curated_read_only(
        ApiResource("apps", "v1", "deployments", "Deployment", True, frozenset())
    )


@pytest.mark.parametrize("render", [curated_cells, curated_details])
def test_unknown_served_versions_fail_closed_in_the_shared_dispatcher(render):
    with pytest.raises(AppError, match="unavailable"):
        render(replace(RESOURCE, version="v99"), record())
