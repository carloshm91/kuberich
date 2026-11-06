"""Declared facts, exact bounded navigation, missing values and default concealment."""

import json
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from kuberich.domain.curated import MAX_CURATED_DETAIL_BYTES, MAX_CURATED_DETAIL_ROWS
from kuberich.domain.curated_navigation import (
    CollectionDestination,
    DeclaredObjectReference,
    LabelsMatch,
    ReferenceDestination,
)
from kuberich.domain.curated_policy import FAMILIES, cells, details
from kuberich.domain.registry import definition_for_resource, order_resources, resource_row
from kuberich.domain.resources import ResourceRecord, resource_record
from kuberich.domain.tables import TableDecoder
from kuberich.errors import AppError
from tests.support.curated_policy import (
    ANNOTATION_CANARY,
    CA_CANARY,
    URL_CANARIES,
    policy_manifest,
    policy_record,
)
from tests.support.resources import item, pod_resource

NAMES = (
    "networkpolicies",
    "endpointslices",
    "ingressclasses",
    "resourcequotas",
    "limitranges",
    "mutatingwebhookconfigurations",
    "validatingwebhookconfigurations",
)
FIELDS = (
    ("selector", "policy-types", "ingress-rules", "egress-rules"),
    ("address-type", "service", "endpoints", "ready", "not-ready", "unspecified", "ports"),
    ("controller", "default", "parameters-kind", "parameters-scope"),
    ("resources", "usage", "scopes", "exceeded"),
    ("types", "items", "defaults", "constraints"),
    (
        "webhooks",
        "review-versions",
        "failure-policies",
        "side-effects",
        "clients",
        "timeout-min",
        "timeout-max",
    ),
    (
        "webhooks",
        "review-versions",
        "failure-policies",
        "side-effects",
        "clients",
        "timeout-min",
        "timeout-max",
    ),
)


def values(name, manifest=None, ordinal=0):
    return dict(cells(*policy_record(name, ordinal, manifest=manifest)).values)


@pytest.mark.parametrize("name,expected", tuple(zip(NAMES, FIELDS, strict=True)))
def test_profiles_exact_columns_real_descriptor_and_nontrivial_typed_rows(name, expected):
    assert tuple(family.resource for family in FAMILIES) == NAMES
    resource, record = policy_record(name)
    projected = cells(resource, record)
    assert tuple(key for key, _ in projected.values) == expected
    assert any(value.sort is not None for _, value in projected.values)
    assert projected != cells(*policy_record(name, 1))
    inspected = details(resource, record)
    assert inspected.sections and inspected.links
    assert record.manifest == policy_manifest(name)
    serialized = json.dumps((asdict(projected), asdict(inspected)), default=str)
    assert not any(canary in serialized for canary in (CA_CANARY, ANNOTATION_CANARY, *URL_CANARIES))
    assert all(len(value.text) <= 256 for _, value in projected.values)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "change", ["version", "group", "kind", "scope", "metadata-only", "contradiction", "normalized"]
)
def test_exact_descriptor_metadata_only_and_normalized_transport_contract(name, change):
    resource, record = policy_record(name)
    if change == "normalized":
        manifest = record.manifest
        del manifest["apiVersion"], manifest["kind"]
        normalized = resource_record(resource, manifest)
        assert cells(resource, normalized) == cells(resource, record)
        return
    if change == "metadata-only":
        record = replace(record, metadata_only=True)
    elif change == "contradiction":
        record = ResourceRecord(
            record.name,
            record.uid,
            record.namespace,
            record.resource_version,
            record.created_at,
            json.dumps({**record.manifest, "kind": "Other"}).encode(),
        )
    else:
        field, value = {
            "version": ("version", "v999"),
            "group": ("group", "other.example.test"),
            "kind": ("kind", "Other"),
            "scope": ("namespaced", not resource.namespaced),
        }[change]
        resource = replace(resource, **{field: value})
    with pytest.raises(AppError):
        cells(resource, record)
    with pytest.raises(AppError):
        details(resource, record)


def test_network_policy_default_and_full_selector_predicate_are_namespace_scoped():
    resource, record = policy_record("networkpolicies")
    selected = next(
        link.destination for link in details(resource, record).links if link.key == "selected-pods"
    )
    assert isinstance(selected, CollectionDestination) and selected.namespace == "team"
    assert isinstance(selected.predicate, LabelsMatch)
    pod = item()
    pod["metadata"]["labels"] = {"app": "owned", "role": "api"}
    assert selected.predicate.matches(pod_resource(), resource_record(pod_resource(), pod))
    pod["metadata"]["labels"]["role"] = "other"
    assert not selected.predicate.matches(pod_resource(), resource_record(pod_resource(), pod))
    expected = values("networkpolicies")
    assert expected["policy-types"].text == "Egress, Ingress"
    assert expected["ingress-rules"].sort == expected["egress-rules"].sort == 1
    missing = values("networkpolicies", ordinal=1)
    assert missing["selector"].text == "all namespace Pods"
    assert missing["policy-types"].text == "Ingress"
    assert missing["ingress-rules"].sort == missing["egress-rules"].sort == 0


def test_endpoint_counts_observed_flags_and_exact_uid_targets_never_infer_from_addresses():
    resource, record = policy_record("endpointslices")
    result = dict(cells(resource, record).values)
    assert [result[key].sort for key in ("endpoints", "ready", "not-ready", "unspecified")] == [
        3,
        1,
        1,
        1,
    ]
    assert "all ports" in result["ports"].text
    inspected = details(resource, record)
    targets = [link for link in inspected.links if link.key.startswith("target-")]
    assert isinstance(targets[0].destination, ReferenceDestination)
    assert targets[0].destination.require_uid and targets[0].destination.ref.uid == "exact-pod-uid"
    assert targets[1].destination is targets[2].destination is None
    assert any("not Pod health" in note for note in inspected.notices)


def test_owned_api_null_endpoints_shape_matches_full_table_and_retains_raw_manifest():
    # Faithful field shape from owned kind005 GET and embedded full-object Table;
    # identities are synthetic, and no ignored runtime artifact is read by tests.
    manifest = {
        "apiVersion": "discovery.k8s.io/v1",
        "kind": "EndpointSlice",
        "metadata": {
            "name": "owned-empty",
            "namespace": "team",
            "uid": "synthetic-empty-slice",
            "resourceVersion": "owned-rv",
            "labels": {"kubernetes.io/service-name": "owned-service"},
        },
        "addressType": "IPv4",
        "endpoints": None,
        "ports": [{"name": "http", "port": 8080, "protocol": "TCP"}],
    }
    resource, record = policy_record("endpointslices", manifest=manifest)
    table = {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "Table",
        "columnDefinitions": [{"name": "Name", "type": "string"}],
        "rows": [{"object": manifest, "cells": ["owned-empty"]}],
    }
    (converted,) = TableDecoder(resource, "team").records(table)
    assert cells(resource, record) == cells(resource, converted)
    result = dict(cells(resource, converted).values)
    assert [result[key].sort for key in ("endpoints", "ready", "not-ready", "unspecified")] == [
        0,
        0,
        0,
        0,
    ]
    assert result["ports"].text == "http:8080/TCP"
    inspected = details(resource, converted)
    assert (
        next(
            section for section in inspected.sections if section.title == "Observed endpoints"
        ).rows
        == ()
    )
    assert not any("malformed" in notice or "unavailable" in notice for notice in inspected.notices)
    assert record.manifest["endpoints"] is converted.manifest["endpoints"] is None


@pytest.mark.parametrize("field", ["endpoints", "ports"])
@pytest.mark.parametrize("form", ["omitted", "null", "empty"])
def test_only_optional_slice_collections_default_to_known_empty_with_zero_membership(field, form):
    manifest = policy_manifest("endpointslices")
    if form == "omitted":
        manifest.pop(field)
    else:
        manifest[field] = None if form == "null" else []
    resource, record = policy_record("endpointslices", manifest=manifest)
    result = dict(cells(resource, record).values)
    inspected = details(resource, record)
    if field == "endpoints":
        assert [result[key].sort for key in ("endpoints", "ready", "not-ready", "unspecified")] == [
            0,
            0,
            0,
            0,
        ]
        assert (
            next(
                section for section in inspected.sections if section.title == "Observed endpoints"
            ).rows
            == ()
        )
        assert not any(link.key.startswith("target-") for link in inspected.links)
    else:
        assert result["ports"].text == "none declared"
        assert (
            next(
                section for section in inspected.sections if section.title == "Declared ports"
            ).rows
            == ()
        )
        assert [result[key].sort for key in ("endpoints", "ready", "not-ready", "unspecified")] == [
            3,
            1,
            1,
            1,
        ]
        target = next(link for link in inspected.links if link.key == "target-0")
        assert isinstance(target.destination, ReferenceDestination)
        assert target.destination.ref.uid == "exact-pod-uid"
    assert not any("malformed" in notice or "unavailable" in notice for notice in inspected.notices)


def test_null_port_entry_is_all_ports_separate_from_empty_ports_collection():
    manifest = policy_manifest("endpointslices")
    manifest["ports"] = [{"name": "all", "port": None, "protocol": "TCP"}]
    resource, record = policy_record("endpointslices", manifest=manifest)
    assert dict(cells(resource, record).values)["ports"].text == "all:all ports/TCP"
    rows = next(
        section
        for section in details(resource, record).sections
        if section.title == "Declared ports"
    ).rows
    assert rows == (("all", "all ports", "TCP"),)


def test_api_defined_empty_zero_sorts_before_observed_count_and_unknown_stays_last_both_directions():
    manifests = [policy_manifest("endpointslices") for _ in range(3)]
    manifests[0]["endpoints"] = None
    manifests[2]["endpoints"] = "malformed"
    rows = []
    for index, manifest in enumerate(manifests):
        manifest["metadata"].update(name=f"owned-{index}", uid=f"slice-{index}")
        resource, record = policy_record("endpointslices", manifest=manifest)
        definition = definition_for_resource(resource)
        assert definition is not None
        rows.append(resource_row(record, definition, resource=resource))
    column = next(
        index for index, field in enumerate(definition.columns) if field.key == "endpoints"
    )
    assert [row.uid for row in order_resources(tuple(rows), column, False)] == [
        "slice-0",
        "slice-1",
        "slice-2",
    ]
    assert [row.uid for row in order_resources(tuple(rows), column, True)] == [
        "slice-1",
        "slice-0",
        "slice-2",
    ]


@pytest.mark.parametrize("field", ["endpoints", "ports"])
@pytest.mark.parametrize("malformed", [False, 0, "", "invalid", {}])
def test_optional_slice_default_never_coerces_other_falsy_or_scalar_fields_to_zero(
    field, malformed
):
    manifest = policy_manifest("endpointslices")
    manifest[field] = malformed
    result = values("endpointslices", manifest)
    assert result[field].sort is None


def test_required_endpoint_addresses_remain_unknown_when_null_despite_optional_list_defaults():
    manifest = policy_manifest("endpointslices")
    manifest["endpoints"][0]["addresses"] = None
    resource, record = policy_record("endpointslices", manifest=manifest)
    inspected = details(resource, record)
    row = next(
        section for section in inspected.sections if section.title == "Observed endpoints"
    ).rows[0]
    assert row[1] == "—"
    assert any("collection" in notice for notice in inspected.notices)


def test_ingress_class_reduces_one_annotation_and_leaves_group_kind_resolution_to_discovery():
    resource, record = policy_record("ingressclasses")
    assert dict(cells(resource, record).values)["default"].sort == 1
    links = {link.key: link for link in details(resource, record).links}
    target = links["parameters"].destination
    assert isinstance(target, ReferenceDestination) and isinstance(
        target.ref, DeclaredObjectReference
    )
    assert target.ref.group == "" and target.ref.version is None and target.ref.kind == "ConfigMap"
    assert target.ref.namespace == "team"
    collection = links["ingresses"].destination
    assert collection.scope == "selected-namespace" and collection.namespace is None
    _, cluster = policy_record("ingressclasses", 1)
    target = next(
        link.destination for link in details(resource, cluster).links if link.key == "parameters"
    )
    assert target.ref.namespace is None


def test_quota_uses_enforced_hard_per_dimension_and_handles_zero_denominator():
    resource, record = policy_record("resourcequotas")
    result = dict(cells(resource, record).values)
    assert result["resources"].sort == 3 and result["exceeded"].sort == 1
    rows = {row[0]: row for row in details(resource, record).sections[0].rows}
    assert rows["cpu"][1:4] == ("2", "1000m", "1500m")
    assert Decimal(rows["cpu"][4]) == Decimal("-0.5")
    assert Decimal(rows["cpu"][5].removesuffix("%")) == Decimal("150")
    assert rows["pods"][3] == "0" and rows["pods"][5] == "undefined (hard=0)"
    assert Decimal(rows["memory"][5].removesuffix("%")) == Decimal("50")
    assert values("resourcequotas", ordinal=1)["exceeded"].sort == 0


def test_limit_items_preserve_duplicate_type_resource_identity_and_separate_ratios():
    manifest = policy_manifest("limitranges")
    manifest["spec"]["limits"].append(deepcopy(manifest["spec"]["limits"][0]))
    inspected = details(*policy_record("limitranges", manifest=manifest))
    rows = inspected.sections[0].rows
    assert [row[0] for row in rows] == ["0", "1", "2"]
    assert rows[0][1:3] == rows[2][1:3] == ("Container", "cpu")
    assert rows[0][-1] == "2" and "dimensionless" in inspected.sections[0].columns[-1]
    assert {
        link.destination.resource
        for link in inspected.links
        if isinstance(link.destination, CollectionDestination)
    } == {"pods", "persistentvolumeclaims"}


@pytest.mark.parametrize("name", NAMES[-2:])
def test_webhook_classifies_safe_clients_without_retaining_url_or_ca_payload(name):
    resource, record = policy_record(name)
    result = dict(cells(resource, record).values)
    assert result["webhooks"].sort == 2
    assert result["timeout-min"].sort == 7 and result["timeout-max"].sort == 20
    assert result["clients"].text == "Service, URL (not fetched)"
    inspected = details(resource, record)
    service = next(link.destination for link in inspected.links if link.key == "service-0")
    assert service.ref.name == "owned-webhook" and service.ref.namespace == "team"
    assert next(link for link in inspected.links if link.key == "client-1").destination is None
    assert all("concealed" in row[3] for row in inspected.sections[0].rows)


@pytest.mark.parametrize("name", NAMES)
def test_missing_fields_are_unknown_not_fabricated_zero(name):
    manifest = policy_manifest(name)
    for key in tuple(manifest):
        if key not in {"apiVersion", "kind", "metadata"}:
            del manifest[key]
    result = values(name, manifest)
    assert any(value.sort is None for value in result.values())
    assert cells(*policy_record(name, manifest=manifest)).notices


def test_safe_output_bounds_and_full_action_identity_are_independent():
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["podSelector"] = {"matchLabels": {f"key{i}": "v" * 60 for i in range(100)}}
    resource, record = policy_record("networkpolicies", manifest=manifest)
    assert len(dict(cells(resource, record).values)["selector"].text) == 256
    selected = details(resource, record).links[0].destination.predicate.selector
    assert len(selected.requirements) == 100 and selected.requirements[-1].values == ("v" * 60,)
    manifest = policy_manifest("endpointslices")
    manifest["endpoints"] *= 200
    inspected = details(*policy_record("endpointslices", manifest=manifest))
    assert (
        sum(len(section.rows) for section in inspected.sections) + len(inspected.links)
        <= MAX_CURATED_DETAIL_ROWS
    )
    assert len(json.dumps(asdict(inspected)).encode()) <= MAX_CURATED_DETAIL_BYTES
    assert any(section.omitted_rows for section in inspected.sections)


@pytest.mark.parametrize(
    "selector",
    [
        None,
        [],
        {"unknown": "field"},
        {"matchLabels": {"bad/key!": "x"}},
        {"matchExpressions": [{"key": "app", "operator": "In", "values": []}]},
    ],
)
def test_malformed_policy_selector_disables_action_instead_of_defaulting_all(selector):
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["podSelector"] = selector
    resource, record = policy_record("networkpolicies", manifest=manifest)
    assert dict(cells(resource, record).values)["selector"].sort is None
    link = details(resource, record).links[0]
    assert link.destination is None and link.unavailable_reason


@pytest.mark.parametrize("types", [None, "Egress", ["unknown"], [[]]])
def test_invalid_policy_types_remain_unknown(types):
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["policyTypes"] = types
    assert values("networkpolicies", manifest)["policy-types"].sort is None


def test_explicit_egress_only_with_no_rules_and_malformed_default_inputs_are_distinct():
    manifest = policy_manifest("networkpolicies", 1)
    manifest["spec"].update(policyTypes=["Egress"], egress=[])
    result = values("networkpolicies", manifest)
    assert result["policy-types"].text == "Egress" and result["egress-rules"].sort == 0
    manifest["spec"].update(policyTypes=[], egress=None, ingress=None)
    result = values("networkpolicies", manifest)
    assert (
        result["policy-types"].sort
        is result["ingress-rules"].sort
        is result["egress-rules"].sort
        is None
    )


@pytest.mark.parametrize(
    "port,valid",
    [
        ({}, True),
        ({"port": 1}, True),
        ({"port": 65535}, True),
        ({"port": 0}, False),
        ({"port": True}, False),
        ({"port": "bad/name"}, False),
        ({"endPort": 4}, False),
        ({"port": 5, "endPort": 4}, False),
        ({"port": 5, "endPort": 6}, True),
        ({"protocol": []}, False),
        (None, False),
    ],
)
def test_policy_port_declarations_never_turn_malformed_values_into_all_ports(port, valid):
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["ingress"] = [{"ports": [port]}]
    section = next(
        section
        for section in details(*policy_record("networkpolicies", manifest=manifest)).sections
        if section.title == "Ingress rules (declared)"
    )
    assert ("invalid port" not in section.rows[0][-1]) == valid


def test_policy_malformed_rules_peers_strings_and_bounded_summaries_stay_explicit():
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["ingress"] = [
        None,
        {"from": None, "ports": None},
        {"from": [None, {"ipBlock": {"cidr": "192.0.2.0/24", "except": [None]}}]},
        {"from": [{}] * 17, "ports": [{}] * 17},
    ]
    inspected = details(*policy_record("networkpolicies", manifest=manifest))
    rendered = repr(inspected)
    assert "invalid rule" in rendered and "invalid peer" in rendered
    assert "first16" in rendered and "—" in rendered


@pytest.mark.parametrize(
    "field,value",
    [
        ("endpoints", "malformed"),
        ("endpoints", [None]),
        ("endpoints", [{}] * 1001),
        ("ports", "malformed"),
        ("ports", [{}] * 101),
        ("addressType", "future-address-type"),
    ],
)
def test_endpoint_malformed_and_excessive_sources_do_not_create_healthy_counts(field, value):
    manifest = policy_manifest("endpointslices")
    manifest[field] = value
    resource, record = policy_record("endpointslices", manifest=manifest)
    result = dict(cells(resource, record).values)
    assert cells(resource, record).notices
    if field == "endpoints":
        assert (
            result["ready"].sort is result["not-ready"].sort is result["unspecified"].sort is None
        )
    elif field == "ports":
        assert result["ports"].sort is None
    else:
        assert result["address-type"].text == value


@pytest.mark.parametrize(
    "condition", [None, {"ready": "yes"}, {"ready": []}, {"ready": True, "serving": "invalid"}]
)
def test_endpoint_condition_shapes_and_missing_target_uid_do_not_enable_guessed_links(condition):
    manifest = policy_manifest("endpointslices")
    manifest["endpoints"][0]["conditions"] = condition
    del manifest["endpoints"][0]["targetRef"]["uid"]
    inspected = details(*policy_record("endpointslices", manifest=manifest))
    assert all(
        link.destination is None for link in inspected.links if link.key.startswith("target-")
    )


def test_endpoint_port_zero_is_invalid_and_empty_port_list_is_an_explicit_declaration():
    manifest = policy_manifest("endpointslices")
    manifest["ports"] = [{"port": 0}, {"protocol": "future"}]
    assert "invalid" in values("endpointslices", manifest)["ports"].text
    assert values("endpointslices", ordinal=1)["ports"].text == "none declared"
    manifest["metadata"]["labels"]["kubernetes.io/service-name"] = "invalid/name"
    link = details(*policy_record("endpointslices", manifest=manifest)).links[0]
    assert link.destination is None and link.unavailable_reason


@pytest.mark.parametrize("annotation", [None, True, "TRUE", []])
def test_only_recognized_ingress_default_boolean_strings_are_projected(annotation):
    manifest = policy_manifest("ingressclasses")
    manifest["metadata"]["annotations"]["ingressclass.kubernetes.io/is-default-class"] = annotation
    assert values("ingressclasses", manifest)["default"].sort is None


@pytest.mark.parametrize(
    "parameters",
    [
        "invalid",
        {"kind": "ConfigMap"},
        {"name": "owned", "kind": []},
        {"name": "owned", "kind": "Bad/Kind"},
        {"name": "owned", "kind": "ConfigMap", "apiGroup": 0},
        {"name": "owned", "kind": "ConfigMap", "scope": "future"},
        {"name": "owned", "kind": "ConfigMap", "scope": "Namespace"},
        {"name": "owned", "kind": "ConfigMap", "scope": "Cluster", "namespace": "team"},
    ],
)
def test_ingress_parameter_identity_scope_and_group_fail_closed(parameters):
    manifest = policy_manifest("ingressclasses")
    manifest["spec"]["parameters"] = parameters
    link = next(
        link
        for link in details(*policy_record("ingressclasses", manifest=manifest)).links
        if link.key == "parameters"
    )
    assert link.destination is None and link.unavailable_reason


def test_ingress_no_parameters_group_only_and_invalid_source_name_are_honest():
    manifest = policy_manifest("ingressclasses", 1)
    manifest["spec"]["parameters"]["apiGroup"] = "parameters.synthetic.example.test"
    resource, record = policy_record("ingressclasses", manifest=manifest)
    target = next(
        link.destination for link in details(resource, record).links if link.key == "parameters"
    )
    assert target.ref.group == "parameters.synthetic.example.test" and target.ref.version is None
    del manifest["spec"]["parameters"]["apiGroup"]
    assert (
        next(
            link.destination
            for link in details(*policy_record("ingressclasses", manifest=manifest)).links
            if link.key == "parameters"
        ).ref.group
        == ""
    )
    del manifest["spec"]["parameters"]
    manifest["metadata"]["name"] = "invalid name"
    inspected = details(*policy_record("ingressclasses", manifest=manifest))
    assert inspected.links[0].destination is None
    assert any("No parameters" in note for note in inspected.notices)


@pytest.mark.parametrize("used", [None, True, "NaN", "-1", "x", "9" * 65])
def test_quota_unknown_usage_never_becomes_zero_or_spec_based_enforcement(used):
    manifest = policy_manifest("resourcequotas")
    manifest["status"]["used"]["cpu"] = used
    result = values("resourcequotas", manifest)
    assert result["exceeded"].sort is None and "cpu: —/1000m" in result["usage"].text


def test_quota_partial_status_and_large_resource_maps_remain_incomplete():
    manifest = policy_manifest("resourcequotas")
    del manifest["status"]["used"]
    assert values("resourcequotas", manifest)["exceeded"].sort is None
    manifest["spec"]["scopes"] = None
    assert values("resourcequotas", manifest)["scopes"].sort is None
    manifest["spec"]["hard"] = {f"count/resource{i}": "0" for i in range(257)}
    inspected = details(*policy_record("resourcequotas", manifest=manifest))
    assert inspected.sections[0].omitted_rows > 0


def test_quota_desired_hard_absence_does_not_discard_observed_enforced_comparison():
    manifest = policy_manifest("resourcequotas")
    del manifest["spec"]["hard"]
    result = values("resourcequotas", manifest)
    assert result["exceeded"].sort == 1
    assert "PriorityClass" in result["scopes"].text
    del manifest["spec"]["scopes"]
    assert "PriorityClass" in values("resourcequotas", manifest)["scopes"].text
    manifest["spec"]["scopeSelector"] = "malformed"
    assert values("resourcequotas", manifest)["scopes"].sort is None
    manifest["spec"]["scopeSelector"] = {"matchExpressions": None}
    assert values("resourcequotas", manifest)["scopes"].sort is None


@pytest.mark.parametrize("client", [None, "malformed"])
def test_malformed_webhook_client_does_not_claim_a_system_root_source(client):
    manifest = policy_manifest("mutatingwebhookconfigurations", 1)
    manifest["webhooks"][0]["clientConfig"] = client
    inspected = details(*policy_record("mutatingwebhookconfigurations", manifest=manifest))
    assert inspected.sections[0].rows[0][3] == "unknown CA source"


@pytest.mark.parametrize(
    "limits", [[], [None], [{"type": "future-type"}], [{"type": "Container", "default": "invalid"}]]
)
def test_empty_and_malformed_limit_items_do_not_fabricate_defaults(limits):
    manifest = policy_manifest("limitranges")
    manifest["spec"]["limits"] = limits
    result = values("limitranges", manifest)
    assert result["items"].sort == len(limits)
    assert (result["defaults"].sort is not None) == (limits == [])


def test_limit_detail_work_and_omissions_are_bounded_across_nested_items():
    manifest = policy_manifest("limitranges")
    manifest["spec"]["limits"] = [
        {"type": "Container", "max": {f"resource{i}": "0" for i in range(200)}}
    ] * 3
    inspected = details(*policy_record("limitranges", manifest=manifest))
    assert sum(len(section.rows) for section in inspected.sections) + len(inspected.links) <= 256
    assert inspected.sections[0].omitted_rows > 0


@pytest.mark.parametrize("timeout", [0, 31, True, "3"])
def test_webhook_invalid_timeout_never_supplies_a_numeric_minimum(timeout):
    manifest = policy_manifest("validatingwebhookconfigurations")
    manifest["webhooks"][0]["timeoutSeconds"] = timeout
    result = values("validatingwebhookconfigurations", manifest)
    assert result["timeout-min"].sort is result["timeout-max"].sort is None


@pytest.mark.parametrize(
    "client",
    [
        {},
        {"url": ""},
        {"service": {"name": "owned", "namespace": None}},
        {
            "service": {"name": "owned", "namespace": "team"},
            "url": "https://never-contact.example.test",
        },
        {"url": "https://never-contact.example.test", "caBundle": []},
        {"url": "https://never-contact.example.test", "caBundle": ""},
    ],
)
def test_webhook_client_classification_and_ca_shape_never_expose_or_fetch_urls(client):
    manifest = policy_manifest("mutatingwebhookconfigurations", 1)
    manifest["webhooks"][0]["clientConfig"] = client
    inspected = details(*policy_record("mutatingwebhookconfigurations", manifest=manifest))
    assert "never-contact" not in repr(inspected)
    assert any(link.destination is None for link in inspected.links)


def test_webhook_defaults_unknown_capabilities_malformed_items_and_rule_bounds():
    manifest = policy_manifest("mutatingwebhookconfigurations", 1)
    hook = manifest["webhooks"][0]
    del hook["timeoutSeconds"], hook["failurePolicy"]
    hook.update(
        sideEffects="future",
        matchPolicy="future",
        admissionReviewVersions=[None],
        rules=[None] * 256,
    )
    result = values("mutatingwebhookconfigurations", manifest)
    assert result["timeout-min"].sort == result["timeout-max"].sort == 10
    assert result["failure-policies"].text == "Fail"
    manifest["webhooks"] = [hook, hook]
    inspected = details(*policy_record("mutatingwebhookconfigurations", manifest=manifest))
    assert any(section.omitted_rows for section in inspected.sections)
    assert any("unknown webhook capability" in note for note in inspected.notices)
    manifest["webhooks"] = [None]
    assert values("mutatingwebhookconfigurations", manifest)["timeout-min"].sort is None
    manifest["webhooks"] = []
    result = values("mutatingwebhookconfigurations", manifest)
    assert result["webhooks"].sort == 0 and result["timeout-min"].sort is None


def test_oversized_valid_selector_disables_action_without_clipping_predicate_identity():
    manifest = policy_manifest("networkpolicies")
    manifest["spec"]["podSelector"] = {"matchLabels": {f"key{i:04}": "v" * 63 for i in range(1000)}}
    inspected = details(*policy_record("networkpolicies", manifest=manifest))
    assert inspected.links[0].destination is None
    assert "payload bound" in inspected.links[0].unavailable_reason
    assert len(json.dumps(asdict(inspected)).encode()) < MAX_CURATED_DETAIL_BYTES


def test_allowed_text_controls_and_credential_fragments_are_inert_before_clipping():
    manifest = policy_manifest("ingressclasses")
    manifest["spec"]["controller"] = "\x1b[31m token=synthetic-private " + "x" * 500
    result = values("ingressclasses", manifest)
    assert (
        "\x1b" not in result["controller"].text
        and "synthetic-private" not in result["controller"].text
    )
    assert len(result["controller"].text) == 256


def test_serialized_action_and_row_budget_charges_escaped_unicode_identity():
    manifest = policy_manifest("endpointslices")
    endpoint = manifest["endpoints"][0]
    endpoint["targetRef"]["uid"] = "u" + "界" * 252
    manifest["endpoints"] = [endpoint] * 600
    inspected = details(*policy_record("endpointslices", manifest=manifest))
    assert len(json.dumps(asdict(inspected)).encode()) <= MAX_CURATED_DETAIL_BYTES
    assert all(
        link.destination.ref.uid == "u" + "界" * 252
        for link in inspected.links
        if isinstance(link.destination, ReferenceDestination) and link.destination.require_uid
    )


def test_bounded_address_summary_retains_an_explicit_omission_notice_not_extra_endpoints():
    manifest = policy_manifest("endpointslices")
    manifest["endpoints"] = [manifest["endpoints"][0]]
    manifest["endpoints"][0]["addresses"] = [f"192.0.2.{index}" for index in range(1, 21)]
    resource, record = policy_record("endpointslices", manifest=manifest)
    assert dict(cells(resource, record).values)["endpoints"].sort == 1
    inspected = details(resource, record)
    assert "… +4" in inspected.sections[0].rows[0][1]
    assert any("String summary entries" in note for note in inspected.notices)
