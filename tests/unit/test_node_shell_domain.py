"""Reviewed profile integrity and UID identity without SDK or terminal types."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.node_shell import (
    EXEC_ARGV,
    NodeShellIntent,
    OwnedPod,
    admitted_profile,
    new_intent,
    owned_pod,
    profile_manifest,
    validate_node,
    validate_node_descriptor,
)
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceAddress, ResourceTarget, SessionIdentity
from kuberich.errors import AppError


@pytest.fixture
def intent() -> NodeShellIntent:
    return new_intent(
        ResourceTarget(SessionIdentity("fixture", 3), "", "nodes", None, "worker-1", "node-uid"),
        "namespace-uid",
        NodeShellSettings(True, "registry.test/node@sha256:" + "a" * 64, "diagnostics"),
        4,
        "b" * 64,
    )


def node_manifest() -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": "worker-1", "uid": "node-uid"},
        "status": {"nodeInfo": {"operatingSystem": "linux"}},
    }


def test_fixed_profile_does_not_inherit_image_command_or_credentials(
    intent: NodeShellIntent,
) -> None:
    pod = profile_manifest(intent)
    assert intent.body == json.dumps(pod, sort_keys=True, separators=(",", ":")).encode()
    assert intent.profile_digest == hashlib.sha256(intent.body).hexdigest()
    assert intent.identity.hex == intent.operation_id
    assert isinstance(intent.target, ResourceAddress) and intent.target.uid is None
    assert intent.target.session == intent.node.session
    assert len(intent.effects) == 3 and "UID" in intent.effects[-1]
    assert EXEC_ARGV == ("/bin/sh",)
    spec = pod["spec"]
    assert spec["containers"][0]["command"] == ["/bin/sleep", "3600"]
    assert spec["containers"][0]["securityContext"] == {
        "privileged": True,
        "runAsUser": 0,
        "runAsGroup": 0,
    }
    assert all(spec[field] is True for field in ("hostPID", "hostIPC", "hostNetwork"))
    assert spec["automountServiceAccountToken"] is False and spec["enableServiceLinks"] is False
    assert spec["volumes"] == [
        {"name": "host-root", "hostPath": {"path": "/", "type": "Directory"}}
    ]
    assert "nodeName" not in spec and "tolerations" not in spec
    assert admitted_profile(intent, pod)
    validate_node(intent.node, node_manifest())
    validate_node_descriptor(ApiResource("", "v1", "nodes", "Node", False, frozenset({"get"})))


@pytest.mark.parametrize(
    "field,value",
    [
        ("group", "other.test"),
        ("version", "v2"),
        ("name", "pods"),
        ("kind", "OtherNode"),
        ("namespaced", True),
    ],
)
def test_descriptor_requires_core_v1_node(field: str, value: Any) -> None:
    resource = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get"}))
    with pytest.raises(AppError):
        validate_node_descriptor(replace(resource, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("group", "other.test"),
        ("resource", "pods"),
        ("namespace", "other"),
        ("container", "one"),
    ],
)
def test_target_requires_exact_cluster_scoped_node(
    intent: NodeShellIntent, field: str, value: Any
) -> None:
    target = replace(intent.node, **{field: value})
    with pytest.raises(AppError):
        validate_node(target, node_manifest())
    with pytest.raises(AppError):
        replace(intent, node=target)


@pytest.mark.parametrize(
    "path,value",
    [
        (("apiVersion",), "other/v1"),
        (("kind",), "OtherNode"),
        (("metadata", "name"), "worker-2"),
        (("metadata", "uid"), "replacement"),
        (("metadata", "deletionTimestamp"), "2026-01-01T00:00:00Z"),
        (("status", "nodeInfo", "operatingSystem"), "windows"),
        (("status",), {}),
        (("metadata",), None),
        (("status", "nodeInfo"), []),
    ],
)
def test_node_replacement_deletion_and_unknown_os_fail(
    intent: NodeShellIntent, path: tuple[str, ...], value: Any
) -> None:
    manifest = node_manifest()
    part = manifest
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = value
    with pytest.raises(AppError):
        validate_node(intent.node, manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("node", None),
        ("settings", None),
        ("settings", NodeShellSettings()),
        ("namespace_uid", ""),
        ("pod_name", "foreign"),
        ("pod_name", 7),
        ("operation_id", "bad"),
        ("operation_id", None),
        ("operation_id", "f" * 32),
        ("config_generation", -1),
        ("config_generation", True),
        ("connection_fingerprint", "wrong"),
        ("connection_fingerprint", 7),
    ],
)
def test_invalid_intents_fail_before_api_work(
    intent: NodeShellIntent, field: str, value: Any
) -> None:
    with pytest.raises(AppError):
        replace(intent, **{field: value})


def test_enumerated_kubernetes_defaults_quantity_normalization_and_pull_secret_binding(
    intent: NodeShellIntent,
) -> None:
    desired = profile_manifest(intent)
    defaulted = deepcopy(desired)
    defaulted["metadata"].update(
        {"resourceVersion": "123", "uid": "dry-run-uid", "managedFields": [{}]}
    )
    defaulted["status"] = {"phase": "Pending"}
    spec = defaulted["spec"]
    spec.update(
        {
            "schedulerName": "default-scheduler",
            "serviceAccountName": "default",
            "serviceAccount": "default",
            "securityContext": {},
            "priority": 0,
            "preemptionPolicy": "PreemptLowerPriority",
            "tolerations": [
                {"key": key, "operator": "Exists", "effect": "NoExecute", "tolerationSeconds": 300}
                for key in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
            ],
        }
    )
    container = spec["containers"][0]
    container.update(
        {
            "args": [],
            "env": [],
            "envFrom": [],
            "ports": [],
            "stdin": False,
            "stdinOnce": False,
            "tty": False,
        }
    )
    container["resources"]["requests"]["cpu"] = "0.01"
    container["resources"]["limits"]["memory"] = "134217728"
    container["volumeMounts"][0].update(
        {"mountPropagation": "None", "recursiveReadOnly": "Disabled"}
    )
    del container["volumeMounts"][0]["readOnly"]
    snapshot = deepcopy(defaulted)
    assert admitted_profile(intent, desired) == admitted_profile(intent, defaulted)
    assert defaulted == snapshot
    spec["imagePullSecrets"] = [{"name": "registry-auth"}]
    projected = admitted_profile(intent, defaulted)
    assert projected != admitted_profile(intent, desired)
    spec["nodeName"] = intent.node.name
    assert admitted_profile(intent, defaulted, scheduled=True) == projected
    with pytest.raises(AppError):
        admitted_profile(intent, defaulted)
    with pytest.raises(AppError):
        admitted_profile(intent, desired, scheduled=True)
    spec["nodeName"] = "other-node"
    with pytest.raises(AppError):
        admitted_profile(intent, defaulted, scheduled=True)


@pytest.mark.parametrize(
    "path,value",
    [
        (("apiVersion",), "apps/v1"),
        (("kind",), "OtherPod"),
        (("metadata", "name"), "foreign"),
        (("metadata", "namespace"), "other"),
        (("metadata", "ownerReferences"), [{"uid": "owner"}]),
        (("metadata", "finalizers"), ["stuck"]),
        (("spec", "schedulerName"), "custom"),
        (("spec", "priority"), False),
        (("spec", "serviceAccountName"), "privileged"),
        (("spec", "hostPID"), 1),
        (("spec", "hostIPC"), False),
        (("spec", "hostNetwork"), False),
        (("spec", "automountServiceAccountToken"), True),
        (("spec", "enableServiceLinks"), True),
        (("spec", "activeDeadlineSeconds"), 3601),
        (("spec", "nodeSelector"), {}),
        (("spec", "affinity"), {}),
        (("spec", "volumes"), []),
        (("spec", "initContainers"), [{"name": "injected"}]),
        (("spec", "ephemeralContainers"), [{}]),
        (("spec", "tolerations"), None),
        (("spec", "tolerations"), [{"key": "custom"}]),
        (("spec", "tolerations"), [{"key": "x"}] * 3),
        (("spec", "imagePullSecrets"), {}),
        (("spec", "imagePullSecrets"), [{}]),
        (("spec", "imagePullSecrets"), [{"name": "x"}] * 33),
        (("spec", "imagePullSecrets"), [{"name": "../secret"}]),
        (("spec", "containers"), []),
        (("spec", "containers"), None),
        (("spec", "containers"), [{}, {}]),
        (("spec", "unknown"), float("nan")),
    ],
)
def test_admission_drift_blocks_execution(
    intent: NodeShellIntent, path: tuple[str, ...], value: Any
) -> None:
    pod = profile_manifest(intent)
    part = pod
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = value
    with pytest.raises(AppError):
        admitted_profile(intent, pod)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "other"),
        ("image", "unapproved@sha256:" + "a" * 64),
        ("command", ["sh", "-c", "anything"]),
        ("args", ["injected"]),
        ("env", [{"name": "TOKEN", "value": "private"}]),
        ("envFrom", [{"secretRef": {"name": "private"}}]),
        ("securityContext", {"privileged": True, "runAsUser": 1, "runAsGroup": 0}),
        ("resources", {}),
        ("resources", {"requests": {}, "limits": {}}),
        (
            "resources",
            {
                "requests": {"cpu": "20m", "memory": "32Mi"},
                "limits": {"cpu": "250m", "memory": "128Mi"},
            },
        ),
        ("volumeMounts", []),
        ("volumeMounts", [{"name": "host-root", "mountPath": "/host", "readOnly": True}]),
        (
            "volumeMounts",
            [{"name": "host-root", "mountPath": "/host", "mountPropagation": "Bidirectional"}],
        ),
        ("volumeMounts", [{}, {}]),
        ("volumeMounts", None),
    ],
)
def test_container_injection_and_mount_drift_fail(
    intent: NodeShellIntent, field: str, value: Any
) -> None:
    pod = profile_manifest(intent)
    pod["spec"]["containers"][0][field] = value
    with pytest.raises(AppError):
        admitted_profile(intent, pod)


def test_duplicate_default_toleration_is_not_accepted(intent: NodeShellIntent) -> None:
    pod = profile_manifest(intent)
    item = {
        "key": "node.kubernetes.io/not-ready",
        "operator": "Exists",
        "effect": "NoExecute",
        "tolerationSeconds": 300,
    }
    pod["spec"]["tolerations"] = [item, item]
    with pytest.raises(AppError):
        admitted_profile(intent, pod)


def test_receipt_uid_survives_admission_drift_and_never_requires_resource_version(
    intent: NodeShellIntent,
) -> None:
    pod = profile_manifest(intent)
    pod["metadata"]["uid"] = "created-uid"
    pod["spec"]["hostPID"] = False
    owned = owned_pod(intent, pod)
    assert owned == OwnedPod(intent.pod_name, "diagnostics", "created-uid")
    assert (
        owned.target(intent).uid == "created-uid" and owned.target(intent).container == "diagnostic"
    )
    with pytest.raises(AppError):
        admitted_profile(intent, pod)
    with pytest.raises(AppError):
        replace(owned, name="foreign").target(intent)
    with pytest.raises(AppError):
        replace(owned, namespace="other").target(intent)
    with pytest.raises(AppError):
        replace(owned, uid="")


@pytest.mark.parametrize(
    "path,value",
    [
        (("apiVersion",), "v2"),
        (("kind",), "OtherPod"),
        (("metadata", "name"), "foreign"),
        (("metadata", "namespace"), "other"),
        (("metadata", "uid"), ""),
        (("metadata", "uid"), None),
    ],
)
def test_untrusted_receipt_does_not_establish_uid(
    intent: NodeShellIntent, path: tuple[str, ...], value: Any
) -> None:
    pod = profile_manifest(intent)
    part = pod
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = value
    with pytest.raises(AppError):
        owned_pod(intent, pod)
