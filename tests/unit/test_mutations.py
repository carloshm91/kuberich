"""Guarded write decisions, immutable bytes, opaque versions and literal annotation keys."""

from dataclasses import replace

import pytest

from kubetrol.domain.mutations import (
    MutationState,
    annotation_intent,
    annotation_key,
    decode_patch,
    mutation_path,
    patch_intent,
    status_result,
)
from kubetrol.domain.resources import ApiResource, resource_record
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError


def selection(*, namespaced=True):
    resource = ApiResource(
        "", "v1", "configmaps", "ConfigMap", namespaced, frozenset({"get", "patch"})
    )
    target = ResourceTarget(
        SessionIdentity("kubetrol-test-one", 1),
        "",
        "configmaps",
        "team" if namespaced else None,
        "owned-one",
        "owned-uid",
    )
    data = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "owned-one",
            "uid": "owned-uid",
            "resourceVersion": "opaque/version-7",
        },
    }
    if namespaced:
        data["metadata"]["namespace"] = "team"
    return resource, target, resource_record(resource, data, target.namespace)


def intent():
    resource, target, record = selection()
    return patch_intent(
        resource, target, record, [{"op": "add", "path": "/data/value", "value": "private-payload"}]
    )


def test_immutable_patch_captures_scoped_uid_and_opaque_version_before_effect():
    resource, target, record = selection()
    changes = [{"op": "add", "path": "/data/value", "value": {"a": [1, None]}}]
    captured = patch_intent(resource, target, record, changes)
    changes[0]["value"]["a"].append(99)
    assert captured.path == "/api/v1/namespaces/team/configmaps/owned-one"
    assert decode_patch(captured.body) == [
        {"op": "test", "path": "/metadata/uid", "value": "owned-uid"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "opaque/version-7"},
        {"op": "add", "path": "/data/value", "value": {"a": [1, None]}},
    ]
    assert captured.effects == ("add /data/value",)
    assert "private-payload" not in repr(intent())
    cluster_resource, cluster_target, _ = selection(namespaced=False)
    assert mutation_path(cluster_resource, cluster_target) == "/api/v1/configmaps/owned-one"
    assert mutation_path(
        replace(resource, group="example.io"), replace(target, group="example.io")
    ).startswith("/apis/example.io/v1/")


@pytest.mark.parametrize(
    "body",
    [
        None,
        b"",
        b"x" * (1024 * 1024 + 1),
        b"not json",
        b'[{"x":NaN}]',
        b"\xff",
        b"{}",
        b"[]",
        b"[1,2,3]",
        b"[{}, {}, {}]" * 100,
    ],
)
def test_invalid_patch_json_is_rejected(body):
    with pytest.raises(AppError):
        decode_patch(body)


@pytest.mark.parametrize(
    "update",
    [
        {"version": "../v1"},
        {"group": "bad/group"},
        {"name": "pods/log"},
        {"namespaced": None},
        {"namespaced": False},
        {"verbs": frozenset({"get"})},
    ],
)
def test_unqualified_discovered_api_is_rejected(update):
    resource, target, _ = selection()
    with pytest.raises(AppError):
        mutation_path(replace(resource, **update), target)


@pytest.mark.parametrize(
    "update", [{"group": "apps"}, {"resource": "pods"}, {"container": "main"}, {"namespace": None}]
)
def test_wrong_target_scope_or_type_is_rejected(update):
    resource, target, _ = selection()
    with pytest.raises(AppError):
        mutation_path(resource, replace(target, **update))


@pytest.mark.parametrize(
    "path",
    [
        None,
        "",
        "data",
        "/" + "x" * 1024,
        "/data/\x1b",
        "/data/a~2b",
        "/apiVersion",
        "/kind/name",
        "/status",
        "/metadata",
        "/metadata/name",
        "/metadata/uid",
        "/metadata/resourceVersion",
        "/metadata/managedFields",
    ],
)
def test_patch_cannot_replace_identity_or_unsafe_pointers(path):
    resource, target, record = selection()
    with pytest.raises(AppError):
        patch_intent(resource, target, record, [{"op": "add", "path": path, "value": 1}])


@pytest.mark.parametrize(
    "change",
    [
        {"op": "move", "path": "/data/value", "from": "/data/x"},
        {"op": "test", "path": "/data/value", "value": 1},
        {"op": "add", "path": "/data/value"},
        {"op": "remove", "path": "/data/value", "value": 1},
        {"op": "replace", "path": "/data/value", "value": 1, "extra": False},
    ],
)
def test_missing_unexpected_or_unqualified_operations_are_rejected(change):
    resource, target, record = selection()
    with pytest.raises(AppError):
        patch_intent(resource, target, record, [change])


def test_replace_remove_and_escaped_pointer_are_supported():
    resource, target, record = selection()
    captured = patch_intent(
        resource,
        target,
        record,
        [
            {"op": "replace", "path": "/metadata/labels/a~1b~0c", "value": "x"},
            {"op": "remove", "path": "/data/old"},
        ],
    )
    assert captured.effects == ("replace /metadata/labels/a~1b~0c", "remove /data/old")


@pytest.mark.parametrize(
    "update", [{"resource_version": "x" * 1025}, {"identity": "not uuid"}, {"body": b"[{},{},{}]"}]
)
def test_intent_constructor_cannot_bypass_server_preconditions(update):
    with pytest.raises(AppError):
        replace(intent(), **update)


@pytest.mark.parametrize(
    "update",
    [
        {"name": "another"},
        {"namespace": "other"},
        {"resource_version": None},
        {"uid": "replacement-uid"},
    ],
)
def test_snapshot_identity_and_version_are_required(update):
    resource, target, record = selection()
    with pytest.raises(AppError):
        patch_intent(
            resource, target, replace(record, **update), [{"op": "remove", "path": "/data/old"}]
        )


@pytest.mark.parametrize("value", [float("nan"), {"unserializable"}, "\ud800"])
def test_nonfinite_unserializable_or_invalid_utf8_values_are_rejected(value):
    resource, target, record = selection()
    with pytest.raises(AppError):
        patch_intent(
            resource, target, record, [{"op": "add", "path": "/data/value", "value": value}]
        )


@pytest.mark.parametrize(
    "key",
    [
        None,
        "",
        "/key",
        "bad/key/extra",
        "-key",
        "key-",
        "é",
        "x" * 64,
        "Upper.example/key",
        "bad..example/key",
        "x" * 64 + "/key",
        "a." * 128 + "a/key",
    ],
)
def test_annotation_key_uses_kubernetes_qualified_name_rules(key):
    with pytest.raises(AppError):
        annotation_key(key)


@pytest.mark.parametrize(
    "key", ["a", "A.B_C-d", "example.io/name", "x" * 63, "x" * 63 + ".example/name"]
)
def test_valid_annotation_keys_are_literal(key):
    assert annotation_key(key) == key


def test_annotation_preserves_existing_keys_and_records_no_values_in_effect():
    resource, target, record = selection()
    data = record.manifest
    data["metadata"]["annotations"] = {"kept": "private-existing"}
    captured = annotation_intent(
        resource,
        target,
        resource_record(resource, data, "team"),
        "example.io/review",
        "✓ [markup]\x1b",
    )
    assert decode_patch(captured.body)[2]["value"] == {
        "kept": "private-existing",
        "example.io/review": "✓ [markup]\x1b",
    }
    assert captured.effects == ("add /metadata/annotations",)
    assert "private-existing" not in repr(captured)


@pytest.mark.parametrize("value", [None, "x" * 65537, "\ud800"])
def test_annotation_values_are_text_bounded_and_utf8(value):
    resource, target, record = selection()
    with pytest.raises(AppError):
        annotation_intent(resource, target, record, "key", value)


@pytest.mark.parametrize(
    "annotations", [{"bad": 1}, ["invalid"], {str(i): "x" * 65536 for i in range(5)}]
)
def test_invalid_or_excessive_existing_annotations_are_rejected(annotations):
    resource, target, record = selection()
    data = record.manifest
    data["metadata"]["annotations"] = annotations
    with pytest.raises(AppError):
        annotation_intent(resource, target, resource_record(resource, data, "team"), "key", "new")


@pytest.mark.parametrize(
    "status,state",
    [
        (401, MutationState.AUTH_ERROR),
        (403, MutationState.DENIED),
        (404, MutationState.NOT_FOUND),
        (409, MutationState.CONFLICT),
        (400, MutationState.REJECTED),
        (413, MutationState.REJECTED),
        (422, MutationState.REJECTED),
        (429, MutationState.UNCERTAIN),
        (500, MutationState.UNCERTAIN),
        (302, MutationState.UNCERTAIN),
    ],
)
def test_status_outcomes_are_distinct_and_no_unknown_success_is_inferred(status, state):
    assert status_result(status).state is state
