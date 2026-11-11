"""Scaling facts preserve versions, uncertainty, literal identity and bounded output."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kuberich.domain.curated import MAX_CURATED_DETAIL_BYTES, MAX_CURATED_DETAIL_ROWS
from kuberich.domain.curated_navigation import CollectionDestination, ReferenceDestination
from kuberich.domain.curated_scaling import FAMILIES, cells, details
from kuberich.errors import AppError
from tests.support.curated_scaling import SAMPLES, TARGET, api, record


def values(resource, item):
    return dict(cells(resource, item).values)


def section(result, title):
    return next(item for item in result.sections if item.title == title)


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize(
    "generation,observed,expected",
    [
        (4, 4, "Current generation"),
        (4, 3, "Stale generation"),
        (4, None, "Unknown generation"),
        (None, 4, "Unknown generation"),
        (True, 4, "Unknown generation"),
    ],
)
def test_hpa_generation_provenance_does_not_replace_observed_replica_values(
    version, generation, observed, expected
):
    resource = api("HorizontalPodAutoscaler", version)
    item = record(
        resource,
        {"status": {"observedGeneration": observed, "currentReplicas": 2, "desiredReplicas": 3}},
        metadata={"generation": generation},
    )
    result = details(resource, item)
    assert dict(section(result, "Observation").rows)["Generation provenance"] == expected
    assert values(resource, item)["current"].sort == 2
    assert values(resource, item)["desired"].sort == 3
    assert any("not timing guarantees" in notice for notice in result.notices)
    assert any(part.title == "Scaling behavior (v2 declarations)" for part in result.sections) is (
        version == "v2"
    )


def test_hpa_v2_behavior_preserves_declared_zero_disabled_policy_velocity_and_tolerance():
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {
                "behavior": {
                    "scaleUp": {
                        "selectPolicy": "Disabled",
                        "stabilizationWindowSeconds": 0,
                        "tolerance": "0",
                        "policies": [{"type": "Pods", "value": 4, "periodSeconds": 15}],
                    },
                    "scaleDown": {
                        "selectPolicy": "Min",
                        "stabilizationWindowSeconds": 3600,
                        "tolerance": "0.05",
                        "policies": [{"type": "Percent", "value": 100, "periodSeconds": 1800}],
                    },
                }
            }
        },
    )
    rows = section(details(resource, item), "Scaling behavior (v2 declarations)").rows
    assert ("scaleUp", "selectPolicy", "Disabled", "Declared") in rows
    assert ("scaleUp", "stabilizationWindowSeconds", "0", "Declared") in rows
    assert ("scaleDown", "stabilizationWindowSeconds", "3600", "Declared") in rows
    assert ("scaleUp", "policy 0", "Pods: 4 per 15s", "Declared velocity constraint") in rows
    assert (
        "scaleDown",
        "policy 0",
        "Percent: 100 per 1800s",
        "Declared velocity constraint",
    ) in rows
    assert any(row[1:3] == ("tolerance (ratio)", "0") for row in rows)
    assert any(row[1:3] == ("tolerance (ratio)", "0.05") for row in rows)


@pytest.mark.parametrize(
    "behavior",
    [
        None,
        [],
        {"scaleUp": None},
        {"scaleDown": {}},
        {"scaleUp": {"policies": None}},
        {"scaleUp": {"policies": []}},
        {"scaleUp": {"policies": "invalid"}},
    ],
)
def test_hpa_missing_behavior_remains_distinct_from_zero_or_a_controller_timing_observation(
    behavior,
):
    resource = api("HorizontalPodAutoscaler")
    item = record(resource, {"spec": {"behavior": behavior}})
    rows = section(details(resource, item), "Scaling behavior (v2 declarations)").rows
    assert rows
    assert any(
        "omitted" in row[2] or "Malformed" in row[3] or row[1] == "policy count" for row in rows
    )
    assert all(row[2] != "0" for row in rows if row[1] == "stabilizationWindowSeconds")


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {},
        {"type": "Future", "value": 1, "periodSeconds": 1},
        {"type": "Pods", "value": 0, "periodSeconds": 1},
        {"type": "Pods", "value": 1, "periodSeconds": 0},
        {"type": "Pods", "value": True, "periodSeconds": 1},
        {"type": "Pods", "value": 1, "periodSeconds": 1801},
    ],
)
def test_hpa_malformed_velocity_and_other_behavior_fields_never_become_valid_constraints(policy):
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {
                "behavior": {
                    "scaleUp": {
                        "selectPolicy": "Future",
                        "stabilizationWindowSeconds": 3601,
                        "tolerance": "-0.1",
                        "policies": [policy],
                    }
                }
            }
        },
    )
    rows = section(details(resource, item), "Scaling behavior (v2 declarations)").rows
    assert ("scaleUp", "selectPolicy", "—", "Declared") in rows
    assert ("scaleUp", "stabilizationWindowSeconds", "—", "Declared") in rows
    assert any(row[1:3] == ("tolerance (ratio)", "—") for row in rows)
    assert ("scaleUp", "policy 0", "—", "Malformed declaration") in rows


def test_hpa_excess_behavior_entries_share_the_existing_complete_detail_budget():
    resource = api("HorizontalPodAutoscaler")
    rules = {"policies": [{"type": "Pods", "value": 1, "periodSeconds": 1}] * 300}
    item = record(resource, {"spec": {"behavior": {"scaleUp": rules, "scaleDown": rules}}})
    result = details(resource, item)
    assert (
        sum(len(part.rows) for part in result.sections) + len(result.links)
        <= MAX_CURATED_DETAIL_ROWS
    )
    assert len(json.dumps(asdict(result)).encode()) < MAX_CURATED_DETAIL_BYTES
    assert any(part.omitted_rows for part in result.sections)


@pytest.mark.parametrize("family", FAMILIES, ids=lambda item: item.kind)
def test_real_families_publish_exact_columns_meaningful_details_and_no_unlisted_payload(family):
    resource = api(family.kind)
    item = record(resource, {"unlisted": "synthetic-freeform-canary"})
    observed = cells(resource, item)
    assert tuple(key for key, _ in observed.values) == tuple(column.key for column in family.fields)
    assert all(value.sort is not None for key, value in observed.values if key != "max-unavailable")
    result = details(resource, item)
    assert len(result.links) >= 1
    assert all(len(row) == len(part.columns) for part in result.sections for row in part.rows)
    output = str((observed, result))
    assert "synthetic-freeform-canary" not in output
    assert "synthetic-description-not-for-default-display" not in output
    assert sum(len(part.rows) for part in result.sections) <= MAX_CURATED_DETAIL_ROWS


@pytest.mark.parametrize("kind", tuple(SAMPLES))
def test_absent_fields_are_unknown_and_are_not_server_column_fallbacks(kind):
    resource = api(kind)
    observed = values(resource, record(resource, sample=False))
    assert any(value.sort is None for value in observed.values())
    assert details(resource, record(resource, sample=False)).sections


@pytest.mark.parametrize(
    "change",
    [
        {"group": "other.example"},
        {"version": "v9"},
        {"name": "secrets"},
        {"kind": "Other"},
        {"namespaced": False},
    ],
)
def test_unsupported_descriptors_never_extract_fields(change):
    resource = api("HorizontalPodAutoscaler")
    item = record(resource)
    for operation in (cells, details):
        with pytest.raises(AppError):
            operation(replace(resource, **change), item)


@pytest.mark.parametrize("manifest", [{"kind": "Other"}, {"apiVersion": "wrong/v1"}])
def test_contradictory_records_rejected_but_normalized_missing_type_is_accepted(manifest):
    resource = api("Lease")
    item = record(resource)
    raw = item.manifest
    raw.update(manifest)
    bad = replace(item, _manifest=json.dumps(raw).encode())
    for operation in (cells, details):
        with pytest.raises(AppError):
            operation(resource, bad)
        with pytest.raises(AppError):
            operation(resource, replace(item, metadata_only=True))
    raw.pop("kind", None)
    raw.pop("apiVersion", None)
    assert cells(resource, replace(item, _manifest=json.dumps(raw).encode())) == cells(
        resource, item
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        (-(2**31), -(2**31)),
        (0, 0),
        (2**31 - 1, 2**31 - 1),
        (-(2**31) - 1, None),
        (2**31, None),
        (True, None),
        ("1", None),
        (None, None),
    ],
)
def test_priority_signed_int32_order_and_boolean_rejection(raw, expected):
    resource = api("PriorityClass")
    assert values(resource, record(resource, {"value": raw}))["priority"].sort == expected


@pytest.mark.parametrize("raw,expected", [(False, 0), (True, 1), (0, None), (None, None)])
def test_global_default_requires_boolean_and_preserves_false(raw, expected):
    resource = api("PriorityClass")
    assert (
        values(resource, record(resource, {"globalDefault": raw}))["global-default"].sort
        == expected
    )


def test_priority_defaults_are_authored_provenance_and_usedby_preserves_selected_scope():
    resource = api("PriorityClass")
    result = details(resource, record(resource, {"value": 0}, sample=False))
    rows = dict(section(result, "Defaults and description").rows)
    assert rows["Global default provenance"] == "API default: false"
    assert rows["Preemption provenance"] == "API default: PreemptLowerPriority"
    assert rows["Description"] == "Not declared"
    assert result.links[0].destination.mode.value == "usedby"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, (0, 0.0)),
        (4, (0, 4.0)),
        ("50%", (1, 50.0)),
        ("100%", (1, 100.0)),
        ("101%", None),
        ("1000%", None),
        ("1", None),
        (True, None),
        (-1, None),
        (2**31, None),
        (None, None),
    ],
)
def test_pdb_count_and_percent_sorts_have_distinct_tags(raw, expected):
    resource = api("PodDisruptionBudget")
    observed = values(resource, record(resource, {"spec": {"minAvailable": raw}}))
    assert observed["min-available"].sort == expected


@pytest.mark.parametrize(
    "selector,matched",
    [
        (None, False),
        ({}, True),
        ({"matchLabels": {"app": "owned"}}, True),
        ({"matchExpressions": [{"key": "app", "operator": "DoesNotExist"}]}, False),
    ],
)
def test_policy_v1_selector_null_empty_and_structured_semantics_stay_in_object_namespace(
    selector, matched
):
    resource = api("PodDisruptionBudget")
    result = details(resource, record(resource, {"spec": {"selector": selector}}))
    destination = result.links[0].destination
    assert isinstance(destination, CollectionDestination)
    assert (destination.scope, destination.namespace) == ("object-namespace", "team")
    from kuberich.domain.resources import resource_record
    from tests.support.resources import pod_resource

    pods = pod_resource()
    pod = resource_record(
        pods,
        {
            "metadata": {
                "name": "owned",
                "namespace": "team",
                "uid": "pod-uid",
                "resourceVersion": "1",
                "labels": {"app": "owned"},
            }
        },
    )
    assert destination.predicate.matches(pods, pod) is matched


@pytest.mark.parametrize(
    "selector",
    [
        [],
        {"other": "hidden"},
        {"matchLabels": {"bad key": "x"}},
        {"matchExpressions": [{"key": "app", "operator": "In", "values": []}]},
    ],
)
def test_invalid_pdb_selectors_disable_navigation(selector):
    resource = api("PodDisruptionBudget")
    link = details(resource, record(resource, {"spec": {"selector": selector}})).links[0]
    assert link.destination is None and link.unavailable_reason


@pytest.mark.parametrize(
    "observed,expected",
    [
        (4, "Current generation"),
        (3, "Stale generation"),
        (None, "Unknown generation"),
        (True, "Unknown generation"),
    ],
)
def test_pdb_reported_generation_is_not_inferred_health(observed, expected):
    resource = api("PodDisruptionBudget")
    result = values(resource, record(resource, {"status": {"observedGeneration": observed}}))
    assert result["status"].text == expected
    assert result["allowed"].sort is None


def test_pdb_generation_absent_and_explicit_eviction_policy():
    resource = api("PodDisruptionBudget")
    item = record(
        resource,
        {"spec": {"unhealthyPodEvictionPolicy": "AlwaysAllow"}},
        metadata={"generation": None},
    )
    assert values(resource, item)["status"].text == "Unknown generation"
    assert (
        dict(section(details(resource, item), "Status provenance").rows)[
            "Eviction policy provenance"
        ]
        == "Declared"
    )
    with pytest.raises(AppError):
        details(replace(resource, version="v1beta1"), item)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("100m", Decimal(".1")),
        ("1Gi", Decimal(2**30)),
        ("1G", Decimal(10**9)),
        ("0", Decimal(0)),
        ("-1", None),
        ("NaN", None),
        (True, None),
        ("9" * 65, None),
    ],
)
def test_runtime_overhead_quantity_units_and_unknowns(raw, expected):
    resource = api("RuntimeClass")
    result = values(resource, record(resource, {"overhead": {"podFixed": {"cpu": raw}}}))
    assert result["overhead-cpu"].sort == expected
    assert result["overhead-memory"].sort is None


def test_runtime_empty_selector_tolerations_and_exact_pod_link_preserve_header_scope():
    resource = api("RuntimeClass")
    item = record(resource, {"scheduling": {"nodeSelector": {}, "tolerations": [{}]}})
    result = details(resource, item)
    assert values(resource, item)["node-selector"].text == "All nodes (empty selector)"
    assert section(result, "Declared tolerations").rows == (("—", "Equal", "—", "—", "—"),)
    link = result.links[0].destination
    assert isinstance(link, CollectionDestination)
    assert (link.scope, link.namespace, link.predicate.name) == (
        "selected-namespace",
        None,
        "owned-one",
    )


def test_invalid_runtime_selector_and_name_disable_links_without_clipped_matching():
    resource = api("RuntimeClass")
    item = record(resource, {"scheduling": {"nodeSelector": {"bad key": "x"}}}, name="x" * 254)
    assert values(resource, item)["node-selector"].sort is None
    result = details(resource, item)
    assert "Invalid" in str(section(result, "Declared node selector").rows)
    assert result.links[0].destination is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-11-06T10:00:01Z", datetime(2026, 11, 6, 10, 0, 1, tzinfo=UTC).timestamp()),
        ("2099-01-01T01:00:00+01:00", datetime(2099, 1, 1, tzinfo=UTC).timestamp()),
        ("2026-01-01", None),
        ("not-a-time", None),
        ("2026-02-31T00:00:00Z", None),
        ("x" * 65, None),
        (1, None),
        (None, None),
    ],
)
def test_lease_timestamp_observation_sort_has_no_clock_expiration(raw, expected):
    resource = api("Lease")
    observed = values(resource, record(resource, {"spec": {"renewTime": raw}}))
    assert observed["renew-time"].sort == expected
    assert "expiry or leadership inference" in str(details(resource, record(resource)))


def test_lease_literal_owner_uid_and_namespace_links_never_infer_holder_objects():
    resource = api("Lease")
    owner = {**TARGET, "uid": "owned-parent-uid"}
    result = details(resource, record(resource, metadata={"ownerReferences": [owner]}))
    assert len(result.links) == 2
    destination = result.links[0].destination
    assert isinstance(destination, ReferenceDestination)
    assert destination.require_uid and destination.ref.uid == "owned-parent-uid"
    assert destination.ref.name == "owned-workload"
    assert result.links[1].destination.ref.namespace is None
    assert result.links[1].destination.ref.name == "team"
    assert all("holder" not in link.key for link in result.links)


@pytest.mark.parametrize(
    "override",
    [
        {"uid": None},
        {"uid": "x" * 254},
        {"uid": "bad/uid"},
        {"kind": None},
        {"kind": "bad-kind"},
        {"name": "x" * 254},
        {"name": "bad/name"},
        {"apiVersion": None},
    ],
)
def test_invalid_owner_reference_retains_disabled_authored_link(override):
    resource = api("Lease")
    owner = {**TARGET, "uid": "owner-uid", **override}
    result = details(resource, record(resource, metadata={"ownerReferences": [owner]}))
    assert result.links[0].destination is None and result.links[0].unavailable_reason


@pytest.mark.parametrize(
    "mode", ["Off", "Initial", "Recreate", "InPlaceOrRecreate", "Auto", "FutureMode"]
)
def test_vpa_modes_are_declared_not_recommendation_or_controller_claims(mode):
    resource = api("VerticalPodAutoscaler")
    item = record(resource, {"spec": {"updatePolicy": {"updateMode": mode}, "targetRef": TARGET}})
    assert values(resource, item)["mode"].text == mode
    assert (
        dict(section(details(resource, item), "Update policy").rows)["Mode provenance"]
        == "Declared"
    )


def test_vpa_recommendations_preserve_container_resource_bound_and_default_provenance():
    resource = api("VerticalPodAutoscaler")
    result = details(resource, record(resource))
    rows = section(result, "Recommendations").rows
    assert ("main", "target", "cpu", "250m") in rows
    assert ("main", "target", "memory", "512Mi") in rows
    assert ("main", "lowerBound", "cpu", "100m") in rows
    assert ("main", "upperBound", "cpu", "1") in rows
    assert ("main", "uncappedTarget", "cpu", "2") in rows
    defaults = record(
        resource, {"spec": {}, "status": {"recommendation": {"containerRecommendations": []}}}
    )
    assert values(resource, defaults)["recommended-containers"].sort == 0
    assert values(resource, record(resource, {"status": {}}))["recommended-containers"].sort is None
    assert "API default: Auto" in str(details(resource, defaults))


def test_hpa_v1_cpu_percentage_is_not_a_v2_metric_array():
    resource = api("HorizontalPodAutoscaler", "v1")
    item = record(
        resource,
        {
            "spec": {
                "scaleTargetRef": TARGET,
                "maxReplicas": 5,
                "targetCPUUtilizationPercentage": 70,
            },
            "status": {"currentCPUUtilizationPercentage": 0},
        },
    )
    assert section(details(resource, item), "CPU metric (v1)").rows == (("70", "0"),)
    assert values(resource, item)["min"].sort == 1
    assert values(resource, item)["current"].sort is None


def metric(
    kind,
    name="owned_metric",
    *,
    current=False,
    selector=None,
    container="main",
    object_name="owned-target",
):
    key = {
        "Resource": "resource",
        "ContainerResource": "containerResource",
        "Pods": "pods",
        "Object": "object",
        "External": "external",
    }[kind]
    body = (
        {"name": name}
        if kind in ("Resource", "ContainerResource")
        else {"metric": {"name": name, "selector": selector or {}}}
    )
    if kind == "ContainerResource":
        body["container"] = container
    if kind == "Object":
        body["describedObject"] = {**TARGET, "name": object_name}
    body["current" if current else "target"] = {
        "type": "AverageValue",
        "averageValue": "250m",
        "value": "0",
        "averageUtilization": 0,
    }
    return {"type": kind, key: body}


@pytest.mark.parametrize(
    "kind,name",
    [
        ("Resource", "cpu"),
        ("ContainerResource", "memory"),
        ("Pods", "owned_metric"),
        ("Object", "owned_metric"),
        ("External", "owned_metric"),
    ],
)
def test_all_hpa_v2_metric_sources_match_complete_identity_independent_of_array_order(kind, name):
    resource = api("HorizontalPodAutoscaler")
    wanted = metric(kind, name)
    observed = metric(kind, name, current=True)
    other = metric("External", "other_metric", current=True)
    item = record(
        resource, {"spec": {"metrics": [wanted]}, "status": {"currentMetrics": [other, observed]}}
    )
    rows = section(details(resource, item), "Metrics (v2)").rows
    assert rows[0][1:3] == ("average=250m", "utilization=0%, value=0, average=250m")
    assert rows[0][3] == "Matched complete identity"
    assert "without unique target" in rows[1][3]


@pytest.mark.parametrize(
    "kind,desired,current",
    [
        (
            "Pods",
            {"selector": {"matchLabels": {"app": "a"}}},
            {"selector": {"matchLabels": {"app": "b"}}},
        ),
        ("ContainerResource", {"container": "a"}, {"container": "b"}),
        ("Object", {"object_name": "a"}, {"object_name": "b"}),
    ],
)
def test_hpa_selector_container_and_described_object_are_part_of_metric_identity(
    kind, desired, current
):
    resource = api("HorizontalPodAutoscaler")
    name = "cpu" if kind == "ContainerResource" else "owned_metric"
    item = record(
        resource,
        {
            "spec": {"metrics": [metric(kind, name, **desired)]},
            "status": {"currentMetrics": [metric(kind, name, current=True, **current)]},
        },
    )
    rows = section(details(resource, item), "Metrics (v2)").rows
    assert rows[0][2] == "Unpaired"


@pytest.mark.parametrize("targets,currents", [(1, 0), (1, 2), (2, 1), (2, 2)])
def test_hpa_missing_and_duplicate_full_identities_never_zip_or_choose_one(targets, currents):
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {"metrics": [metric("Resource", "cpu")] * targets},
            "status": {"currentMetrics": [metric("Resource", "cpu", current=True)] * currents},
        },
    )
    rows = section(details(resource, item), "Metrics (v2)").rows
    assert all(row[2] == "Unpaired" for row in rows)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {"type": "Future"},
        {"type": []},
        {"type": "Resource", "resource": {"name": "bad name"}},
        {"type": "External", "external": {"metric": {"name": "bad name"}}},
        {"type": "External", "external": {"metric": {"name": None}}},
        {"type": "External", "external": {"metric": {"name": "owned", "selector": {"other": 1}}}},
        {"type": "Object", "object": {"metric": {"name": "owned"}, "describedObject": {}}},
    ],
)
def test_invalid_metric_sources_are_explicit_and_do_not_expose_arbitrary_body(raw):
    resource = api("HorizontalPodAutoscaler")
    item = record(resource, {"spec": {"metrics": [raw]}, "status": {"currentMetrics": [raw]}})
    rows = section(details(resource, item), "Metrics (v2)").rows
    assert rows[0] == ("Invalid metric identity", "—", "Unpaired", "Unsupported or invalid source")
    assert rows[-1] == ("Invalid status metrics", "—", "Unpaired", "1")


def test_hpa_missing_metric_values_and_invalid_target_are_unknown():
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {
                "metrics": [{"type": "Resource", "resource": {"name": "cpu"}}],
                "scaleTargetRef": {"apiVersion": "v1", "kind": None, "name": "owned"},
            },
            "status": {"currentMetrics": [{"type": "Resource", "resource": {"name": "cpu"}}]},
        },
    )
    assert values(resource, item)["target"].sort is None
    assert details(resource, item).links[0].destination is None
    assert section(details(resource, item), "Metrics (v2)").rows[0][1:3] == (
        "Unknown target type",
        "—",
    )


def test_condition_messages_unknown_types_and_unlisted_fields_are_concealed():
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "status": {
                "conditions": [
                    {
                        "type": "ScalingActive",
                        "status": "False",
                        "message": "synthetic-message-canary",
                    },
                    {"type": "synthetic-type-canary", "status": "synthetic-state-canary"},
                    None,
                ]
            }
        },
    )
    result = details(resource, item)
    assert section(result, "Reported conditions").rows == (
        ("ScalingActive", "False"),
        ("Other condition", "—"),
        ("Other condition", "—"),
    )
    assert "canary" not in str((result, cells(resource, item)))


def test_cells_and_detail_output_escape_controls_and_bound_unicode_bytes():
    resource = api("Lease")
    item = record(resource, {"spec": {"holderIdentity": "\x1b[31m" + "界" * 1000}})
    text = values(resource, item)["holder"].text
    assert "\x1b" not in text and "\\u001b" in text
    assert len(text) <= 256
    assert "界" in text


def test_shared_detail_row_budget_reports_omissions_across_large_recommendations_and_policies():
    resource = api("VerticalPodAutoscaler")
    recommendation = {"containerName": "main", "target": {f"resource-{i}": "1" for i in range(257)}}
    item = record(
        resource,
        {
            "status": {
                "recommendation": {
                    "containerRecommendations": [recommendation, *({} for _ in range(256))]
                }
            },
            "spec": {
                "resourcePolicy": {
                    "containerPolicies": [
                        {"containerName": "main", "controlledResources": ["cpu"] * 257}
                    ]
                    * 257
                }
            },
        },
    )
    result = details(resource, item)
    assert sum(len(part.rows) for part in result.sections) == MAX_CURATED_DETAIL_ROWS
    assert sum(part.omitted_rows for part in result.sections) > 1000
    assert "Recommendation containers omitted: 1." in result.notices
    assert "Container policies omitted: 1." in result.notices
    assert any("budget reached" in notice for notice in result.notices)


def test_utf8_budget_precedes_row_budget_and_includes_headers():
    resource = api("RuntimeClass")
    tolerance = {
        "key": "界" * 256,
        "value": "界" * 256,
        "effect": "界" * 256,
        "operator": "界" * 256,
    }
    item = record(resource, {"scheduling": {"tolerations": [tolerance] * 257}})
    result = details(resource, item)
    assert sum(len(part.rows) for part in result.sections) < MAX_CURATED_DETAIL_ROWS
    size = sum(
        len(
            (
                part.title + "".join(part.columns) + "".join("".join(row) for row in part.rows)
            ).encode()
        )
        for part in result.sections
    )
    assert size <= MAX_CURATED_DETAIL_BYTES
    assert section(result, "Declared tolerations").omitted_rows > 200
    assert "Tolerations omitted: 1." in str(result.notices)


def test_all_input_collection_limits_are_reported_without_unbounded_output():
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {"metrics": [metric("Resource", "cpu")] * 257},
            "status": {
                "currentMetrics": [metric("Resource", "cpu", current=True)] * 257,
                "conditions": [{"type": "ScalingActive", "status": "True"}] * 257,
            },
        },
    )
    result = details(resource, item)
    assert "Condition entries omitted: 1." in result.notices
    assert section(result, "Metrics (v2)").omitted_rows > 0
    lease = api("Lease")
    owner = {**TARGET, "uid": "owner-uid"}
    result = details(lease, record(lease, metadata={"ownerReferences": [owner] * 257}))
    assert len(result.links) + sum(len(part.rows) for part in result.sections) <= 256
    assert "Owner references omitted: 1." in result.notices
    assert any("Links omitted" in notice for notice in result.notices)


def test_complete_selector_action_payload_is_omitted_when_it_exceeds_total_utf8_budget():
    resource = api("PodDisruptionBudget")
    selector = {"matchLabels": {f"label-{index}": "x" * 63 for index in range(1000)}}
    result = details(resource, record(resource, {"spec": {"selector": selector}}))
    assert not result.links
    assert "Links omitted: 1" in str(result.notices)
    assert (
        len(json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")).encode()) <= 65536
    )
    assert "Selector requirements omitted: 744." in result.notices


def test_total_json_presentation_budget_counts_controls_structure_and_notices():
    resource = api("RuntimeClass")
    # A display cell containing escaped controls is much larger in serialized form.
    tolerance = {
        "key": "\x01" * 256,
        "value": "\x02" * 256,
        "effect": "\x03" * 256,
        "operator": "\x04" * 256,
    }
    result = details(resource, record(resource, {"scheduling": {"tolerations": [tolerance] * 256}}))
    encoded = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= MAX_CURATED_DETAIL_BYTES
    assert sum(part.omitted_rows for part in result.sections) > 0


def test_generation_and_toleration_seconds_use_api_int64_rather_than_replica_int32():
    pdb = api("PodDisruptionBudget")
    generation = 2**40
    item = record(
        pdb, {"status": {"observedGeneration": generation}}, metadata={"generation": generation}
    )
    assert values(pdb, item)["status"].text == "Current generation"
    runtime = api("RuntimeClass")
    result = details(
        runtime,
        record(runtime, {"scheduling": {"tolerations": [{"tolerationSeconds": generation}]}}),
    )
    assert section(result, "Declared tolerations").rows[0][-1] == str(generation)


@pytest.mark.parametrize(
    "target_type,field,value,expected",
    [
        ("Utilization", "averageUtilization", 0, "utilization=0%"),
        ("Value", "value", "1Gi", "value=1Gi"),
        ("AverageValue", "averageValue", "500m", "average=500m"),
        ("Future", "value", "1", "Unknown target type"),
        ("Value", "value", "-1", "—"),
    ],
)
def test_hpa_target_discriminator_controls_percentage_and_quantity_units(
    target_type, field, value, expected
):
    resource = api("HorizontalPodAutoscaler")
    item = record(
        resource,
        {
            "spec": {
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {"name": "cpu", "target": {"type": target_type, field: value}},
                    }
                ]
            }
        },
    )
    assert section(details(resource, item), "Metrics (v2)").rows[0][1] == expected


@pytest.mark.parametrize("raw", [True, -1, 2**31, "0"])
def test_lease_reported_duration_and_transitions_reject_non_api_counters(raw):
    resource = api("Lease")
    observed = values(
        resource, record(resource, {"spec": {"leaseDurationSeconds": raw, "leaseTransitions": raw}})
    )
    assert observed["duration-seconds"].sort is None
    assert observed["transitions"].sort is None


def test_hpa_canonical_selector_identity_ignores_label_and_value_order():
    resource = api("HorizontalPodAutoscaler")
    first = {
        "matchLabels": {"app": "owned", "team": "synthetic"},
        "matchExpressions": [{"key": "zone", "operator": "In", "values": ["a", "b"]}],
    }
    second = {
        "matchExpressions": [{"key": "zone", "operator": "In", "values": ["b", "a"]}],
        "matchLabels": {"team": "synthetic", "app": "owned"},
    }
    item = record(
        resource,
        {
            "spec": {"metrics": [metric("External", selector=first)]},
            "status": {"currentMetrics": [metric("External", current=True, selector=second)]},
        },
    )
    assert (
        section(details(resource, item), "Metrics (v2)").rows[0][3] == "Matched complete identity"
    )


@pytest.mark.parametrize(
    "holder,preferred",
    [
        ("token=synthetic-holder-canary", "Bearer synthetic-preferred-canary"),
        (
            "password=synthetic-holder-canary",
            "https://synthetic:synthetic-preferred-canary@example.invalid",
        ),
    ],
)
def test_lease_credential_shaped_observations_are_redacted_in_cells_and_details(holder, preferred):
    resource = api("Lease")
    item = record(resource, {"spec": {"holderIdentity": holder, "preferredHolder": preferred}})
    observed = values(resource, item)["holder"]
    result = details(resource, item)
    assert "synthetic-holder-canary" not in observed.text
    assert "synthetic-holder-canary" not in str(result)
    assert "synthetic-preferred-canary" not in str(result)
    assert "[REDACTED]" in observed.text
    assert "[REDACTED]" in str(section(result, "Reported Lease observations").rows)
    assert observed.sort == observed.text.casefold()
    assert result.links[0].destination.ref.name == "team"


def test_display_redaction_happens_before_the_cell_clip_boundary():
    resource = api("Lease")
    holder = "a" * 248 + " token=synthetic-boundary-canary"
    observed = values(resource, record(resource, {"spec": {"holderIdentity": holder}}))["holder"]
    assert observed.text == "a" * 248 + " token=["
    assert len(observed.text) == 256


@pytest.mark.parametrize("truncated", ["desired", "current", "both"])
def test_hpa_duplicate_identity_after_input_limit_keeps_target_but_pairing_is_uncertain(truncated):
    resource = api("HorizontalPodAutoscaler")
    desired = [metric("Resource", "cpu")]
    current = [metric("Resource", "cpu", current=True)]
    if truncated in ("desired", "both"):
        desired.extend(metric("External", f"owned_{index}") for index in range(255))
        desired.append(metric("Resource", "cpu"))
    if truncated in ("current", "both"):
        current.extend(metric("External", f"owned_{index}", current=True) for index in range(255))
        current.append(metric("Resource", "cpu", current=True))
    item = record(resource, {"spec": {"metrics": desired}, "status": {"currentMetrics": current}})
    result = details(resource, item)
    first = section(result, "Metrics (v2)").rows[0]
    assert first[1] == "average=250m"
    assert first[2] == "Unpaired"
    assert first[3] == "Pairing uncertain: metric input collection truncated"
    assert "Matched complete identity" not in str(result)
    assert (
        "Metric pairing uncertain: input collection limit prevents proving identity uniqueness."
        in result.notices
    )
    assert values(resource, item)["metrics"].sort == len(desired)
