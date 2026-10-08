"""Applicable workload actions and rollout state from actual controller snapshots."""

import copy
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from kubetrol.domain.mutations import MutationIntent, patch_intent
from kubetrol.domain.resources import ApiResource, ResourceRecord, resource_object
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError


class WorkloadAction(Enum):
    SCALE = "Scale"
    RESTART = "Restart"
    ROLLBACK = "Rollback"
    STATUS = "Rollout status"


def applicable(resource: ApiResource, action: WorkloadAction) -> None:
    families = (
        {"deployments", "replicasets", "statefulsets"}
        if action is WorkloadAction.SCALE
        else {"deployments", "statefulsets", "daemonsets"}
    )
    if resource.group != "apps" or resource.name not in families or not resource.namespaced:
        raise AppError("This action is unsupported for the selected resource.")


def replica_count(text: str) -> int:
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]{1,10}", text):
        raise AppError("Replicas must be an ASCII integer from 0 to 2147483647.")
    value = int(text)
    if value > 2147483647:
        raise AppError("Replicas exceed the Kubernetes integer limit.")
    return value


def _count(data: dict[str, Any], key: str, default: int = 0) -> int:
    value = data.get(key, default)
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise AppError("Controller returned an invalid replica/generation count.")
    return value


def require_rolling(record: ResourceRecord) -> None:
    data = record.manifest
    spec = resource_object(data.get("spec"))
    if spec.get("paused") is True:
        raise AppError("Deployment is paused. Resume it before restart or rollback.")
    strategy = resource_object(spec.get("updateStrategy", {}))
    if strategy.get("type") == "OnDelete":
        raise AppError(
            "OnDelete requires deliberate pod deletion; automatic restart/rollback is unavailable."
        )


def restart_intent(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, now: datetime
) -> MutationIntent:
    applicable(resource, WorkloadAction.RESTART)
    require_rolling(record)
    if now.tzinfo is None or now.utcoffset() is None:
        raise AppError("Restart timestamp requires an explicit timezone.")
    template = resource_object(resource_object(record.manifest.get("spec")).get("template"))
    metadata = resource_object(template.get("metadata", {}))
    annotations = resource_object(metadata.get("annotations", {}))
    stamp = now.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    changes = []
    if "metadata" not in template:
        changes.append({"op": "add", "path": "/spec/template/metadata", "value": {}})
    changes.append(
        {
            "op": "add",
            "path": "/spec/template/metadata/annotations",
            "value": {**annotations, "kubectl.kubernetes.io/restartedAt": stamp},
        }
    )
    return patch_intent(resource, target, record, changes)


def controlled_by(data: dict[str, Any], target: ResourceTarget) -> bool:
    owners = resource_object(data.get("metadata")).get("ownerReferences", [])
    if not isinstance(owners, list):
        raise AppError("Controller history has invalid ownership.")
    return any(
        resource_object(owner).get("uid") == target.uid and owner.get("controller") is True
        for owner in owners
    )


def revision_template(data: dict[str, Any], resource: ApiResource) -> tuple[int, dict[str, Any]]:
    if resource.name == "deployments":
        metadata = resource_object(data.get("metadata"))
        annotations = resource_object(metadata.get("annotations", {}))
        revision = replica_count(annotations.get("deployment.kubernetes.io/revision", ""))
        template = copy.deepcopy(resource_object(resource_object(data.get("spec")).get("template")))
        labels = resource_object(resource_object(template.get("metadata", {})).get("labels", {}))
        labels.pop("pod-template-hash", None)
    else:
        revision = _count(data, "revision")
        template = copy.deepcopy(
            resource_object(
                resource_object(resource_object(data.get("data")).get("spec")).get("template")
            )
        )
        directive = template.pop("$patch", "replace")
        if directive != "replace":
            raise AppError("Unsupported controller history patch directive.")
    if revision == 0 or not isinstance(
        resource_object(template.get("spec")).get("containers"), list
    ):
        raise AppError("Controller history has no usable positive revision/template.")
    return revision, template


@dataclass(frozen=True)
class RolloutProgress:
    state: str
    message: str
    terminal: bool


def rollout_progress(resource: ApiResource, record: ResourceRecord) -> RolloutProgress:
    applicable(resource, WorkloadAction.STATUS)
    data = record.manifest
    spec, status = resource_object(data.get("spec")), resource_object(data.get("status", {}))
    generation = _count(resource_object(data.get("metadata")), "generation", 1)
    observed = _count(status, "observedGeneration")
    if spec.get("paused") is True:
        return RolloutProgress(
            "Paused", "Deployment is paused; monitoring does not resume it.", True
        )
    if observed < generation:
        return RolloutProgress(
            "Waiting", "Controller has not observed the current generation.", False
        )
    conditions = status.get("conditions", [])
    if not isinstance(conditions, list):
        raise AppError("Controller conditions are invalid.")
    if any(
        resource_object(c).get("type") == "Progressing"
        and c.get("status") == "False"
        and c.get("reason") == "ProgressDeadlineExceeded"
        for c in conditions
    ):
        return RolloutProgress("Failed", "Deployment exceeded its progress deadline.", True)
    if resource.name == "daemonsets":
        desired = _count(status, "desiredNumberScheduled")
        updated, ready = _count(status, "updatedNumberScheduled"), _count(status, "numberAvailable")
        total = _count(status, "currentNumberScheduled")
        required = desired
    else:
        desired = _count(spec, "replicas", 1)
        updated, ready = _count(status, "updatedReplicas"), _count(status, "readyReplicas")
        total = _count(status, "replicas")
        required = desired
        if resource.name == "deployments":
            ready = _count(status, "availableReplicas")
        else:
            strategy = resource_object(spec.get("updateStrategy", {}))
            partition = _count(resource_object(strategy.get("rollingUpdate", {})), "partition")
            required = max(0, desired - partition)
    if resource_object(spec.get("updateStrategy", {})).get("type") == "OnDelete":
        return RolloutProgress(
            "Manual", "OnDelete requires pod deletion; no automatic rollout is promised.", True
        )
    complete = updated >= required and ready >= desired and total == desired
    if resource.name == "deployments":
        complete = complete and total == updated
    if resource.name == "statefulsets" and required == desired:
        complete = (
            complete
            and isinstance(status.get("currentRevision"), str)
            and status.get("currentRevision") == status.get("updateRevision")
        )
    return RolloutProgress(
        "Complete" if complete else "Progressing",
        f"Updated {updated}/{required}; available/ready {ready}/{desired}; total {total}.",
        complete,
    )
