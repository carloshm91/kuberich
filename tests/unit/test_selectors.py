"""Local selectors deliberately exclude arbitrary manifest paths and secret data."""

import pytest

from kuberich.domain.selectors import metadata_fields, object_fields, selectors, unhealthy
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "text,fields,expected",
    [
        ("app=api", {"app": "api"}, True),
        ("app==api", {"app": "other"}, False),
        ("app!=api", {}, True),
        ("app!=api", {"app": "api"}, False),
        ("app in (api, worker)", {"app": "worker"}, True),
        ("app in (api,worker)", {}, False),
        ("app notin (api,worker)", {}, True),
        ("app notin (api,worker)", {"app": "worker"}, False),
        ("app", {"app": ""}, True),
        ("app", {}, False),
        ("!app", {}, True),
        ("!app", {"app": ""}, False),
        ("app=api,!debug", {"app": "api"}, True),
    ],
)
def test_label_equality_sets_existence_and_missing_keys(text, fields, expected):
    assert all(term.matches(fields) for term in selectors(text)) is expected


@pytest.mark.parametrize(
    "text,field",
    [
        ("", False),
        ("x" * 257, False),
        (",".join("app" for _ in range(9)), False),
        ("app > api", False),
        ("app in (api)", True),
        ("metadata.annotations.private=x", True),
        ("data.token=x", True),
    ],
)
def test_malformed_unbounded_and_sensitive_paths_are_refused(text, field):
    with pytest.raises(AppError):
        selectors(text, field=field)


def test_fields_use_api_names_and_typed_defaults_without_secret_data():
    manifest = {
        "metadata": {"name": "api", "namespace": "team", "labels": {"private": "hidden"}},
        "spec": {"nodeName": "node-a"},
        "status": {"phase": "Pending", "succeeded": 2},
        "data": {"token": "hidden"},
    }
    pod = metadata_fields(manifest, "pods")
    assert pod == {
        "metadata.name": "api",
        "metadata.namespace": "team",
        "spec.nodeName": "node-a",
        "spec.schedulerName": "",
        "spec.hostNetwork": "false",
        "status.phase": "Pending",
    }
    assert selectors("status.phase=Pending", field=True)[0].matches(pod)
    assert metadata_fields(manifest, "nodes")["spec.unschedulable"] == "false"
    assert metadata_fields(manifest, "jobs")["status.successful"] == "2"
    assert metadata_fields({}, "jobs")["status.successful"] == "0"
    assert metadata_fields(manifest, "secrets") == {
        "metadata.name": "api",
        "metadata.namespace": "team",
    }
    assert object_fields(None) == {}


@pytest.mark.parametrize(
    "manifest,resource,expected",
    [
        ({}, "unknown", None),
        (
            {
                "status": {
                    "phase": "Succeeded",
                    "conditions": [{"type": "Failed", "status": "True"}],
                }
            },
            "pods",
            False,
        ),
        *[
            ({"status": {"phase": phase}}, "pods", True)
            for phase in ("Failed", "Pending", "Unknown")
        ],
        ({"status": {"phase": "Running"}}, "pods", None),
        ({"status": {"conditions": [{"type": "Failed", "status": "True"}]}}, "jobs", True),
        (
            {"status": {"conditions": [{"type": "Available", "status": "False"}]}},
            "deployments",
            True,
        ),
        ({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}, "nodes", False),
        ({"status": {"conditions": [{"type": "Other", "status": "False"}]}}, "other", None),
    ],
)
def test_health_is_observable_and_unknown_is_not_zero(manifest, resource, expected):
    assert unhealthy(manifest, resource) is expected


def test_unknown_ready_condition_is_not_healthy_and_failure_wins_over_other_conditions():
    assert (
        unhealthy({"status": {"conditions": [{"type": "Ready", "status": "Unknown"}]}}, "nodes")
        is None
    )
    assert (
        unhealthy(
            {
                "status": {
                    "conditions": [
                        {"type": "Ready", "status": "True"},
                        {"type": "ReplicaFailure", "status": "True"},
                    ]
                }
            },
            "deployments",
        )
        is True
    )
