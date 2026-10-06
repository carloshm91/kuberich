"""Faithful shell return messages without retaining raw kubectl output."""

from kubetrol.domain.logs import log_containers
from kubetrol.domain.processes import ProcessResult, ProcessStatus
from kubetrol.domain.resources import ResourceRecord, resource_object
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError


def verify_shell_target(target: ResourceTarget, record: ResourceRecord) -> None:
    target.require_current(target.session, uid=record.uid or "")
    if record.name != target.name or record.namespace != target.namespace:
        raise AppError("Shell API response does not match the captured pod.")
    if target.container not in log_containers(record.manifest):
        raise AppError("Selected regular/init container is unavailable in this pod.")
    if resource_object(record.manifest.get("metadata")).get("deletionTimestamp") is not None:
        raise AppError("This pod is being deleted. Select a running pod for its shell.")
    status = record.manifest.get("status")
    if resource_object({} if status is None else status).get("phase") in {"Succeeded", "Failed"}:
        raise AppError("This pod has finished. Select a running pod for its shell.")


def shell_result(result: ProcessResult) -> str:
    if result.status is ProcessStatus.SUCCEEDED:
        return "Shell closed. The selected container and view are retained."
    if result.status is ProcessStatus.CANCELLED:
        return "Shell cancelled. The owned kubectl process has been cleaned up."
    if result.status is ProcessStatus.SIGNALLED or result.returncode in {130, 143}:
        return "Shell interrupted. Press s to open the selected container again."
    if result.status is ProcessStatus.FAILED:
        if result.returncode in {126, 127}:
            return "Shell executable unavailable in this image. Change the shell argument list in preferences."
        return (
            f"kubectl exec failed (exit {result.returncode}). Check pods/exec permission, "
            "container state and the configured shell; this image may have no shell."
        )
    return "Shell ended unexpectedly. Check connectivity and try the selected container again."
