"""Real parser/intent contracts for safe editor arguments and immutable YAML edits."""

import json
from dataclasses import replace

import pytest
import yaml

from kubetrol.domain.editing import (
    MAX_EDIT_BYTES,
    edit_preview,
    editable_manifest,
    edited_intent,
    editor_arguments,
    manifest_text,
    parse_manifest,
)
from kubetrol.domain.mutations import decode_patch
from kubetrol.domain.resources import ApiResource, resource_record
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError


def snapshot():
    resource = ApiResource("", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "patch"}))
    value = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "owned-one",
            "namespace": "team",
            "uid": "original-uid",
            "resourceVersion": "17",
            "creationTimestamp": "2026-01-01T00:00:00Z",
            "managedFields": [],
            "labels": {"original": "preserved"},
            "annotations": {"example.io/token": "sensitive-original"},
        },
        "data": {"nested/key~": "sensitive-old"},
        "status": {"phase": "server-owned"},
    }
    record = resource_record(resource, value, "team")
    target = ResourceTarget(
        SessionIdentity("kubetrol-test-one", 1),
        "",
        "configmaps",
        "team",
        "owned-one",
        "original-uid",
    )
    return resource, target, record


@pytest.mark.parametrize(
    "environment,expected",
    [
        ({}, ("vi",)),
        ({"EDITOR": "nano -w"}, ("nano", "-w")),
        ({"VISUAL": "vim -n", "EDITOR": "nano"}, ("vim", "-n")),
        ({"KUBETROL_EDITOR": '"/a path/vim" -n', "VISUAL": "nano"}, ("/a path/vim", "-n")),
        ({"EDITOR": 'vim "$(literal)" "$HOME" "a;b"'}, ("vim", "$(literal)", "$HOME", "a;b")),
    ],
)
def test_editor_argv_precedence_quoting_and_literal_shell_text(environment, expected):
    assert editor_arguments(environment) == expected


@pytest.mark.parametrize(
    "value",
    ["", "   ", '"unterminated', "-vim", 'vim "a\ncontrol"', "x" * 8193, "vi " + "x " * 32, None],
)
def test_editor_argv_refuses_malformed_controls_options_and_bounds(value):
    with pytest.raises(AppError, match="Editor must"):
        editor_arguments({"EDITOR": value})


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"x" * (MAX_EDIT_BYTES + 1),
        "not-bytes",
        b"\xff",
        b"x: [invalid",
        b"x: .nan",
        b"x: .inf",
        b"!!python/object:evil {}",
        b"x: !!timestamp 2026-01-01",
        b"x: !!set {a: null}",
        b"x: 1\nx: 2",
        b"x: {same: 1, same: 2}",
        b"1: x",
        b"x: {1: value}",
        b"x: &a []\ny: *a",
        b"---\nx: 1\n---\nx: 2",
        b"[]",
        b"null",
        b"x: [" + b"[" * 64 + b"0" + b"]" * 65,
        b"x: [" + b"0," * 100001 + b"0]",
        b'x: "\\uD800"',
    ],
)
def test_bounded_yaml_refuses_unsafe_invalid_non_json_and_ambiguous_input(data):
    with pytest.raises(AppError):
        parse_manifest(data)


def test_dates_strings_values_safe_loader_isolation_and_semantic_noop():
    resource, target, record = snapshot()
    baseline = editable_manifest(record)
    assert "status" not in baseline and "managedFields" not in baseline["metadata"]
    assert "managedFields" in record.manifest["metadata"] and "status" in record.manifest
    data = manifest_text(record, target)
    parsed = parse_manifest(data)
    assert parsed == baseline and "# Context: kubetrol-test-one" in data.decode()
    assert parse_manifest(b"date: 2026-01-01")["date"] == "2026-01-01"
    assert isinstance(yaml.safe_load("date: 2026-01-01")["date"], __import__("datetime").date)
    assert edited_intent(resource, target, record, b"# changed comments\n" + data) is None
    assert parse_manifest(b'x: [true, false, null, 2, 2.5, "string"]')["x"] == [
        True,
        False,
        None,
        2,
        2.5,
        "string",
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("apiVersion", "apps/v1"),
        ("kind", "Secret"),
        ("metadata", None),
        ("metadata.name", "replaced"),
        ("metadata.namespace", "other"),
        ("metadata.uid", "new"),
        ("metadata.resourceVersion", "18"),
        ("metadata.creationTimestamp", "changed"),
        ("metadata.managedFields", []),
        ("metadata.unknown", "extra"),
        ("status", {}),
    ],
)
def test_identity_server_metadata_and_status_are_immutable(field, value):
    resource, target, record = snapshot()
    data = editable_manifest(record)
    if "." in field:
        parent, key = field.split(".")
        data[parent][key] = value
    else:
        data[field] = value
    with pytest.raises(AppError):
        edited_intent(resource, target, record, json.dumps(data).encode())


def test_structural_add_remove_replace_preserves_raw_values_and_rejects_stale_uid():
    resource, target, record = snapshot()
    data = editable_manifest(record)
    del data["metadata"]["labels"]["original"]
    data["metadata"]["labels"]["new"] = "value"
    data["data"]["nested/key~"] = "sensitive-new"
    data["items"] = [False, 2]
    intent = edited_intent(resource, target, record, json.dumps(data).encode())
    operations = decode_patch(intent.body)
    assert operations[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "original-uid"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "17"},
    ]
    assert {"op": "replace", "path": "/data/nested~1key~0", "value": "sensitive-new"} in operations
    assert {"op": "remove", "path": "/metadata/labels/original"} in operations
    assert {"op": "add", "path": "/metadata/labels/new", "value": "value"} in operations
    preview = edit_preview(record, json.dumps(data).encode())
    assert "+    new: value" in preview and "sensitive-" not in preview
    assert "sensitive-new" in intent.body.decode() and "[REDACTED]" not in intent.body.decode()
    data = editable_manifest(record)
    data["data"]["nested/key~"] = "hidden-change"
    assert "hidden by" in edit_preview(record, json.dumps(data).encode())
    with pytest.raises(AppError):
        manifest_text(record, replace(target, uid="new-uid"))


@pytest.mark.parametrize(
    "old,new", [(1, True), ([1], [True]), ({"a": 1}, {"a": True}), ([1, 2], [1]), ("text", {})]
)
def test_changes_preserve_json_types_and_replace_lists_atomically(old, new):
    resource, target, record = snapshot()
    value = record.manifest
    value["extra"] = old
    record = resource_record(resource, value, "team")
    data = editable_manifest(record)
    data["extra"] = new
    intent = edited_intent(resource, target, record, json.dumps(data).encode())
    assert any(op["op"] == "replace" for op in decode_patch(intent.body)[2:])


def test_change_limit_rejects_partial_edit_and_dump_errors_are_safe(monkeypatch):
    resource, target, record = snapshot()
    data = editable_manifest(record)
    data["metadata"]["labels"].update({f"key{i}": "x" for i in range(129)})
    with pytest.raises(AppError, match="128"):
        edited_intent(resource, target, record, json.dumps(data).encode())

    def fail(*args, **kwargs):
        raise yaml.YAMLError("sensitive-error-content")

    monkeypatch.setattr(yaml, "safe_dump", fail)
    with pytest.raises(AppError) as error:
        manifest_text(record, target)
    assert "sensitive" not in str(error.value)
