"""Immutable reviewed Node maintenance facts; no transport or UI dependencies."""

import json
import re
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parsedate_to_datetime
from enum import StrEnum
from uuid import UUID, uuid4

from kuberich.domain.mutations import MutationIntent, patch_intent
from kuberich.domain.relationships import resource_labels, selector_matches, structured_selector
from kuberich.domain.resources import (
    ApiResource,
    ResourceRecord,
    api_segment,
    resource_object,
    resource_record,
    resource_text,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError


class MaintenanceMode(StrEnum):
    CORDON = "cordon"
    DRAIN = "drain"
    UNCORDON = "uncordon"


@dataclass(frozen=True)
class DrainOptions:
    force: bool = False
    delete_emptydir_data: bool = False
    leave_daemonsets: bool = False
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not bool
                for value in (self.force, self.delete_emptydir_data, self.leave_daemonsets)
            )
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 3600
        ):
            raise AppError(
                "Drain requires explicit boolean consents and a timeout from 1 to 3600 seconds."
            )


class NodeState(StrEnum):
    CORDONED = "Observed cordoned"
    SCHEDULABLE = "Observed schedulable"
    ABSENT = "Node absent"
    REPLACED = "Node replaced"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class NodeObservation:
    state: NodeState
    observed_at: float
    uid: str | None = None
    last_known_state: NodeState | None = None
    last_observed_at: float | None = None


class PodState(StrEnum):
    QUEUED = "Queued"
    RETRYING = "Refused; waiting to retry"
    ACCEPTED = "Accepted; absence pending"
    TERMINATING = "Terminating; absence pending"
    ABSENT = "Original UID absent"
    SKIPPED = "Retained"
    STALE = "Fresh review required"
    FAILED = "Failed"
    UNCERTAIN = "Outcome uncertain"
    NOT_SENT = "Not sent"


@dataclass(frozen=True)
class PdbReview:
    name: str
    uid: str
    min_available: str | None
    max_unavailable: str | None
    disruptions_allowed: int | None
    current_healthy: int | None
    desired_healthy: int | None
    generation: int | None
    observed_generation: int | None
    unhealthy_policy: str
    status_current: bool


@dataclass(frozen=True, repr=False)
class PodReview:
    target: ResourceTarget
    resource_version: str
    owner: str
    managed: bool
    daemonset: bool
    mirror: bool
    terminating: bool
    phase: str
    ready: bool | None
    storage: tuple[str, ...]
    emptydir: bool
    pdbs: tuple[PdbReview, ...]
    blockers: tuple[str, ...] = ()
    eviction_body: bytes = field(default=b"", repr=False)
    finalizer_count: int = 0

    @property
    def retained(self) -> bool:
        return self.daemonset or self.mirror


@dataclass(frozen=True, repr=False)
class MaintenanceReview:
    mode: MaintenanceMode
    target: ResourceTarget
    node_resource_version: str
    node_unschedulable: bool
    options: DrainOptions
    pods: tuple[PodReview, ...]
    blockers: tuple[str, ...]
    patch: MutationIntent
    identity: UUID = field(default_factory=uuid4)

    @property
    def effects(self) -> tuple[str, ...]:
        if self.mode is MaintenanceMode.DRAIN:
            return (
                "Cordon Node; evict reviewed Pod UIDs with policy/v1; never automatically uncordon",
            )
        return (f"Set Node scheduling: {self.mode.value}",)


@dataclass(frozen=True)
class PodProgress:
    uid: str
    namespace: str
    name: str
    state: PodState
    message: str = ""
    attempts: int = 0
    retry_at: float | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class MaintenanceProgress:
    pods: tuple[PodProgress, ...]
    node: NodeObservation
    running: bool


def node_state(record: ResourceRecord, target: ResourceTarget) -> bool:
    target.require_current(target.session, uid=record.uid or "")
    if record.name != target.name or record.namespace is not None or not record.resource_version:
        raise AppError("Node observation does not match the captured identity/version.")
    data = record.manifest
    if data.get("apiVersion") != "v1" or data.get("kind") != "Node":
        raise AppError("Maintenance requires an actual core/v1 Node.")
    metadata = resource_object(data.get("metadata"))
    if metadata.get("deletionTimestamp") is not None:
        raise AppError("The selected Node is being deleted.")
    value = resource_object(data.get("spec")).get("unschedulable", False)
    if type(value) is not bool:
        raise AppError("Node scheduling state is malformed.")
    return value


def node_record(resource: ApiResource, value: object) -> ResourceRecord:
    data = resource_object(value)
    if data.get("apiVersion") != "v1" or data.get("kind") != "Node":
        raise AppError("Node GET/patch receipt must identify an actual core/v1 Node.")
    return resource_record(resource, data)


def node_patch(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, mode: MaintenanceMode
) -> MutationIntent:
    node_state(record, target)
    return patch_intent(
        resource,
        target,
        record,
        [
            {
                "op": "add",
                "path": "/spec/unschedulable",
                "value": mode is not MaintenanceMode.UNCORDON,
            }
        ],
    )


def eviction_body(target: ResourceTarget, resource_version: str) -> bytes:
    if (target.group, target.resource, target.container) != (
        "",
        "pods",
        None,
    ) or target.namespace is None:
        raise AppError("Eviction requires one captured namespaced Pod.")
    api_segment(target.name)
    api_segment(target.namespace)
    resource_text(resource_version)
    if len(resource_version) > 1024 or len(target.uid) > 1024:
        raise AppError("Eviction identity/version is excessive.")
    return json.dumps(
        {
            "apiVersion": "policy/v1",
            "kind": "Eviction",
            "metadata": {"name": target.name, "namespace": target.namespace},
            "deleteOptions": {
                "preconditions": {"uid": target.uid, "resourceVersion": resource_version}
            },
        },
        separators=(",", ":"),
    ).encode()


def pod_facts(
    record: ResourceRecord, node: ResourceTarget
) -> tuple[bool, bool, str, bool | None, tuple[str, ...], bool]:
    data = record.manifest
    metadata, spec = resource_object(data.get("metadata")), resource_object(data.get("spec"))
    if (
        spec.get("nodeName") != node.name
        or not record.uid
        or not record.resource_version
        or record.namespace is None
    ):
        raise AppError("Pod inventory contains an incomplete identity or wrong Node membership.")
    resource_labels(record)
    annotations = resource_object(metadata.get("annotations", {}))
    if any(not isinstance(value, str) for value in annotations.values()):
        raise AppError("Pod annotations are malformed.")
    mirror = "kubernetes.io/config.mirror" in annotations
    terminating = metadata.get("deletionTimestamp") is not None
    if terminating:
        resource_text(metadata["deletionTimestamp"])
    finalizers = metadata.get("finalizers", [])
    if not isinstance(finalizers, list) or len(finalizers) > 128:
        raise AppError("Pod finalizers are malformed or excessive.")
    for finalizer in finalizers:
        resource_text(finalizer)
    status = resource_object(data.get("status", {}))
    phase = status.get("phase", "Unknown")
    if phase not in ("Pending", "Running", "Succeeded", "Failed", "Unknown"):
        raise AppError("Pod phase is malformed.")
    conditions = status.get("conditions", [])
    if not isinstance(conditions, list) or len(conditions) > 128:
        raise AppError("Pod readiness is malformed.")
    ready = None
    for condition in conditions:
        condition = resource_object(condition)
        if condition.get("type") == "Ready":
            if condition.get("status") not in ("True", "False", "Unknown"):
                raise AppError("Pod readiness is malformed.")
            ready = condition["status"] == "True"
    volumes = spec.get("volumes", [])
    if not isinstance(volumes, list) or len(volumes) > 128:
        raise AppError("Pod volumes are malformed or excessive.")
    storage = []
    emptydir = False
    for raw in volumes:
        volume = resource_object(raw)
        name = resource_text(volume.get("name"))
        for kind in ("emptyDir", "hostPath", "persistentVolumeClaim", "ephemeral", "csi"):
            if kind in volume:
                declaration = resource_object(volume[kind])
                if kind == "emptyDir" and declaration.get("medium", "") not in ("", "Memory"):
                    raise AppError("emptyDir medium is malformed.")
                if kind == "hostPath":
                    resource_text(declaration.get("path"))
                if kind == "persistentVolumeClaim":
                    api_segment(declaration.get("claimName"))
                    if type(declaration.get("readOnly", False)) is not bool:
                        raise AppError("PVC read-only declaration is malformed.")
                emptydir |= kind == "emptyDir"
                storage.append(f"{name}: {kind}; portability unknown")
    return mirror, terminating, phase, ready, tuple(storage), emptydir


def consent_blockers(pod: PodReview, options: DrainOptions) -> tuple[str, ...]:
    blockers = list(pod.blockers)
    if pod.daemonset and not options.leave_daemonsets:
        blockers.append("Explicitly acknowledge leaving DaemonSet Pods running.")
    if not pod.retained:
        if not pod.managed and not options.force:
            blockers.append("Unmanaged/orphaned Pod requires independent force consent.")
        if pod.emptydir and not options.delete_emptydir_data:
            blockers.append("emptyDir data loss requires independent delete-emptyDir-data consent.")
    return tuple(blockers)


def pvc_claims(record: ResourceRecord) -> tuple[tuple[str, str], ...]:
    """Only declared volume/claim names; never retain paths or source contents."""
    volumes = resource_object(record.manifest.get("spec")).get("volumes", [])
    if not isinstance(volumes, list) or len(volumes) > 128:
        raise AppError("Pod volumes are malformed or excessive.")
    result = []
    for value in volumes:
        volume = resource_object(value)
        if "persistentVolumeClaim" in volume:
            claim = resource_object(volume["persistentVolumeClaim"])
            result.append((api_segment(volume.get("name")), api_segment(claim.get("claimName"))))
    return tuple(result)


def bound_volume(claim: ResourceRecord) -> str | None:
    if not claim.uid or not claim.resource_version:
        raise AppError("PVC metadata identity is incomplete.")
    name = resource_object(claim.manifest.get("spec")).get("volumeName")
    return None if name in (None, "") else api_segment(name)


def volume_locality(claim: ResourceRecord, volume: ResourceRecord) -> str:
    if not volume.uid or not volume.resource_version:
        raise AppError("PV metadata identity is incomplete.")
    spec = resource_object(volume.manifest.get("spec"))
    ref = resource_object(spec.get("claimRef", {}))
    if (ref.get("uid"), ref.get("namespace"), ref.get("name")) != (
        claim.uid,
        claim.namespace,
        claim.name,
    ):
        return "PVC/PV binding is unverified; portability unknown"
    facts = ["PVC/PV binding UID verified; backend portability unknown"]
    for key, detail in (
        ("local", "local PV; data remains local"),
        ("hostPath", "hostPath PV; data may remain on its host"),
        ("nodeAffinity", "PV Node affinity constrains placement"),
    ):
        if key in spec:
            resource_object(spec[key])
            facts.append(detail)
    return "; ".join(facts)


def _integer(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise AppError("PDB numeric evidence is malformed.")
    return value


def _intstr(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"(?:100|[0-9]{1,2})%", value):
        return value
    raise AppError("PDB availability constraint is malformed.")


def matching_pdb(record: ResourceRecord, pod: ResourceRecord) -> PdbReview | None:
    data = record.manifest
    spec = resource_object(data.get("spec"))
    if spec.get("minAvailable") is not None and spec.get("maxUnavailable") is not None:
        raise AppError("PDB minAvailable and maxUnavailable cannot both be set.")
    selector = spec.get("selector")
    if selector is None:
        return None
    parsed = structured_selector(selector)
    if record.namespace != pod.namespace or not selector_matches(
        parsed, dict(resource_labels(pod))
    ):
        return None
    if not record.uid:
        raise AppError("PDB identity is missing.")
    metadata = resource_object(data.get("metadata"))
    status = resource_object(data.get("status", {}))
    generation, observed = (
        _integer(metadata.get("generation")),
        _integer(status.get("observedGeneration")),
    )
    allowed, healthy, desired = (
        _integer(status.get(key))
        for key in ("disruptionsAllowed", "currentHealthy", "desiredHealthy")
    )
    policy = spec.get("unhealthyPodEvictionPolicy", "IfHealthyBudget")
    if policy not in ("IfHealthyBudget", "AlwaysAllow"):
        raise AppError("PDB unhealthy-Pod policy is malformed.")
    return PdbReview(
        record.name,
        record.uid,
        _intstr(spec.get("minAvailable")),
        _intstr(spec.get("maxUnavailable")),
        allowed,
        healthy,
        desired,
        generation,
        observed,
        policy,
        generation is not None
        and observed is not None
        and observed >= generation
        and all(value is not None for value in (allowed, healthy, desired)),
    )


def matching_pdbs(
    records: tuple[ResourceRecord, ...], pod: ResourceRecord
) -> tuple[PdbReview, ...]:
    return tuple(match for record in records if (match := matching_pdb(record, pod)) is not None)


def retry_delay(header: str | None, status_seconds: object, now: float) -> float:
    """Honor both valid hints, including HTTP dates; never retry a valid hint early."""
    hints: list[float] = []
    if header is not None:
        if re.fullmatch(r"[0-9]+", header) and len(header) <= 1024:
            hints.append(float(min(int(header), 10**12)))
        else:
            try:
                date = parsedate_to_datetime(header)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                hints.append(max(0.0, date.timestamp() - now))
            except (ValueError, TypeError, OverflowError):
                pass
    if type(status_seconds) is int and status_seconds >= 0:
        hints.append(float(min(status_seconds, 10**12)))
    return max(1.0, max(hints)) if hints else 5.0


def eviction_receipt(data: object, http_status: int = 200) -> bool:
    status = resource_object(data)
    code = status.get("code", http_status)
    return (
        http_status in (200, 201)
        and status.get("apiVersion") == "v1"
        and status.get("kind") == "Status"
        and status.get("status") == "Success"
        and type(code) is int
        and code == http_status
    )
