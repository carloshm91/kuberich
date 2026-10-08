"""Action applicability, immutable effects, ownership and actual controller status decisions."""

import copy
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kubetrol.domain.mutations import MutationIntent, decode_patch, mutation_path, patch_intent
from kubetrol.domain.resources import resource_record
from kubetrol.domain.workloads import (
    WorkloadAction,
    applicable,
    controlled_by,
    replica_count,
    require_rolling,
    restart_intent,
    revision_template,
    rollout_progress,
)
from kubetrol.errors import AppError
from kubetrol.ui.chrome import workload_shortcuts
from tests.support.workloads import selection


@pytest.mark.parametrize(
    "text",
    [None, True, 1, "", "-1", "+1", "1.5", " 1", "1 ", "\u0661", "2147483648", "10000000000"],
)
def test_replica_count_rejects_invalid_limits(text):
    with pytest.raises(AppError):
        replica_count(text)


@pytest.mark.parametrize(
    "text,expected", [("0", 0), ("1", 1), ("0001", 1), ("2147483647", 2147483647)]
)
def test_replica_count_valid(text, expected):
    assert replica_count(text) == expected


@pytest.mark.parametrize(
    "resource", ["deployments", "statefulsets", "daemonsets", "replicasets", "configmaps"]
)
@pytest.mark.parametrize("readonly", [False, True])
def test_workload_hints_offer_only_applicable_actions(resource, readonly):
    keys = {key for key, label in workload_shortcuts(resource, readonly)}
    assert (":scale" in keys) == (
        not readonly and resource in {"deployments", "statefulsets", "replicasets"}
    )
    assert (":restart" in keys) == (
        not readonly and resource in {"deployments", "statefulsets", "daemonsets"}
    )
    assert (":rollback" in keys) == (":restart" in keys)
    assert (":rollout" in keys) == (resource in {"deployments", "statefulsets", "daemonsets"})
    assert "y" in keys and len(keys) <= 12


@pytest.mark.parametrize("action", list(WorkloadAction))
def test_applicable_resources(action):
    resource, _, _ = selection()
    applicable(resource, action)
    for update in ({"group": "other"}, {"name": "pods"}, {"namespaced": False}):
        with pytest.raises(AppError):
            applicable(replace(resource, **update), action)
    if action is WorkloadAction.SCALE:
        with pytest.raises(AppError):
            applicable(selection("daemonsets")[0], action)
    else:
        with pytest.raises(AppError):
            applicable(selection("replicasets")[0], action)


@pytest.mark.parametrize("metadata", [None, {}, {"annotations": {"retained": "private-value"}}])
def test_restart_preserves_template_annotations_and_captures_timestamp(metadata):
    resource, target, value = selection()
    if metadata is None:
        value["spec"]["template"].pop("metadata")
    else:
        value["spec"]["template"]["metadata"] = metadata
    record = resource_record(resource, value, "team")
    intent = restart_intent(resource, target, record, datetime(2026, 10, 8, tzinfo=UTC))
    ops = decode_patch(intent.body)
    assert ops[-1]["value"]["kubectl.kubernetes.io/restartedAt"] == "2026-10-08T00:00:00.000000Z"
    assert "private-value" not in repr(intent)
    assert record.manifest == value
    with pytest.raises(AppError):
        restart_intent(resource, target, record, datetime(2026, 10, 8))


@pytest.mark.parametrize("spec", [{"paused": True}, {"updateStrategy": {"type": "OnDelete"}}])
def test_paused_manual_restart_refused(spec):
    resource, _, value = selection()
    value["spec"].update(spec)
    with pytest.raises(AppError):
        require_rolling(resource_record(resource, value, "team"))


def test_related_revisions_preserve_payload_strip_only_controller_directive():
    resource, target, value = selection()
    item = copy.deepcopy(value)
    item["metadata"]["ownerReferences"] = [{"uid": target.uid, "controller": True}]
    item["metadata"]["annotations"] = {"deployment.kubernetes.io/revision": "3"}
    item["spec"]["template"]["metadata"]["labels"]["pod-template-hash"] = "owned"
    assert controlled_by(item, target)
    rev, template = revision_template(item, resource)
    assert rev == 3 and "pod-template-hash" not in template["metadata"]["labels"]
    assert "pod-template-hash" in item["spec"]["template"]["metadata"]["labels"]
    item["metadata"]["ownerReferences"] = [
        {"uid": "other", "controller": True},
        {"uid": target.uid, "controller": False},
    ]
    assert not controlled_by(item, target)
    item["metadata"]["ownerReferences"] = {}
    with pytest.raises(AppError):
        controlled_by(item, target)
    data = {"revision": 2, "data": {"spec": {"template": {**template, "$patch": "replace"}}}}
    assert revision_template(data, selection("statefulsets")[0]) == (2, template)
    data["data"]["spec"]["template"]["$patch"] = "merge"
    with pytest.raises(AppError):
        revision_template(data, selection("daemonsets")[0])
    data["data"]["spec"]["template"].pop("$patch")
    assert revision_template(data, selection("daemonsets")[0]) == (2, template)
    data["revision"] = 0
    with pytest.raises(AppError):
        revision_template(data, selection("daemonsets")[0])
    data["revision"] = 1
    data["data"]["spec"]["template"]["spec"]["containers"] = {}
    with pytest.raises(AppError):
        revision_template(data, selection("statefulsets")[0])


@pytest.mark.parametrize("family", ["deployments", "statefulsets", "daemonsets"])
def test_controller_complete_progress_and_unobserved(family):
    resource, _, value = selection(family)

    def progress():
        return rollout_progress(resource, resource_record(resource, value, "team"))

    assert progress().state == "Complete"
    value["status"]["observedGeneration"] = 1
    assert not progress().terminal
    value["status"]["observedGeneration"] = 2
    field = "updatedNumberScheduled" if family == "daemonsets" else "updatedReplicas"
    value["status"][field] = 1
    assert progress().state == "Progressing"
    value["status"][field] = 2
    if family == "statefulsets":
        value["status"]["currentRevision"] = "old"
        assert progress().state == "Progressing"
        value["spec"]["updateStrategy"] = {"rollingUpdate": {"partition": 1}}
        value["status"]["updatedReplicas"] = 1
        assert progress().state == "Complete"
    value["spec"]["updateStrategy"] = {"type": "OnDelete"}
    assert progress().state == "Manual"
    value["spec"]["paused"] = True
    assert progress().state == "Paused"


@pytest.mark.parametrize(
    "change",
    [
        {"observedGeneration": True},
        {"observedGeneration": -1},
        {"conditions": {}},
        {
            "conditions": [
                {"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}
            ]
        },
    ],
)
def test_failed_and_invalid_controller_status(change):
    resource, _, value = selection()
    value["status"].update(change)
    if "conditions" in change and isinstance(change["conditions"], list):
        assert (
            rollout_progress(resource, resource_record(resource, value, "team")).state == "Failed"
        )
    else:
        with pytest.raises(AppError):
            rollout_progress(resource, resource_record(resource, value, "team"))


def test_scale_subresource_uses_narrow_parent_read_scope():
    resource, target, value = selection()
    resource = replace(resource, verbs=frozenset({"get"}))
    intent = patch_intent(
        resource,
        target,
        resource_record(resource, value, "team"),
        [{"op": "add", "path": "/spec/replicas", "value": 0}],
        subresource="scale",
    )
    assert intent.path.endswith("/deployments/owned-one/scale")
    for suffix in ("status", "../scale"):
        with pytest.raises(AppError):
            mutation_path(resource, target, suffix)
    with pytest.raises(AppError):
        mutation_path(
            replace(resource, name="daemonsets"), replace(target, resource="daemonsets"), "scale"
        )
    for effect in (
        {"op": "remove", "path": "/spec/replicas"},
        {"op": "add", "path": "/data/x", "value": 1},
        {"op": "add", "path": "/spec/replicas", "value": True},
        {"op": "add", "path": "/spec/replicas", "value": -1},
    ):
        with pytest.raises(AppError):
            patch_intent(
                resource,
                target,
                resource_record(resource, value, "team"),
                [effect],
                subresource="scale",
            )
    with pytest.raises(AppError):
        patch_intent(
            resource,
            target,
            resource_record(resource, value, "team"),
            [{"op": "add", "path": "/spec/replicas", "value": 1}] * 2,
            subresource="scale",
        )
    assert isinstance(intent, MutationIntent)
