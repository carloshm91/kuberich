"""Captured DELETE/create effects and narrow Job suspension decisions."""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kuberich.domain.mutations import MutationIntent, patch_intent
from kuberich.domain.resources import (
    ApiResource,
    ResourceRecord,
    api_segment,
    resource_object,
    string_list,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_BATCH = 100
MAX_OPERATION_BYTES = 1024 * 1024


class ResourceAction(Enum):
    DELETE = "Delete"
    TRIGGER = "Run now"
    SUSPEND = "Suspend"
    RESUME = "Resume"


def operation_path(resource: ApiResource, target: ResourceTarget, action: ResourceAction) -> str:
    if resource.group:
        api_segment(resource.group)
    api_segment(resource.version)
    api_segment(resource.name)
    if (
        target.group != resource.group
        or target.resource != resource.name
        or target.container is not None
        or type(resource.namespaced) is not bool
        or resource.namespaced != (target.namespace is not None)
        or "get" not in resource.verbs
        or not isinstance(action, ResourceAction)
    ):
        raise AppError("Operation requires an exact readable resource scope.")
    if action is ResourceAction.DELETE:
        if "delete" not in resource.verbs:
            raise AppError("This API does not advertise deletion.")
    elif (
        resource.group != "batch"
        or resource.version != "v1"
        or not resource.namespaced
        or resource.name not in {"jobs", "cronjobs"}
        or (action is ResourceAction.TRIGGER and resource.name != "cronjobs")
        or (action is not ResourceAction.TRIGGER and "patch" not in resource.verbs)
    ):
        raise AppError("Use a supported batch/v1 Job or CronJob for this action.")
    return resource.path(target.namespace) + "/" + api_segment(target.name)


@dataclass(frozen=True)
class DeleteOptions:
    propagation: str = "Foreground"
    grace_seconds: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.propagation, str)
            or self.propagation not in {"Foreground", "Background", "Orphan"}
            or (
                self.grace_seconds is not None
                and (
                    type(self.grace_seconds) is not int or not 0 <= self.grace_seconds <= 2147483647
                )
            )
        ):
            raise AppError(
                "Choose Foreground, Background or Orphan and a nonnegative grace period."
            )

    @property
    def summary(self) -> str:
        grace = "server default" if self.grace_seconds is None else f"{self.grace_seconds}s"
        return f"Propagation: {self.propagation}; grace: {grace}."


def snapshot_version(target: ResourceTarget, record: ResourceRecord) -> str:
    target.require_current(target.session, uid=record.uid or "")
    if (
        record.name != target.name
        or record.namespace != target.namespace
        or record.resource_version is None
        or len(record.resource_version) > 1024
    ):
        raise AppError("Operation snapshot does not match its captured identity/version.")
    return validate_argument(record.resource_version)


def operation_json(value: object) -> bytes:
    try:
        result = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Operation must contain finite UTF-8 JSON.") from None
    if len(result) > MAX_OPERATION_BYTES:
        raise AppError("Operation exceeds the 1 MiB request limit.")
    return result


@dataclass(frozen=True, repr=False)
class ResourceIntent:
    target: ResourceTarget
    resource: ApiResource
    resource_version: str
    action: ResourceAction
    body: bytes = field(repr=False)
    identity: UUID = field(default_factory=uuid4)
    created_name: str | None = None
    finalizers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        operation_path(self.resource, self.target, self.action)
        validate_argument(self.resource_version)
        if (
            self.action not in {ResourceAction.DELETE, ResourceAction.TRIGGER}
            or not isinstance(self.identity, UUID)
            or not isinstance(self.body, bytes)
            or not 1 <= len(self.body) <= MAX_OPERATION_BYTES
            or len(self.resource_version) > 1024
        ):
            raise AppError("Invalid immutable operation identity/body.")
        try:
            data = resource_object(json.loads(self.body))
            operation_json(data)
        except (ValueError, UnicodeError, RecursionError):
            raise AppError("Invalid operation JSON.") from None
        if self.action is ResourceAction.DELETE:
            allowed = {"apiVersion", "kind", "preconditions", "propagationPolicy"}
            propagation = data.get("propagationPolicy")
            if not isinstance(propagation, str):
                raise AppError("Deletion requires an explicit propagation policy.")
            options = DeleteOptions(propagation, data.get("gracePeriodSeconds"))
            expected: dict[str, Any] = {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "preconditions": {"uid": self.target.uid, "resourceVersion": self.resource_version},
                "propagationPolicy": options.propagation,
            }
            if options.grace_seconds is not None:
                allowed.add("gracePeriodSeconds")
                expected["gracePeriodSeconds"] = options.grace_seconds
            if set(data) != allowed or data != expected or self.created_name is not None:
                raise AppError(
                    "Deletion requires exact UID/version and explicit validated options."
                )
        else:
            metadata = resource_object(data.get("metadata"))
            if (
                self.created_name != manual_job_name(self.target.name, self.identity)
                or data.get("apiVersion") != "batch/v1"
                or data.get("kind") != "Job"
                or set(data) != {"apiVersion", "kind", "metadata", "spec"}
                or metadata.get("name") != self.created_name
                or metadata.get("namespace") != self.target.namespace
                or set(metadata) != {"name", "namespace", "labels", "annotations"}
                or resource_object(metadata.get("annotations")).get("kuberich.io/request")
                != str(self.identity)
            ):
                raise AppError("Job creation requires its exact one-use name and namespace.")
            resource_object(metadata["labels"])
            resource_object(data["spec"])
        if not isinstance(self.finalizers, tuple):
            raise AppError("Finalizers must be an immutable bounded snapshot.")
        string_list(list(self.finalizers))

    @property
    def method(self) -> str:
        return "DELETE" if self.action is ResourceAction.DELETE else "POST"

    @property
    def path(self) -> str:
        return (
            operation_path(self.resource, self.target, self.action)
            if self.action is ResourceAction.DELETE
            else f"/apis/batch/v1/namespaces/{self.target.namespace}/jobs"
        )

    @property
    def effects(self) -> tuple[str, ...]:
        if self.action is ResourceAction.TRIGGER:
            return (f"Create jobs/{self.created_name} from captured CronJob template",)
        data = json.loads(self.body)
        return (
            "Delete captured UID/version; "
            + DeleteOptions(data["propagationPolicy"], data.get("gracePeriodSeconds")).summary,
            "Finalizers: " + (", ".join(self.finalizers) or "none observed"),
        )


def delete_intent(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, options: DeleteOptions
) -> ResourceIntent:
    version = snapshot_version(target, record)
    metadata = resource_object(record.manifest["metadata"])
    if metadata.get("deletionTimestamp"):
        raise AppError(
            "This resource is already terminating. Inspect finalizers; do not delete again."
        )
    value: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "DeleteOptions",
        "preconditions": {"uid": target.uid, "resourceVersion": version},
        "propagationPolicy": options.propagation,
    }
    if options.grace_seconds is not None:
        value["gracePeriodSeconds"] = options.grace_seconds
    return ResourceIntent(
        target,
        resource,
        version,
        ResourceAction.DELETE,
        operation_json(value),
        finalizers=string_list(metadata.get("finalizers")),
    )


def manual_job_name(name: str, identity: UUID) -> str:
    return api_segment(name[:23].rstrip(".-") + "-manual-" + identity.hex)


def trigger_intent(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, identity: UUID
) -> ResourceIntent:
    version = snapshot_version(target, record)
    template = resource_object(resource_object(record.manifest.get("spec")).get("jobTemplate"))
    metadata = resource_object(template.get("metadata", {}))
    labels = resource_object(metadata.get("labels", {}))
    annotations = resource_object(metadata.get("annotations", {}))
    if any(not isinstance(value, str) for value in (*labels.values(), *annotations.values())):
        raise AppError("Job template labels/annotations must be text mappings.")
    name = manual_job_name(target.name, identity)
    value = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": target.namespace,
            "labels": labels,
            "annotations": {
                **annotations,
                "cronjob.kubernetes.io/instantiate": "manual",
                "kuberich.io/request": str(identity),
                "kuberich.io/source-uid": target.uid,
            },
        },
        "spec": resource_object(template.get("spec")),
    }
    return ResourceIntent(
        target, resource, version, ResourceAction.TRIGGER, operation_json(value), identity, name
    )


def suspension_intent(
    resource: ApiResource, target: ResourceTarget, record: ResourceRecord, action: ResourceAction
) -> MutationIntent:
    operation_path(resource, target, action)
    if action not in {ResourceAction.SUSPEND, ResourceAction.RESUME}:
        raise AppError("Choose suspend or resume.")
    spec = resource_object(record.manifest.get("spec"))
    old = spec.get("suspend", False)
    value = action is ResourceAction.SUSPEND
    if type(old) is not bool or old == value:
        raise AppError("Suspension is invalid or already in the requested state.")
    return patch_intent(
        resource, target, record, [{"op": "add", "path": "/spec/suspend", "value": value}]
    )
