"""Exhaustive deterministic operation scope, JSON, identity and effect boundaries."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from kuberich.domain.operations import (
    MAX_OPERATION_BYTES,
    DeleteOptions,
    ResourceAction,
    delete_intent,
    manual_job_name,
    operation_json,
    operation_path,
    snapshot_version,
    suspension_intent,
    trigger_intent,
)
from kuberich.domain.resources import resource_record
from kuberich.errors import AppError
from tests.support.operations import selection


def captured(alias="cm"):
    resource, target, value = selection(alias)
    return resource, target, resource_record(resource, value, target.namespace)


@pytest.mark.parametrize("policy", ["Foreground", "Background", "Orphan"])
@pytest.mark.parametrize("grace", [None, 0, 2147483647])
@pytest.mark.parametrize("alias", ["cm", "no"])
def test_delete_captures_exact_scope_uid_version_options_and_safe_effects(policy, grace, alias):
    resource, target, record = captured(alias)
    options = DeleteOptions(policy, grace)
    intent = delete_intent(resource, target, record, options)
    body = json.loads(intent.body)
    assert body["preconditions"] == {"uid": target.uid, "resourceVersion": "opaque-7"}
    assert body["propagationPolicy"] == policy
    assert body.get("gracePeriodSeconds") == grace
    assert intent.method == "DELETE" and intent.path.endswith("/" + target.name)
    assert policy in " ".join(intent.effects) and "private" not in repr(intent)
    assert "none observed" in intent.effects[-1]
    assert ("server default" if grace is None else f"{grace}s") in options.summary


@pytest.mark.parametrize(
    "policy,grace",
    [
        (None, None),
        ([], None),
        ("invalid", None),
        ("Foreground", -1),
        ("Foreground", True),
        ("Foreground", "0"),
        ("Orphan", 2147483648),
    ],
)
def test_delete_options_reject_invalid_types_and_bounds(policy, grace):
    with pytest.raises(AppError):
        DeleteOptions(policy, grace)


@pytest.mark.parametrize(
    "change",
    [
        "group",
        "family",
        "namespace",
        "container",
        "namespaced",
        "get",
        "delete",
        "bad-api",
        "bad-name",
        "action",
    ],
)
def test_operation_paths_reject_mismatched_unreadable_or_unsupported_scope(change):
    resource, target, _ = captured()
    action = ResourceAction.DELETE
    if change == "group":
        target = replace(target, group="apps")
    elif change == "family":
        target = replace(target, resource="pods")
    elif change == "namespace":
        target = replace(target, namespace=None)
    elif change == "container":
        target = replace(target, container="app")
    elif change == "namespaced":
        resource = replace(resource, namespaced=1)
    elif change in {"get", "delete"}:
        resource = replace(resource, verbs=resource.verbs - {change})
    elif change == "bad-api":
        resource = replace(resource, version="../v1")
    elif change == "bad-name":
        target = replace(target, name="../name")
    else:
        action = None
    with pytest.raises(AppError):
        operation_path(resource, target, action)


@pytest.mark.parametrize(
    "alias,action",
    [
        ("job", ResourceAction.TRIGGER),
        ("cm", ResourceAction.SUSPEND),
        ("cj", ResourceAction.RESUME),
    ],
)
def test_job_operation_scope_is_narrow(alias, action):
    resource, target, _ = captured(alias)
    if alias == "cj":
        resource = replace(resource, verbs=frozenset({"get"}))
    with pytest.raises(AppError):
        operation_path(resource, target, action)


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", "replacement"),
        ("name", "other"),
        ("namespace", "other"),
        ("resource_version", None),
        ("resource_version", "x" * 1025),
    ],
)
def test_snapshot_replacement_and_version_mismatch_are_refused(field, value):
    _, target, record = captured()
    with pytest.raises(AppError):
        snapshot_version(target, replace(record, **{field: value}))


def test_finalizers_and_already_terminating_are_deliberate():
    resource, target, value = selection()
    value["metadata"]["finalizers"] = ["example.io/cleanup"]
    record = resource_record(resource, value, target.namespace)
    intent = delete_intent(resource, target, record, DeleteOptions())
    assert intent.finalizers == ("example.io/cleanup",)
    assert "example.io/cleanup" in intent.effects[-1]
    value["metadata"]["deletionTimestamp"] = "2026-10-08T00:00:00Z"
    with pytest.raises(AppError, match="already terminating"):
        delete_intent(resource, target, resource_record(resource, value, "team"), DeleteOptions())


@pytest.mark.parametrize("kind", ["nonfinite", "nonjson", "unicode", "recursive", "oversized"])
def test_request_json_is_finite_utf8_and_bounded(kind):
    value = {"value": float("nan")}
    if kind == "nonjson":
        value = {"value": object()}
    elif kind == "unicode":
        value = {"value": "\ud800"}
    elif kind == "recursive":
        value["value"] = value
    elif kind == "oversized":
        value = {"value": "x" * MAX_OPERATION_BYTES}
    with pytest.raises(AppError):
        operation_json(value)


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "body-type",
        "empty",
        "big",
        "bad-json",
        "bad-utf8",
        "version",
        "action",
        "policy-missing",
        "precondition",
        "extra",
        "created-name",
        "grace",
        "finalizers-type",
        "finalizers-limit",
    ],
)
def test_immutable_delete_intent_cannot_hide_or_replace_effects(change):
    resource, target, record = captured()
    intent = delete_intent(resource, target, record, DeleteOptions())
    fields = {}
    body = json.loads(intent.body)
    if change == "identity":
        fields["identity"] = "invalid"
    elif change == "body-type":
        fields["body"] = bytearray(intent.body)
    elif change == "empty":
        fields["body"] = b""
    elif change == "big":
        fields["body"] = b"x" * (MAX_OPERATION_BYTES + 1)
    elif change == "bad-json":
        fields["body"] = b"{"
    elif change == "bad-utf8":
        fields["body"] = b"\xff"
    elif change == "version":
        fields["resource_version"] = "x" * 1025
    elif change == "action":
        fields["action"] = ResourceAction.SUSPEND
        resource, target, _ = captured("cj")
        fields.update(resource=resource, target=target)
    elif change == "policy-missing":
        body.pop("propagationPolicy")
    elif change == "precondition":
        body["preconditions"]["uid"] = "replacement"
    elif change == "extra":
        body["ignoreStoreReadErrorWithClusterBreakingPotential"] = True
    elif change == "created-name":
        fields["created_name"] = "other"
    elif change == "grace":
        body["gracePeriodSeconds"] = -1
    elif change == "finalizers-type":
        fields["finalizers"] = []
    else:
        fields["finalizers"] = tuple("f" for _ in range(65))
    fields.setdefault("body", operation_json(body))
    with pytest.raises(AppError):
        replace(intent, **fields)


def test_manual_job_has_repeatable_bounded_name_and_copies_only_template_fields():
    resource, target, value = selection("cj")
    value["spec"]["jobTemplate"]["metadata"].update(
        uid="never-copy", name="never-copy", ownerReferences=[{"uid": "never-copy"}]
    )
    record = resource_record(resource, value, "team")
    identity = uuid4()
    intent = trigger_intent(resource, target, record, identity)
    body = json.loads(intent.body)
    assert intent.method == "POST" and intent.path == "/apis/batch/v1/namespaces/team/jobs"
    assert intent.created_name == manual_job_name(target.name, identity)
    assert len(manual_job_name("long-name-" * 10, identity)) <= 63
    assert body["metadata"]["annotations"]["keep"] == "value"
    assert body["metadata"]["annotations"]["kuberich.io/source-uid"] == target.uid
    assert "never-copy" not in intent.body.decode()
    assert body["spec"] == value["spec"]["jobTemplate"]["spec"]
    assert "private-template" not in repr(intent) + " ".join(intent.effects)
    assert trigger_intent(resource, target, record, identity).body == intent.body


@pytest.mark.parametrize(
    "field",
    [
        "created_name",
        "apiVersion",
        "kind",
        "extra",
        "name",
        "namespace",
        "metadata-extra",
        "request",
        "spec",
        "labels",
    ],
)
def test_created_job_intent_cannot_change_its_reviewed_destination(field):
    resource, target, record = captured("cj")
    intent = trigger_intent(resource, target, record, uuid4())
    body, fields = json.loads(intent.body), {}
    if field == "created_name":
        fields[field] = "other"
    elif field in {"apiVersion", "kind"}:
        body[field] = "other"
    elif field == "extra":
        body["status"] = {}
    elif field in {"name", "namespace"}:
        body["metadata"][field] = "other"
    elif field == "metadata-extra":
        body["metadata"]["uid"] = "hidden"
    elif field == "request":
        body["metadata"]["annotations"]["kuberich.io/request"] = "other"
    else:
        if field == "spec":
            body[field] = []
        else:
            body["metadata"][field] = []
    with pytest.raises(AppError):
        replace(intent, body=operation_json(body), **fields)


def test_template_text_labels_annotations_and_missing_spec_are_validated():
    resource, target, value = selection("cj")
    for field in ("labels", "annotations"):
        metadata = value["spec"]["jobTemplate"]["metadata"]
        previous = metadata[field]
        metadata[field] = {"owned": False}
        with pytest.raises(AppError, match="text mappings"):
            trigger_intent(resource, target, resource_record(resource, value, "team"), uuid4())
        metadata[field] = previous
    value["spec"]["jobTemplate"].pop("spec")
    with pytest.raises(AppError):
        trigger_intent(resource, target, resource_record(resource, value, "team"), uuid4())


@pytest.mark.parametrize("alias", ["job", "cj"])
@pytest.mark.parametrize("action", [ResourceAction.SUSPEND, ResourceAction.RESUME])
def test_suspension_is_one_atomic_guarded_boolean_effect(alias, action):
    resource, target, value = selection(alias)
    value["spec"]["suspend"] = action is ResourceAction.RESUME
    intent = suspension_intent(resource, target, resource_record(resource, value, "team"), action)
    assert json.loads(intent.body)[-1] == {
        "op": "add",
        "path": "/spec/suspend",
        "value": action is ResourceAction.SUSPEND,
    }
    with pytest.raises(AppError):
        suspension_intent(
            resource,
            target,
            resource_record(resource, value, "team"),
            ResourceAction.TRIGGER if alias == "cj" else ResourceAction.DELETE,
        )
    value["spec"]["suspend"] = "false"
    with pytest.raises(AppError):
        suspension_intent(resource, target, resource_record(resource, value, "team"), action)
    value["spec"]["suspend"] = action is ResourceAction.SUSPEND
    with pytest.raises(AppError):
        suspension_intent(resource, target, resource_record(resource, value, "team"), action)
