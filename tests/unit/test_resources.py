"""Discovery identity/path decisions and immutable, credential-safe snapshots."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from kubetrol.domain.resources import (
    Discovery,
    DiscoveryIssue,
    api_resource,
    api_segment,
    resource_object,
    resource_record,
    resource_text,
    split_api_version,
    string_list,
)
from kubetrol.errors import AppError
from tests.support.resources import aggregated_resource, descriptor, item, pod_resource


def test_discovered_paths_and_aliases_preserve_scope_and_served_version() -> None:
    pods = pod_resource()
    assert pods.path() == "/api/v1/pods"
    assert pods.path("team") == "/api/v1/namespaces/team/pods"
    nodes = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    assert nodes.path() == "/api/v1/nodes"
    deployments = api_resource("apps/v1", descriptor("deployments", kind="Deployment"))
    assert deployments.api_version == "apps/v1"
    assert deployments.path("team") == "/apis/apps/v1/namespaces/team/deployments"
    assert deployments.path() == "/apis/apps/v1/deployments"
    with pytest.raises(AppError, match="cluster-scoped"):
        nodes.path("team")
    with pytest.raises(AppError, match="Namespace"):
        pods.path("../escape")
    modern = api_resource("v1", aggregated_resource(), aggregated=True)
    assert modern == pods
    cluster = api_resource("v1", aggregated_resource("nodes", scope="Cluster"), aggregated=True)
    assert not cluster.namespaced


@pytest.mark.parametrize(
    "factory,value",
    [
        (resource_object, []),
        (resource_object, {1: "value"}),
        (resource_text, 4),
        (resource_text, "secret\ncontrol"),
        (api_segment, "../escape"),
        (api_segment, "A"),
        (api_segment, "a" * 254),
        (split_api_version, "a/b/c"),
        (split_api_version, "/v1"),
        (string_list, False),
        (string_list, ["a"] * 65),
    ],
)
def test_invalid_resource_data_has_owned_messages(factory, value) -> None:
    with pytest.raises(AppError) as error:
        factory(value)
    assert "secret" not in str(error.value)


def test_optional_strings_and_core_group_version() -> None:
    assert string_list(None) == ()
    assert string_list([]) == ()
    assert string_list(["get"]) == ("get",)
    assert split_api_version("v1") == ("", "v1")
    assert split_api_version("apps/v1") == ("apps", "v1")


@pytest.mark.parametrize(
    "overrides,modern",
    [
        ({"namespaced": "true"}, False),
        ({"scope": "Unexpected"}, True),
        ({"scope": {}}, True),
        ({"responseKind": None}, True),
        ({"kind": "bad kind"}, False),
        ({"verbs": ["get resource"]}, False),
        ({"shortNames": ["../escape"]}, False),
        ({"singularName": None}, False),
    ],
)
def test_invalid_resource_descriptors_are_rejected(overrides: dict, modern: bool) -> None:
    base = aggregated_resource() if modern else descriptor()
    with pytest.raises(AppError):
        api_resource("v1", {**base, **overrides}, aggregated=modern)


def test_discovery_prefers_canonical_names_and_preserves_preferred_version_order() -> None:
    pods = pod_resource()
    beta = api_resource("v1beta1", descriptor())
    alternate = api_resource("v1", {**descriptor("other"), "shortNames": ["po"]})
    discovery = Discovery((pods, beta, alternate), (DiscoveryIssue("apps/v1", "forbidden", 403),))
    assert discovery.partial
    assert discovery.find("pods") is pods
    assert discovery.find("pod", version="v1beta1") is beta
    with pytest.raises(AppError, match="ambiguous"):
        discovery.find("po")
    assert Discovery((pods, beta)).find("po") is pods
    assert not Discovery((pods,)).partial
    with pytest.raises(AppError, match="not discovered"):
        discovery.find("pods", group="missing")
    with pytest.raises(AppError, match="not discovered"):
        discovery.find("missing")


def test_manifest_copy_and_typed_metadata_do_not_expose_or_change_raw_values() -> None:
    original = item()
    original["metadata"]["creationTimestamp"] = "2026-01-02T03:04:05Z"
    original["data"] = {"token": "opaque-sensitive-test-value"}
    record = resource_record(pod_resource(), original, "team")
    assert record.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert record.resource_version == "opaque/object" and record.uid == "owned-one"
    assert record.namespace == "team" and record.name == "one"
    assert record.size_bytes > 0
    first = record.manifest
    first["metadata"]["name"] = "changed"
    original["data"]["token"] = "changed"
    assert record.manifest["metadata"]["name"] == "one"
    assert record.manifest["data"]["token"] == "opaque-sensitive-test-value"
    assert record.manifest["kind"] == "Pod" and record.manifest["apiVersion"] == "v1"
    assert "opaque-sensitive" not in repr(record)
    with pytest.raises(FrozenInstanceError):
        record.name = "changed"


@pytest.mark.parametrize(
    "overrides",
    [
        {"apiVersion": "apps/v1"},
        {"kind": "Deployment"},
        {"metadata": None},
        {"metadata": {"name": ".", "uid": "owned"}},
        {"metadata": {"name": "../escape", "uid": "owned"}},
        {"metadata": {"name": "bad%name", "uid": "owned"}},
    ],
)
def test_item_type_and_name_must_match_the_discovered_resource(overrides: dict) -> None:
    with pytest.raises(AppError):
        resource_record(pod_resource(), {**item(), **overrides})


@pytest.mark.parametrize(
    "metadata",
    [
        {"namespace": "other"},
        {"namespace": "INVALID"},
        {"namespace": None},
        {"uid": None},
        {"resourceVersion": None},
        {"resourceVersion": ""},
        {"creationTimestamp": "bad"},
        {"creationTimestamp": "2026-01-02T03:04:05"},
        {"creationTimestamp": 4},
    ],
)
def test_malformed_metadata_never_becomes_a_usable_watch_identity(metadata: dict) -> None:
    data = item()
    data["metadata"].update(metadata)
    with pytest.raises(AppError):
        resource_record(pod_resource(), data, "team")


def test_cluster_scoped_names_and_unversioned_aggregate_items() -> None:
    roles = api_resource("rbac.authorization.k8s.io/v1", descriptor("roles", namespaced=False))
    data = item("system:aggregate-to-admin", namespace=None)
    record = resource_record(roles, data)
    assert record.namespace is None and record.created_at is None
    data["metadata"]["namespace"] = ""
    assert resource_record(roles, data).namespace is None
    data["metadata"]["namespace"] = "team"
    with pytest.raises(AppError, match="cluster-scoped"):
        resource_record(roles, data)
    aggregate = api_resource("v1", {**descriptor(), "verbs": ["list"]})
    data = item()
    del data["metadata"]["resourceVersion"]
    del data["metadata"]["uid"]
    record = resource_record(aggregate, data)
    assert record.resource_version is None and record.uid is None


@pytest.mark.parametrize("value", [float("nan"), object(), "\ud800"])
def test_invalid_manifest_values_have_owned_errors(value: object) -> None:
    data = item()
    data["data"] = {"opaque-sensitive": value}
    with pytest.raises(AppError) as error:
        resource_record(pod_resource(), data)
    assert "opaque-sensitive" not in str(error.value)
