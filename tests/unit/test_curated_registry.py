"""Actual served descriptors enroll curated facts without trusting printer payloads."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kuberich.domain.curated import curated_cells, curated_families, supported_family
from kuberich.domain.registry import (
    RESOURCE_ALIASES,
    STANDARD_RESOURCES,
    definition_for_resource,
    order_resources,
    resource_row,
)
from kuberich.domain.resources import ServerColumn, ServerRow, resource_record
from kuberich.errors import AppError
from tests.support.curated_access import CANARY as ACCESS_CANARY
from tests.support.curated_policy import ANNOTATION_CANARY, CA_CANARY, URL_CANARIES
from tests.support.standard import FIXTURES, KINDS, api, manifest, roots, row_record

LEGACY = tuple(definition for definition in STANDARD_RESOURCES if not definition.curated)
CURATED = tuple(definition for definition in STANDARD_RESOURCES if definition.curated)
CANARY = "SYNTHETIC_PRINTER_PAYLOAD_MUST_NOT_ENTER_STANDARD_ROWS"
EXPECTED = {
    "horizontalpodautoscalers": {"min": ("0", 0), "max": ("5", 5), "desired": ("2", 2)},
    "verticalpodautoscalers": {"mode": ("Off", "off"), "recommended-containers": ("1", 1)},
    "poddisruptionbudgets": {"min-available": ("50%", (1, 50.0)), "allowed": ("0", 0)},
    "priorityclasses": {"priority": ("-10", -10), "global-default": ("true", 1)},
    "runtimeclasses": {"overhead-cpu": ("100m", Decimal("0.1")), "tolerations": ("1", 1)},
    "leases": {"duration-seconds": ("0", 0), "transitions": ("0", 0)},
    "networkpolicies": {
        "ingress-rules": ("1", 1),
        "policy-types": ("Egress, Ingress", "egress, ingress"),
    },
    "endpointslices": {
        "endpoints": ("3", 3),
        "ready": ("1", 1),
        "not-ready": ("1", 1),
        "unspecified": ("1", 1),
    },
    "ingressclasses": {"default": ("true", 1), "parameters-scope": ("Namespace", "namespace")},
    "resourcequotas": {"resources": ("3", 3), "exceeded": ("1", 1)},
    "limitranges": {
        "items": ("2", 2),
        "types": ("Container, PersistentVolumeClaim", "container, persistentvolumeclaim"),
    },
    "mutatingwebhookconfigurations": {
        "webhooks": ("2", 2),
        "timeout-min": ("7", 7),
        "timeout-max": ("20", 20),
    },
    "validatingwebhookconfigurations": {
        "webhooks": ("2", 2),
        "timeout-min": ("7", 7),
        "timeout-max": ("20", 20),
    },
    "serviceaccounts": {
        "automount": ("false", "false"),
        "secrets": ("1", 1),
        "image-pull-secrets": ("0", 0),
    },
    "roles": {"rules": ("1", 1), "resource-rules": ("1", 1), "nonresource-rules": ("0", 0)},
    "clusterroles": {"rules": ("1", 1), "aggregation-selectors": ("0", 0)},
    "rolebindings": {
        "role-kind": ("Role", "Role"),
        "service-accounts": ("1", 1),
        "users": ("0", 0),
    },
    "clusterrolebindings": {
        "role-kind": ("ClusterRole", "ClusterRole"),
        "service-accounts": ("1", 1),
        "groups": ("0", 0),
    },
}


def projected(definition, record=None, resource=None):
    row = resource_row(
        record or row_record(definition), definition, resource=resource or api(definition)
    )
    return {column.key: value for column, value in zip(definition.columns, row.values, strict=True)}


def test_all_advertised_family_fixtures_preserve_old_fifteen_and_exact_new_sources():
    assert len(STANDARD_RESOURCES) == len(KINDS) == len(FIXTURES) == 33
    assert len(LEGACY) == 15 and STANDARD_RESOURCES[:15] == LEGACY
    assert len(CURATED) == len(curated_families()) == 18
    assert {definition.name for definition in CURATED} == set(EXPECTED)
    discovery = roots()
    groups = {entry["name"]: entry for entry in discovery["/apis"]["groups"]}
    assert groups["autoscaling"]["preferredVersion"] == {
        "groupVersion": "autoscaling/v2",
        "version": "v2",
    }
    for definition in STANDARD_RESOURCES:
        resource = api(definition)
        expected_version = "v2" if definition.name == "horizontalpodautoscalers" else "v1"
        assert resource.version == expected_version
        path = f"/apis/{resource.api_version}" if resource.group else "/api/v1"
        served = next(
            item for item in discovery[path]["resources"] if item["name"] == definition.name
        )
        assert (served["kind"], served["namespaced"]) == (resource.kind, definition.namespaced)
        body = manifest(definition, name="preserved", uid="preserved-uid", namespace="other")
        assert (
            body["metadata"]["uid"] == "preserved-uid" and body["metadata"]["name"] == "preserved"
        )
        assert body["metadata"]["resourceVersion"] == "opaque/object"
        assert body["metadata"].get("namespace") == ("other" if definition.namespaced else None)
        assert (body["apiVersion"], body["kind"]) == (resource.api_version, resource.kind)


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
def test_actual_descriptor_projects_meaningful_typed_family_cells_and_derived_info(definition):
    resource, record = api(definition), row_record(definition)
    row = resource_row(record, definition, resource=resource)
    result = projected(definition, record)
    for key, (text, sort) in EXPECTED[definition.name].items():
        assert result[key].text == text and result[key].sort == sort
        assert type(result[key].sort) is type(sort)
    profile = supported_family(resource)
    assert profile is not None and definition.fields == profile.fields
    expected_keys = (
        *(("namespace",) if definition.namespaced else ()),
        "name",
        *(field.key for field in profile.fields),
        "info",
        "age",
    )
    assert tuple(result) == expected_keys
    assert result["name"].text == "owned-one" and row.uid == "owned-owned-one"
    extraction = curated_cells(resource, record)
    assert all(result[key] == value for key, value in extraction.values)
    assert result["info"].text == (" · ".join(extraction.notices) or "Object fields")[:256]
    assert row.cells(datetime(2026, 10, 8, tzinfo=UTC))[-1] == "7d"
    assert not any(
        canary in repr(row)
        for canary in (CANARY, ACCESS_CANARY, ANNOTATION_CANARY, CA_CANARY, *URL_CANARIES)
    )


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
def test_new_family_without_actual_descriptor_cannot_guess_a_supported_version(definition):
    row = resource_row(row_record(definition), definition)
    result = {
        column.key: value for column, value in zip(definition.columns, row.values, strict=True)
    }
    assert all(
        result[field.key].text == "—" and result[field.key].sort is None
        for field in definition.fields
    )
    assert result["info"].text == "Resource version unavailable"


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
@pytest.mark.parametrize("change", ["version", "kind", "scope"])
def test_unsupported_actual_schema_has_only_actual_metadata_info_and_age(definition, change):
    mutation = {
        "version": {"version": "v999"},
        "kind": {"kind": "Other"},
        "scope": {"namespaced": not definition.namespaced},
    }[change]
    resource = replace(api(definition), **mutation)
    fallback = definition_for_resource(resource)
    assert fallback is not None and fallback.curated and not fallback.fields
    assert fallback.namespaced == resource.namespaced
    body = manifest(definition)
    body.update(apiVersion=resource.api_version, kind=resource.kind)
    if resource.namespaced:
        body["metadata"]["namespace"] = "team"
    else:
        body["metadata"].pop("namespace", None)
    record = replace(
        resource_record(resource, body),
        server=ServerRow((ServerColumn("Credential", "string"),), (CANARY,), len(CANARY)),
    )
    row = resource_row(record, fallback, resource=resource)
    keys = tuple(column.key for column in fallback.columns)
    assert keys == (*(("namespace",) if resource.namespaced else ()), "name", "info", "age")
    assert "Unsupported" in row.values[-2].text
    assert CANARY not in repr(row) and "SYNTHETIC" not in repr(row)


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
def test_compact_rows_suppress_all_fields_and_untrusted_server_printer_values(definition):
    resource = api(definition)
    fallback = definition_for_resource(resource, metadata_only=True)
    assert fallback is not None and not fallback.fields
    record = replace(
        row_record(definition),
        metadata_only=True,
        server=ServerRow((ServerColumn("Credential", "string"),), (CANARY,), len(CANARY)),
    )
    row = resource_row(record, fallback, resource=resource)
    assert row.values[-2].text == "Metadata only; values unavailable"
    assert CANARY not in repr(row)
    assert len(row.values) == (4 if resource.namespaced else 3)
    full_shape = projected(definition, record)
    assert all(full_shape[field.key].sort is None for field in definition.fields)


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
def test_unrelated_same_plural_group_is_not_recognized_as_this_curated_family(definition):
    resource = replace(api(definition), group="unrelated.example.test")
    assert definition_for_resource(resource) is None
    row = resource_row(row_record(definition), definition, resource=resource)
    assert "Unsupported" in row.values[-2].text
    assert all(
        value.sort is None
        for column, value in zip(definition.columns, row.values, strict=True)
        if column in definition.fields
    )


@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
def test_supported_descriptor_rejects_a_contradictory_full_record_type(definition):
    expected = api(definition)
    other = replace(expected, kind="Other")
    body = manifest(definition)
    body["kind"] = "Other"
    record = resource_record(other, body)
    with pytest.raises(AppError):
        resource_row(record, definition, resource=expected)


@pytest.mark.parametrize("definition", LEGACY, ids=lambda definition: definition.name)
def test_old_fifteen_legacy_construction_and_explicit_descriptor_stay_equivalent(definition):
    record = row_record(definition)
    assert not definition.curated and definition_for_resource(api(definition)) is definition
    assert resource_row(record, definition) == resource_row(
        record, definition, resource=api(definition)
    )


def test_canonical_names_and_aliases_are_unambiguous_and_unknown_names_stay_unknown():
    declarations = [
        (alias, definition)
        for definition in STANDARD_RESOURCES
        for alias in (definition.name, *definition.aliases)
    ]
    assert len(declarations) == len(RESOURCE_ALIASES)
    assert all(RESOURCE_ALIASES[alias] is definition for alias, definition in declarations)
    assert definition_for_resource(replace(api(STANDARD_RESOURCES[0]), name="unregistered")) is None


def test_each_curated_fixture_is_independent_when_callers_modify_nested_data():
    for definition in CURATED:
        expected = manifest(definition)
        modified = manifest(definition)
        for value in modified.values():
            if isinstance(value, (dict, list)):
                value.clear()
        assert manifest(definition) == expected


def test_new_typed_sort_keeps_negative_priority_zero_and_unknown_last_in_both_directions():
    definition = RESOURCE_ALIASES["pc"]
    resource = api(definition)
    rows = tuple(
        resource_row(
            row_record(definition, name=name, overrides={"value": value}),
            definition,
            resource=resource,
        )
        for name, value in (("negative", -10), ("zero", 0), ("positive", 20), ("unknown", None))
    )
    index = next(
        index for index, column in enumerate(definition.columns) if column.key == "priority"
    )
    assert [row.name for row in order_resources(rows, index)] == [
        "negative",
        "zero",
        "positive",
        "unknown",
    ]
    assert [row.name for row in order_resources(rows, index, True)] == [
        "positive",
        "zero",
        "negative",
        "unknown",
    ]
