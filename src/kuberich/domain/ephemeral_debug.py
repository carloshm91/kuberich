"""Bounded append-only debug declarations, reviewed identity and remote observations."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from kuberich.domain.resources import api_segment, resource_object, resource_text
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_CONTAINERS = 4096
MAX_ROWS = 256


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise AppError("Debug review requires finite UTF-8 JSON data.") from None


def _name(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value) is None
    ):
        raise AppError("Debug container names must be DNS labels of at most 63 characters.")
    return value


def new_debug_name() -> str:
    return "debug-" + uuid4().hex[:16]


@dataclass(frozen=True, slots=True)
class EphemeralDebugOptions:
    name: str
    image: str
    command: tuple[str, ...]
    target_container: str | None = None
    run_as_user: int = 1000
    run_as_group: int = 1000
    read_only_root_filesystem: bool = True

    def __post_init__(self) -> None:
        _name(self.name)
        if (
            not isinstance(self.image, str)
            or len(self.image) > 1024
            or re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}", self.image) is None
        ):
            raise AppError(
                "Select an explicit image pinned with @sha256 and 64 lowercase hex digits."
            )
        if not isinstance(self.command, tuple) or not 1 <= len(self.command) <= 32:
            raise AppError("Debug command requires a literal tuple of 1 to 32 arguments.")
        for argument in self.command:
            validate_argument(argument)
        command_size = sum(len(argument.encode("utf-8")) for argument in self.command)
        if command_size > 8192:
            raise AppError("Debug command exceeds 8192 UTF-8 bytes.")
        if self.target_container is not None:
            _name(self.target_container)
        for identity in (self.run_as_user, self.run_as_group):
            if type(identity) is not int or not 1 <= identity <= 2**31 - 1:
                raise AppError("Debug user and group must be positive 32-bit identities.")
        if type(self.read_only_root_filesystem) is not bool:
            raise AppError("Read-only root filesystem must be an explicit boolean.")


def declaration(options: EphemeralDebugOptions) -> dict[str, Any]:
    value: dict[str, Any] = {
        "name": options.name,
        "image": options.image,
        "command": list(options.command),
        "imagePullPolicy": "IfNotPresent",
        "stdin": True,
        "stdinOnce": False,
        "tty": True,
        "terminationMessagePath": "/dev/termination-log",
        "terminationMessagePolicy": "File",
        "securityContext": {
            "privileged": False,
            "allowPrivilegeEscalation": False,
            "runAsNonRoot": True,
            "runAsUser": options.run_as_user,
            "runAsGroup": options.run_as_group,
            "readOnlyRootFilesystem": options.read_only_root_filesystem,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }
    if options.target_container is not None:
        value["targetContainerName"] = options.target_container
    return value


def _entries(value: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    raw = value.get(field_name, [])
    if not isinstance(raw, list) or len(raw) > MAX_CONTAINERS:
        raise AppError(
            "Container declarations/status are malformed or exceed the complete-read limit."
        )
    return [resource_object(entry) for entry in raw]


def _pod(target: ResourceTarget, value: object, *, live: bool = False) -> dict[str, Any]:
    pod = resource_object(value)
    metadata = resource_object(pod.get("metadata"))
    if (
        target.group != ""
        or target.resource != "pods"
        or target.namespace is None
        or pod.get("apiVersion") != "v1"
        or pod.get("kind") != "Pod"
        or metadata.get("name") != target.name
        or metadata.get("namespace") != target.namespace
        or metadata.get("uid") != target.uid
    ):
        raise AppError("Debug operation requires the exact captured core/v1 Pod UID and address.")
    api_segment(target.name)
    api_segment(target.namespace)
    resource_text(metadata.get("uid"))
    resource_text(metadata.get("resourceVersion"))
    if live:
        status = resource_object(pod.get("status", {}))
        spec = resource_object(pod.get("spec"))
        annotations = resource_object(metadata.get("annotations", {}))
        if (
            metadata.get("deletionTimestamp") is not None
            or status.get("phase") != "Running"
            or "kubernetes.io/config.mirror" in annotations
            or resource_object(spec.get("os", {})).get("name", "linux") != "linux"
        ):
            raise AppError(
                "Debug addition requires a live, non-mirror Linux Pod with a running sandbox."
            )
    return pod


def _all_names(spec: dict[str, Any]) -> tuple[str, ...]:
    names = tuple(
        _name(entry.get("name"))
        for key in ("containers", "initContainers", "ephemeralContainers")
        for entry in _entries(spec, key)
    )
    if (
        not _entries(spec, "containers")
        or len(names) > MAX_CONTAINERS
        or len(set(names)) != len(names)
    ):
        raise AppError(
            "Pod container names are missing, ambiguous or exceed the complete-read limit."
        )
    return names


@dataclass(frozen=True, slots=True)
class ContainerInstance:
    name: str
    category: str
    container_id: str | None
    restart_count: int | None
    started_at: str | None


def _running(name: str, category: str, statuses: list[dict[str, Any]]) -> ContainerInstance:
    matches = [entry for entry in statuses if entry.get("name") == name]
    if len(matches) != 1:
        raise AppError("Selected container has missing or ambiguous running status.")
    entry = matches[0]
    state = resource_object(entry.get("state"))
    if set(state) != {"running"}:
        raise AppError("Selected container does not have one existing running instance.")
    running = resource_object(state["running"])
    container_id, restarts, started = (
        entry.get("containerID"),
        entry.get("restartCount"),
        running.get("startedAt"),
    )
    for text in (container_id, started):
        if text is not None:
            resource_text(text)
    if restarts is not None and (type(restarts) is not int or restarts < 0):
        raise AppError("Container restart count is invalid.")
    return ContainerInstance(name, category, container_id, restarts, started)


def _target_instance(pod: dict[str, Any], name: str | None) -> ContainerInstance | None:
    if name is None:
        return None
    spec, status = resource_object(pod.get("spec")), resource_object(pod.get("status", {}))
    for category, status_key in (
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
    ):
        if any(entry.get("name") == name for entry in _entries(spec, category)):
            return _running(name, category, _entries(status, status_key))
    raise AppError("A debug target must be a freshly running regular or init container.")


def _fingerprints(entries: list[dict[str, Any]]) -> tuple[bytes, ...]:
    return tuple(hashlib.sha256(_canonical(entry)).digest() for entry in entries)


def _inherited(pod: dict[str, Any]) -> bytes:
    spec = resource_object(pod.get("spec"))
    security = resource_object(spec.get("securityContext", {}))
    facts = {
        key: spec.get(key, False)
        for key in ("hostPID", "hostIPC", "hostNetwork", "shareProcessNamespace")
    }
    if any(type(value) is not bool for value in facts.values()):
        raise AppError("Inherited Pod namespaces are malformed.")
    identity: dict[str, Any] = {}
    for key in ("runAsUser", "runAsGroup", "fsGroup"):
        if key in security:
            if type(security[key]) is not int or not 0 <= security[key] <= 2**31 - 1:
                raise AppError("Inherited Pod identity is malformed.")
            identity[key] = security[key]
    if "runAsNonRoot" in security:
        if type(security["runAsNonRoot"]) is not bool:
            raise AppError("Inherited Pod non-root policy is malformed.")
        identity["runAsNonRoot"] = security["runAsNonRoot"]
    facts["securityContext"] = identity
    facts["serviceAccountName"] = api_segment(spec.get("serviceAccountName", "default"))
    facts["imagePullSecrets"] = [
        api_segment(entry.get("name")) for entry in _entries(spec, "imagePullSecrets")
    ]
    return _canonical(facts)


def _workload(spec: dict[str, Any]) -> bytes:
    return hashlib.sha256(
        _canonical({key: value for key, value in spec.items() if key != "ephemeralContainers"})
    ).digest()


@dataclass(frozen=True, slots=True, repr=False)
class EphemeralDebugIntent:
    target: ResourceTarget
    options: EphemeralDebugOptions
    resource_version: str
    target_instance: ContainerInstance | None
    previous_entries: tuple[bytes, ...]
    inherited: bytes
    pod_spec_fingerprint: bytes
    identity: UUID = field(default_factory=uuid4)

    @property
    def path(self) -> str:
        return (
            "/api/v1/namespaces/"
            + api_segment(self.target.namespace)
            + "/pods/"
            + api_segment(self.target.name)
            + "/ephemeralcontainers"
        )

    @property
    def body(self) -> bytes:
        entry = declaration(self.options)
        return _canonical(
            [
                {"op": "test", "path": "/metadata/uid", "value": self.target.uid},
                {"op": "test", "path": "/metadata/resourceVersion", "value": self.resource_version},
                {
                    "op": "add",
                    "path": "/spec/ephemeralContainers/-"
                    if self.previous_entries
                    else "/spec/ephemeralContainers",
                    "value": entry if self.previous_entries else [entry],
                },
            ]
        )

    @property
    def effects(self) -> tuple[str, ...]:
        return (
            "Add permanently to this Pod's spec",
            "The debug entry cannot be removed or restarted",
            "Disconnecting may leave the remote process running",
        )


def prepare_intent(
    target: ResourceTarget, value: object, options: EphemeralDebugOptions
) -> EphemeralDebugIntent:
    pod = _pod(target, value, live=True)
    spec = resource_object(pod.get("spec"))
    if options.name in _all_names(spec):
        raise AppError("This container name already exists, including completed debug entries.")
    return EphemeralDebugIntent(
        target,
        options,
        resource_text(resource_object(pod["metadata"])["resourceVersion"]),
        _target_instance(pod, options.target_container),
        _fingerprints(_entries(spec, "ephemeralContainers")),
        _inherited(pod),
        _workload(spec),
    )


def validate_current(
    intent: EphemeralDebugIntent, value: object, *, require_version: bool = True
) -> None:
    pod = _pod(intent.target, value, live=True)
    if require_version and pod["metadata"]["resourceVersion"] != intent.resource_version:
        raise AppError("Pod resourceVersion changed; prepare and confirm a new debug review.")
    spec = resource_object(pod.get("spec"))
    if (
        intent.options.name in _all_names(spec)
        or _fingerprints(_entries(spec, "ephemeralContainers")) != intent.previous_entries
    ):
        raise AppError("Pod debug declarations changed; prepare a new review.")
    if (
        _target_instance(pod, intent.options.target_container) != intent.target_instance
        or _inherited(pod) != intent.inherited
        or _workload(spec) != intent.pod_spec_fingerprint
    ):
        raise AppError("The reviewed target instance or inherited Pod context changed.")


@dataclass(frozen=True, slots=True)
class AppendIdentity:
    target: ResourceTarget
    name: str
    resource_version: str


def append_identity(intent: EphemeralDebugIntent, value: object) -> AppendIdentity:
    pod = _pod(intent.target, value)
    entries = _entries(resource_object(pod.get("spec")), "ephemeralContainers")
    if sum(entry.get("name") == intent.options.name for entry in entries) != 1:
        raise AppError("The response did not establish exactly one reviewed debug addition.")
    return AppendIdentity(intent.target, intent.options.name, pod["metadata"]["resourceVersion"])


def admitted_profile(intent: EphemeralDebugIntent, value: object) -> bytes:
    pod = _pod(intent.target, value)
    spec = resource_object(pod.get("spec"))
    _all_names(spec)
    if _workload(spec) != intent.pod_spec_fingerprint:
        raise AppError("The response changed the existing workload Pod specification.")
    entries = _entries(spec, "ephemeralContainers")
    if (
        len(entries) != len(intent.previous_entries) + 1
        or _fingerprints(entries[:-1]) != intent.previous_entries
    ):
        raise AppError("Admission changed the existing ephemeral declarations or addition count.")
    # Canonical round-trip avoids mutating a transport-owned object.
    entry = resource_object(json.loads(_canonical(entries[-1])))
    for key, default in {
        "resources": {},
        "stdinOnce": False,
        "terminationMessagePath": "/dev/termination-log",
        "terminationMessagePolicy": "File",
    }.items():
        if key == "resources":
            if entry.pop(key, {}) != default:
                raise AppError("Admission changed the reviewed debug resource profile.")
        else:
            entry.setdefault(key, default)
    profile = _canonical(entry)
    if profile != _canonical(declaration(intent.options)):
        raise AppError("Admission changed the reviewed debug declaration; attachment is blocked.")
    return profile


def verify_debug_declaration(
    intent: EphemeralDebugIntent, value: object, expected_profile: bytes
) -> None:
    pod = _pod(intent.target, value, live=True)
    spec = resource_object(pod.get("spec"))
    _all_names(spec)
    # Later append-only additions do not invalidate the reviewed earlier entry.
    reviewed = {
        **pod,
        "spec": {
            **spec,
            "ephemeralContainers": _entries(spec, "ephemeralContainers")[
                : len(intent.previous_entries) + 1
            ],
        },
    }
    if (
        admitted_profile(intent, reviewed) != expected_profile
        or _target_instance(pod, intent.options.target_container) != intent.target_instance
        or _inherited(pod) != intent.inherited
    ):
        raise AppError("The reviewed debug declaration, target instance or Pod context changed.")


def verify_debug_instance(
    intent: EphemeralDebugIntent, value: object, expected_profile: bytes
) -> ContainerInstance:
    verify_debug_declaration(intent, value, expected_profile)
    pod = resource_object(value)
    return _running(
        intent.options.name,
        "ephemeralContainers",
        _entries(resource_object(pod.get("status", {})), "ephemeralContainerStatuses"),
    )


def inspect_debug_instance(
    target: ResourceTarget, value: object, name: str
) -> tuple[ContainerInstance, ContainerInstance | None, bytes]:
    """Fresh explicit attachment to an existing entry grants no old write ownership."""
    pod = _pod(target, value, live=True)
    spec = resource_object(pod.get("spec"))
    _all_names(spec)
    matches = [
        entry for entry in _entries(spec, "ephemeralContainers") if entry.get("name") == _name(name)
    ]
    if len(matches) != 1:
        raise AppError("Select one existing debug declaration before attaching.")
    declaration_value = matches[0]
    selected_target = declaration_value.get("targetContainerName")
    if selected_target is not None:
        _name(selected_target)
    instance = _running(
        name,
        "ephemeralContainers",
        _entries(resource_object(pod.get("status", {})), "ephemeralContainerStatuses"),
    )
    return (
        instance,
        _target_instance(pod, selected_target),
        hashlib.sha256(_canonical(declaration_value)).digest(),
    )


def discover_ephemeral(value: object) -> None:
    payload = resource_object(value)
    if payload.get("kind") != "APIResourceList" or payload.get("groupVersion") != "v1":
        raise AppError("Core/v1 subresource discovery is malformed or unavailable.")
    entries = _entries(payload, "resources")
    matches = [entry for entry in entries if entry.get("name") == "pods/ephemeralcontainers"]
    if len(matches) != 1:
        raise AppError("The cluster does not unambiguously advertise pods/ephemeralcontainers.")
    entry = matches[0]
    verbs = entry.get("verbs")
    if (
        entry.get("namespaced") is not True
        or entry.get("kind") != "Pod"
        or not isinstance(verbs, list)
        or any(not isinstance(verb, str) for verb in verbs)
        or "patch" not in verbs
    ):
        raise AppError(
            "The cluster does not advertise the supported ephemeral-container patch API."
        )


@dataclass(frozen=True, slots=True)
class DebugSessionRow:
    name: str
    image: str
    state: str
    reason: str | None = None
    exit_code: int | None = None
    instance: ContainerInstance | None = None


@dataclass(frozen=True, slots=True)
class DebugObservation:
    rows: tuple[DebugSessionRow, ...]
    incomplete: bool


def _status_row(entry: dict[str, Any], states: list[dict[str, Any]]) -> DebugSessionRow:
    name, image = _name(entry.get("name")), resource_text(entry.get("image"))
    matches = [state for state in states if state.get("name") == name]
    if not matches:
        return DebugSessionRow(name, image, "pending")
    state = matches[0].get("state")
    if len(matches) != 1 or not isinstance(state, dict) or len(state) != 1:
        return DebugSessionRow(name, image, "unknown")
    try:
        if "running" in state:
            return DebugSessionRow(
                name, image, "running", instance=_running(name, "ephemeralContainers", matches)
            )
        if "waiting" in state:
            reason = resource_object(state["waiting"]).get("reason")
            return DebugSessionRow(
                name, image, "waiting", None if reason is None else resource_text(reason)
            )
        if "terminated" in state:
            terminated = resource_object(state["terminated"])
            code = terminated.get("exitCode")
            if type(code) is not int or not -(2**31) <= code <= 2**31 - 1:
                raise AppError("Invalid remote exit status.")
            reason = terminated.get("reason")
            return DebugSessionRow(
                name, image, "terminated", None if reason is None else resource_text(reason), code
            )
    except AppError:
        pass
    return DebugSessionRow(name, image, "unknown")


def session_rows(target: ResourceTarget, value: object) -> DebugObservation:
    pod = _pod(target, value)
    entries = _entries(resource_object(pod.get("spec")), "ephemeralContainers")
    states = _entries(resource_object(pod.get("status", {})), "ephemeralContainerStatuses")
    names = [entry.get("name") for entry in entries]
    if len(set(_name(name) for name in names)) != len(names):
        raise AppError("Existing debug declarations have ambiguous names.")
    return DebugObservation(
        tuple(_status_row(entry, states) for entry in entries[:MAX_ROWS]), len(entries) > MAX_ROWS
    )


def debug_session_row(target: ResourceTarget, value: object, name: str) -> DebugSessionRow:
    """Resolve the selected entry across the complete read, independent of display limits."""
    pod = _pod(target, value)
    spec = resource_object(pod.get("spec"))
    _all_names(spec)
    matches = [
        entry for entry in _entries(spec, "ephemeralContainers") if entry.get("name") == _name(name)
    ]
    if len(matches) != 1:
        raise AppError("The selected debug declaration is unavailable.")
    return _status_row(
        matches[0], _entries(resource_object(pod.get("status", {})), "ephemeralContainerStatuses")
    )
