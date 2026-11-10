"""Fixed node-shell intent, admission projection and returned-UID ownership."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.quantities import parse_quantity
from kuberich.domain.resources import ApiResource, api_segment, resource_object, resource_text
from kuberich.domain.targets import ResourceAddress, ResourceTarget
from kuberich.errors import AppError

CONTAINER = "diagnostic"
EXEC_ARGV = ("/bin/sh",)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise AppError("Node-shell profile requires finite JSON data.") from None


def validate_node_descriptor(resource: ApiResource) -> None:
    if (resource.group, resource.version, resource.name, resource.kind) != (
        "",
        "v1",
        "nodes",
        "Node",
    ) or resource.namespaced is not False:
        raise AppError("Node shell requires an explicitly discovered core/v1 Node.")


def validate_node(target: ResourceTarget, value: object) -> None:
    node = resource_object(value)
    metadata = resource_object(node.get("metadata"))
    status = resource_object(node.get("status", {}))
    info = resource_object(status.get("nodeInfo", {}))
    if (
        target.group != ""
        or target.resource != "nodes"
        or target.namespace is not None
        or target.container is not None
        or node.get("apiVersion") != "v1"
        or node.get("kind") != "Node"
        or metadata.get("name") != target.name
        or metadata.get("uid") != target.uid
        or metadata.get("deletionTimestamp") is not None
        or info.get("operatingSystem") != "linux"
    ):
        raise AppError("Node shell requires the captured, live Linux Node UID.")


@dataclass(frozen=True, slots=True, repr=False)
class NodeShellIntent:
    node: ResourceTarget
    namespace_uid: str
    settings: NodeShellSettings
    pod_name: str
    operation_id: str
    config_generation: int
    connection_fingerprint: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node, ResourceTarget)
            or not isinstance(self.settings, NodeShellSettings)
            or self.node.group != ""
            or self.node.resource != "nodes"
            or self.node.namespace is not None
            or self.node.container is not None
            or not self.settings.enabled
            or self.settings.namespace is None
            or self.settings.image is None
        ):
            raise AppError("Node-shell intent requires enabled settings and an exact Node target.")
        resource_text(self.namespace_uid)
        api_segment(self.node.name)
        if (
            not isinstance(self.pod_name, str)
            or re.fullmatch(r"kuberich-node-shell-[a-f0-9]{32}", self.pod_name) is None
        ):
            raise AppError("Node-shell Pod name must be a fresh operation name.")
        if (
            not isinstance(self.operation_id, str)
            or re.fullmatch(r"[a-f0-9]{32}", self.operation_id) is None
        ):
            raise AppError("Node-shell operation identity must be UUID hex.")
        if self.pod_name != "kuberich-node-shell-" + self.operation_id:
            raise AppError("Node-shell Pod name must match the reviewed operation identity.")
        if type(self.config_generation) is not int or self.config_generation < 0:
            raise AppError("Node-shell configuration generation must be nonnegative.")
        if (
            not isinstance(self.connection_fingerprint, str)
            or re.fullmatch(r"[a-f0-9]{64}", self.connection_fingerprint) is None
        ):
            raise AppError("Node-shell connection fingerprint must be SHA-256 hex.")

    @property
    def target(self) -> ResourceAddress:
        return ResourceAddress(
            self.node.session, "", "pods", self.settings.namespace, self.pod_name
        )

    @property
    def body(self) -> bytes:
        return _canonical(profile_manifest(self))

    @property
    def profile_digest(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def identity(self) -> UUID:
        return UUID(hex=self.operation_id)

    @property
    def effects(self) -> tuple[str, ...]:
        return (
            "Create the reviewed diagnostic Pod",
            "Run /bin/sh in the diagnostic container",
            "Delete only the Pod UID returned by this create",
        )


def new_intent(
    node: ResourceTarget,
    namespace_uid: str,
    settings: NodeShellSettings,
    config_generation: int,
    connection_fingerprint: str,
) -> NodeShellIntent:
    operation = uuid4().hex
    return NodeShellIntent(
        node,
        namespace_uid,
        settings,
        "kuberich-node-shell-" + operation,
        operation,
        config_generation,
        connection_fingerprint,
    )


def profile_manifest(intent: NodeShellIntent) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": intent.pod_name,
            "namespace": intent.settings.namespace,
            "labels": {
                "app.kubernetes.io/name": "kuberich-node-shell",
                "kuberich.io/operation": intent.operation_id,
            },
        },
        "spec": {
            "containers": [
                {
                    "name": CONTAINER,
                    "image": intent.settings.image,
                    "command": ["/bin/sleep", str(intent.settings.session_timeout_seconds)],
                    "imagePullPolicy": "IfNotPresent",
                    "resources": {
                        "requests": intent.settings.requests.to_mapping(),
                        "limits": intent.settings.limits.to_mapping(),
                    },
                    "securityContext": {"privileged": True, "runAsUser": 0, "runAsGroup": 0},
                    "volumeMounts": [
                        {"name": "host-root", "mountPath": "/host", "readOnly": False}
                    ],
                    "terminationMessagePath": "/dev/termination-log",
                    "terminationMessagePolicy": "File",
                }
            ],
            "volumes": [{"name": "host-root", "hostPath": {"path": "/", "type": "Directory"}}],
            "hostPID": True,
            "hostIPC": True,
            "hostNetwork": True,
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": 5,
            "activeDeadlineSeconds": intent.settings.session_timeout_seconds,
            "os": {"name": "linux"},
            "dnsPolicy": "ClusterFirstWithHostNet",
            "nodeSelector": {"kubernetes.io/os": "linux"},
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchFields": [
                                    {
                                        "key": "metadata.name",
                                        "operator": "In",
                                        "values": [intent.node.name],
                                    }
                                ]
                            }
                        ]
                    }
                }
            },
        },
    }


def _drift() -> AppError:
    return AppError(
        "Admission changed the reviewed diagnostic profile; shell execution is blocked."
    )


def _defaults(mapping: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, expected in defaults.items():
        if key in mapping and _canonical(mapping.pop(key)) != _canonical(expected):
            raise _drift()


def admitted_profile(intent: NodeShellIntent, value: object, *, scheduled: bool = False) -> bytes:
    """Validate complete spec, allowing only enumerated API/admission defaults.

    Pull-secret references are not mounted credentials. Their names are bound in
    the returned bytes, so the service compares dry-run, create and fresh reads.
    Metadata/status are deliberately excluded from the execution projection.
    """
    pod = resource_object(value)
    metadata = resource_object(pod.get("metadata"))
    if (
        pod.get("apiVersion") != "v1"
        or pod.get("kind") != "Pod"
        or metadata.get("name") != intent.pod_name
        or metadata.get("namespace") != intent.settings.namespace
        or metadata.get("ownerReferences")
        or metadata.get("finalizers")
    ):
        raise _drift()
    # Copy through JSON so projection never mutates a transport-owned response.
    spec = resource_object(json.loads(_canonical(resource_object(pod.get("spec")))))
    desired = profile_manifest(intent)["spec"]
    _defaults(
        spec,
        {
            "schedulerName": "default-scheduler",
            "serviceAccountName": "default",
            "serviceAccount": "default",
            "securityContext": {},
            "priority": 0,
            "preemptionPolicy": "PreemptLowerPriority",
        },
    )
    binding = spec.pop("nodeName", "")
    if (scheduled and binding != intent.node.name) or (not scheduled and binding):
        raise _drift()
    tolerations = spec.pop("tolerations", [])
    allowed = [
        {"key": key, "operator": "Exists", "effect": "NoExecute", "tolerationSeconds": 300}
        for key in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
    ]
    if (
        not isinstance(tolerations, list)
        or len(tolerations) > 2
        or any(item not in allowed for item in tolerations)
        or len({_canonical(item) for item in tolerations}) != len(tolerations)
    ):
        raise _drift()
    pull_secrets = spec.pop("imagePullSecrets", [])
    if (
        not isinstance(pull_secrets, list)
        or len(pull_secrets) > 32
        or any(not isinstance(item, dict) or set(item) != {"name"} for item in pull_secrets)
    ):
        raise _drift()
    for secret in pull_secrets:
        api_segment(secret["name"])
    containers = spec.get("containers")
    if not isinstance(containers, list) or len(containers) != 1:
        raise _drift()
    container = resource_object(containers[0])
    _defaults(
        container,
        {
            "args": [],
            "env": [],
            "envFrom": [],
            "ports": [],
            "stdin": False,
            "stdinOnce": False,
            "tty": False,
        },
    )
    resources = resource_object(container.get("resources"))
    if set(resources) != {"requests", "limits"}:
        raise _drift()
    for kind in ("requests", "limits"):
        quantities = resource_object(resources[kind])
        expected = desired["containers"][0]["resources"][kind]
        if set(quantities) != {"cpu", "memory"} or any(
            parse_quantity(quantities[key]) != parse_quantity(expected[key]) for key in expected
        ):
            raise _drift()
        resources[kind] = expected
    mounts = container.get("volumeMounts")
    if isinstance(mounts, list) and len(mounts) == 1:
        mount = resource_object(mounts[0])
        _defaults(mount, {"mountPropagation": "None", "recursiveReadOnly": "Disabled"})
        mount.setdefault("readOnly", False)
    if _canonical(spec) != _canonical(desired):
        raise _drift()
    return _canonical({"spec": spec, "imagePullSecrets": pull_secrets})


@dataclass(frozen=True, slots=True)
class OwnedPod:
    name: str
    namespace: str
    uid: str

    def __post_init__(self) -> None:
        api_segment(self.name)
        api_segment(self.namespace)
        resource_text(self.uid)

    def target(self, intent: NodeShellIntent) -> ResourceTarget:
        if self.name != intent.pod_name or self.namespace != intent.settings.namespace:
            raise AppError("Owned Pod does not match the reviewed operation.")
        return ResourceTarget(
            intent.node.session, "", "pods", self.namespace, self.name, self.uid, CONTAINER
        )


def owned_pod(intent: NodeShellIntent, value: object) -> OwnedPod:
    """Only a successful create response may be passed here, never a later GET."""
    pod = resource_object(value)
    metadata = resource_object(pod.get("metadata"))
    if (
        pod.get("apiVersion") != "v1"
        or pod.get("kind") != "Pod"
        or metadata.get("name") != intent.pod_name
        or metadata.get("namespace") != intent.settings.namespace
    ):
        raise AppError("The create response did not establish the diagnostic Pod identity.")
    return OwnedPod(
        intent.pod_name, str(intent.settings.namespace), resource_text(metadata.get("uid"))
    )
