"""Bounded receipts for a single non-replayed DELETE or Job creation."""

from collections.abc import Callable

from kuberich.adapters.kubernetes import KubernetesSession, decode_json
from kuberich.adapters.mutations import guarded_request
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.operations import ResourceAction, ResourceIntent
from kuberich.domain.resources import ApiResource, resource_object, resource_record
from kuberich.errors import AppError


def operation_receipt(data: bytes, intent: ResourceIntent) -> MutationResult:
    value = decode_json(data)
    if intent.action is ResourceAction.TRIGGER:
        resource = ApiResource("batch", "v1", "jobs", "Job", True, frozenset({"get"}))
        record = resource_record(resource, value, intent.target.namespace)
        if (
            record.name != intent.created_name
            or record.uid is None
            or record.resource_version is None
        ):
            raise AppError("Created Job receipt does not establish its captured name/identity.")
        return MutationResult(
            MutationState.SUCCEEDED,
            f"Created jobs/{record.name} in {record.namespace}; UID: {record.uid}. No retry was made.",
        )
    if value.get("kind") == "Status":
        details = resource_object(value.get("details", {}))
        if (
            value.get("status") != "Success"
            or details.get("uid", intent.target.uid) != intent.target.uid
            or details.get("name", intent.target.name) != intent.target.name
        ):
            raise AppError("Deletion receipt does not match the captured target.")
    else:
        record = resource_record(intent.resource, value, intent.target.namespace)
        intent.target.require_current(intent.target.session, uid=record.uid or "")
        if record.name != intent.target.name:
            raise AppError("Deletion receipt names a different object.")
    return MutationResult(
        MutationState.ACCEPTED,
        "API accepted deletion of the captured UID. Completion/finalizers require observation.",
    )


async def resource_write(
    client: KubernetesSession, intent: ResourceIntent, authorize: Callable[[], None]
) -> MutationResult:
    result = await guarded_request(
        client,
        authorize,
        method=intent.method,
        path=intent.path,
        body=intent.body,
        content_type="application/json",
        accepted=(200, 202) if intent.action is ResourceAction.DELETE else (201,),
        receipt=lambda data: operation_receipt(data, intent),
    )
    if result.state is MutationState.DENIED:
        return MutationResult(result.state, "Permission denied (403). Check delete/create access.")
    if result.state is MutationState.CONFLICT and intent.action is ResourceAction.TRIGGER:
        return MutationResult(
            result.state,
            f"Job name {intent.created_name} already exists. Inspect it; no duplicate or retry was sent.",
        )
    if intent.action is ResourceAction.TRIGGER and result.state is not MutationState.SUCCEEDED:
        return MutationResult(
            result.state,
            f"Job: jobs/{intent.created_name} in {intent.target.namespace}. {result.message}",
        )
    return result
