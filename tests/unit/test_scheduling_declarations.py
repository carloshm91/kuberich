"""Scheduling observations preserve declarations, scope, uncertainty and bounds."""

import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from kuberich.domain.curated import MAX_CURATED_DETAIL_BYTES, MAX_CURATED_DETAIL_ROWS
from kuberich.domain.scheduling_declarations import scheduling_declarations


def projected(kind="Pod", **spec):
    result = scheduling_declarations({"apiVersion": "v1", "kind": kind, "spec": spec})
    assert result is not None
    assert result.links == ()
    return result


def rows(result, title):
    return next(section.rows for section in result.sections if section.title == title)


@pytest.mark.parametrize(
    "manifest",
    [
        {},
        {"kind": "Pod", "apiVersion": "other.example/v1"},
        {"kind": "Deployment", "apiVersion": "v1"},
        {"kind": [], "apiVersion": "v1"},
    ],
)
def test_unrelated_or_unreviewed_descriptors_have_no_projection(manifest):
    assert scheduling_declarations(manifest) is None


@pytest.mark.parametrize("spec", [None, [], "unavailable"])
def test_missing_or_malformed_spec_is_unknown_instead_of_empty_constraints(spec):
    result = scheduling_declarations({"apiVersion": "v1", "kind": "Pod", "spec": spec})
    assert result is not None
    assert rows(result, "Scheduling declarations") == (("spec", "—"),)
    assert any("malformed or unavailable" in notice for notice in result.notices)


def test_pod_placement_and_declared_node_labels_remain_separate_and_do_not_retain_other_payloads():
    spec = {
        "nodeName": "owned-worker",
        "schedulerName": "fixture",
        "priorityClassName": "batch",
        "runtimeClassName": "sandbox",
        "nodeSelector": {"disk": "ssd", "team": "owned"},
        "unlisted": "unlisted-config-body-canary",
        "containers": [{"env": [{"value": "unlisted-config-body-canary"}]}],
    }
    original = deepcopy(spec)
    result = projected(**spec)
    assert dict(rows(result, "Scheduling identity (declared)")) == {
        "nodeName": "owned-worker",
        "schedulerName": "fixture",
        "priorityClassName": "batch",
        "runtimeClassName": "sandbox",
    }
    assert {(key, value) for key, value, _ in rows(result, "Node selectors (declared)")} == {
        ("disk", "ssd"),
        ("team", "owned"),
    }
    assert "unlisted-config-body-canary" not in repr(result)
    assert spec == original
    assert any("not scheduler feasibility" in notice for notice in result.notices)


@pytest.mark.parametrize("selector", [None, [], {"invalid key": "v"}])
def test_malformed_node_selector_does_not_claim_to_select_all_nodes(selector):
    result = projected(nodeSelector=selector)
    assert rows(result, "Node selectors (declared)") == (("—", "—", "Malformed nodeSelector"),)


def test_node_selector_input_limit_is_explicit_and_does_not_add_actions():
    result = projected(nodeSelector={f"key{i:03}": "owned" for i in range(65)})
    assert len(rows(result, "Node selectors (declared)")) == 64
    assert any("omitted" in notice for notice in result.notices)


def test_required_node_affinity_or_terms_and_and_requirements_are_declarations():
    result = projected(
        affinity={
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {},
                        {
                            "matchExpressions": [
                                {"key": "size", "operator": "Gt", "values": ["2"]}
                            ],
                            "matchFields": [
                                {
                                    "key": "metadata.name",
                                    "operator": "In",
                                    "values": ["owned-worker"],
                                }
                            ],
                        },
                    ]
                },
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 100,
                        "preference": {"matchExpressions": [{"key": "disk", "operator": "Exists"}]},
                    }
                ],
            }
        }
    )
    observed = rows(result, "Affinity declarations")
    assert ("nodeAffinity.required[0]", "term", "empty term", "Matches no nodes") in observed
    assert any(row[2] == "Gt (2)" for row in observed)
    assert any(row[2] == "In (owned-worker)" for row in observed)
    assert any(row[1:3] == ("weight", "100") for row in observed)
    assert any("terms are alternatives (OR)" in row[3] for row in observed)
    empty = projected(
        affinity={
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": []}
            }
        }
    )
    assert rows(empty, "Affinity declarations") == (
        (
            "nodeAffinity.required",
            "term count",
            "0",
            "Empty required node selector matches no nodes",
        ),
    )


def test_pod_affinity_null_selector_and_namespace_union_preserve_distinct_scopes():
    term = {
        "topologyKey": "zone",
        "labelSelector": {},
        "namespaces": ["explicit"],
        "namespaceSelector": {},
        "matchLabelKeys": ["revision"],
        "mismatchLabelKeys": ["tenant"],
    }
    result = projected(
        affinity={
            "podAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": [{"topologyKey": "zone"}, term]
            },
            "podAntiAffinity": {
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {
                        "weight": 1,
                        "podAffinityTerm": {
                            "labelSelector": {"matchLabels": {"app": "api"}},
                            "topologyKey": "host",
                            "namespaces": None,
                            "namespaceSelector": {},
                        },
                    }
                ]
            },
        }
    )
    observed = rows(result, "Affinity declarations")
    assert any(row[1:3] == ("labelSelector", "null (no matching Pods)") for row in observed)
    assert any(row[1:3] == ("namespaces", "declaring Pod namespace") for row in observed)
    assert any(row[1:3] == ("namespaces", "explicit") and "union" in row[3] for row in observed)
    assert any(row[1:3] == ("namespaces", "empty list") for row in observed)
    assert any(
        row[1:3] == ("namespaceSelector", "empty selector (all within declared scope)")
        for row in observed
    )
    assert any(row[1:3] == ("matchLabelKeys", "revision") for row in observed)
    assert any(row[1:3] == ("mismatchLabelKeys", "tenant") for row in observed)


@pytest.mark.parametrize(
    "affinity",
    [
        None,
        [],
        {"nodeAffinity": None},
        {"nodeAffinity": {}},
        {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": None}},
        {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        None,
                        {"matchExpressions": None},
                        {"matchExpressions": [None, {"key": "x", "operator": "Future"}]},
                    ]
                }
            }
        },
        {
            "podAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": [
                    None,
                    {
                        "labelSelector": {"matchLabels": []},
                        "namespaces": [True],
                        "matchLabelKeys": None,
                    },
                ]
            }
        },
        {
            "podAntiAffinity": {
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    None,
                    {"weight": True, "podAffinityTerm": {"topologyKey": 1}},
                ]
            }
        },
    ],
)
def test_malformed_affinity_never_becomes_an_empty_success_or_executable_expression(affinity):
    result = projected(affinity=affinity)
    observed = rows(result, "Affinity declarations")
    if affinity == {"nodeAffinity": {}}:
        assert observed == ()
    else:
        assert any("—" in row for row in observed)
        assert any("malformed or unavailable" in notice for notice in result.notices)


def test_empty_affinity_and_tolerations_have_honest_absence_without_scheduling_verdict():
    result = projected()
    assert rows(result, "Node selectors (declared)")[0][1] == "empty map"
    assert rows(result, "Affinity declarations")[0][2] == "omitted or empty"
    assert rows(result, "Tolerations (declared)")[0][1] == "none declared"


def test_tolerations_keep_defaults_wildcards_gated_operators_and_signed_seconds():
    result = projected(
        tolerations=[
            {"key": "owned", "value": "v", "effect": "NoExecute", "tolerationSeconds": -2},
            {"operator": "Exists"},
            {
                "key": "priority",
                "operator": "Gt",
                "value": "2",
                "effect": "NoSchedule",
                "tolerationSeconds": 0,
            },
            {
                "key": "priority",
                "operator": "Lt",
                "value": "7",
                "effect": "PreferNoSchedule",
                "tolerationSeconds": 5,
            },
        ]
    )
    observed = rows(result, "Tolerations (declared)")
    assert observed[0] == ("0", "owned", "Equal", "v", "NoExecute", "-2")
    assert observed[1] == (
        "1",
        "all keys (Exists required)",
        "Exists",
        "empty value",
        "all effects",
        "not set",
    )
    assert observed[2][2:] == ("Gt", "2", "NoSchedule", "0")
    assert observed[3][2:] == ("Lt", "7", "PreferNoSchedule", "5")
    assert any("never guarantees placement" in notice for notice in result.notices)


@pytest.mark.parametrize(
    "entries",
    [
        None,
        [None],
        [
            {
                "key": None,
                "value": 0,
                "operator": "Future",
                "effect": None,
                "tolerationSeconds": True,
            }
        ],
        [{"tolerationSeconds": 2**63}],
    ],
)
def test_malformed_tolerations_do_not_infer_zero_seconds_or_known_operators(entries):
    result = projected(tolerations=entries)
    assert all(row[-1] != "0" for row in rows(result, "Tolerations (declared)"))


@pytest.mark.parametrize(
    "value,expected", [(False, "false"), (True, "true"), (None, "—"), (0, "—")]
)
def test_node_unschedulable_boolean_is_not_guessed_from_numeric_or_missing_state(value, expected):
    result = projected(
        "Node",
        unschedulable=value,
        taints=[
            {"key": "dedicated", "value": "batch", "effect": "NoSchedule"},
            {"key": "unavailable", "effect": "NoExecute"},
            {"key": "soft", "effect": "PreferNoSchedule"},
        ],
    )
    assert rows(result, "Node scheduling (declared)")[0] == ("unschedulable", expected, "Declared")
    assert rows(result, "Node taints (declared)") == (
        ("0", "dedicated", "batch", "NoSchedule"),
        ("1", "unavailable", "empty value", "NoExecute"),
        ("2", "soft", "empty value", "PreferNoSchedule"),
    )


def test_node_default_and_malformed_taints_do_not_invent_effects():
    default = projected("Node")
    assert rows(default, "Node scheduling (declared)")[0] == (
        "unschedulable",
        "false",
        "API default: false",
    )
    assert rows(default, "Node taints (declared)")[0][1] == "none declared"
    assert rows(projected("Node", taints=None), "Node taints (declared)") == ()
    malformed = projected("Node", taints=[None, {"key": "", "value": None, "effect": "Future"}])
    assert rows(malformed, "Node taints (declared)") == (("0", "—", "—", "—"), ("1", "—", "—", "—"))


@pytest.mark.parametrize("wide", [False, True])
def test_complete_scheduling_output_is_bounded_including_escaped_unicode_and_notices(wide):
    term = {
        "labelSelector": {},
        "namespaces": ["界" * 300 if wide else "owned"] * 65,
        "namespaceSelector": {},
        "topologyKey": "界" * 300 if wide else "zone",
        "matchLabelKeys": ["界" * 300 if wide else "revision"] * 65,
    }
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "spec": {
            "nodeName": "Bearer PRIVATE80\x1b[2J",
            "affinity": {
                "podAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [term] * 65}
            },
            "tolerations": [{"key": "owned"}] * 65,
        },
    }
    result = scheduling_declarations(manifest)
    assert result is not None
    serialized = json.dumps(asdict(result), ensure_ascii=True)
    assert "PRIVATE80" not in serialized and "\x1b" not in serialized
    assert len(serialized.encode()) < MAX_CURATED_DETAIL_BYTES
    assert sum(len(part.rows) for part in result.sections) <= MAX_CURATED_DETAIL_ROWS
    assert all(len(cell) <= 256 for part in result.sections for row in part.rows for cell in row)
    assert any(part.omitted_rows for part in result.sections)
    assert any("omitted" in notice for notice in result.notices)
