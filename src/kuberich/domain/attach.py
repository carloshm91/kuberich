"""Captured existing-process attachment, independent of terminal widgets."""

from collections.abc import Mapping
from pathlib import Path

from kuberich.domain.processes import (
    ProcessCommand,
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kuberich.domain.resources import ResourceRecord, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError


def attach_command(
    target: ResourceTarget,
    path: Path,
    *,
    environment: Mapping[str, str],
    directory: Path,
) -> ProcessCommand:
    if (
        target.group
        or target.resource != "pods"
        or target.namespace is None
        or target.container is None
    ):
        raise AppError("Attach requires a captured pod, namespace and container.")
    if not path.is_absolute():
        raise AppError("Attach requires an explicit absolute private kubeconfig.")
    variables = {**environment, "KUBECONFIG": str(path)}
    return capture_command(
        (
            "kubectl",
            f"--kubeconfig={path}",
            f"--context={target.session.context}",
            f"--namespace={target.namespace}",
            "attach",
            "--stdin",
            "--tty",
            f"--container={target.container}",
            "--detach-keys=ctrl-p,ctrl-q",
            "--pod-running-timeout=1s",
            target.name,
        ),
        environment=variables,
        directory=directory,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.ATTACH,
        target=target,
    )


def verify_attach_target(target: ResourceTarget, record: ResourceRecord) -> None:
    target.require_current(target.session, uid=record.uid or "")
    if record.name != target.name or record.namespace != target.namespace:
        raise AppError("Attach API response does not match the captured pod.")
    if resource_object(record.manifest.get("metadata")).get("deletionTimestamp") is not None:
        raise AppError("This pod is being deleted. Select a running container to attach.")
    spec = resource_object(record.manifest.get("spec"))
    raw_status = record.manifest.get("status")
    status = resource_object({} if raw_status is None else raw_status)
    if status.get("phase") in {"Succeeded", "Failed"}:
        raise AppError("This pod has finished. Select a running container to attach.")
    selected = []
    for field, observed in (
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ):
        declarations, states = spec.get(field), status.get(observed)
        if not isinstance(declarations, list):
            continue
        for entry in declarations:
            if resource_object(entry).get("name") == target.container:
                selected.append(states)
    if len(selected) != 1:
        raise AppError("Selected container is unavailable or ambiguous in this pod.")
    states = selected[0]
    matches = (
        [
            resource_object(entry)
            for entry in states
            if resource_object(entry).get("name") == target.container
        ]
        if isinstance(states, list)
        else []
    )
    if (
        len(matches) != 1
        or not isinstance(matches[0].get("state"), dict)
        or not isinstance(matches[0]["state"].get("running"), dict)
    ):
        raise AppError("Attach requires the selected container's existing running process.")


def attach_result(result: ProcessResult) -> str:
    if result.status is ProcessStatus.SUCCEEDED:
        return "Attach closed. Container selection and the previous view are retained."
    if result.status is ProcessStatus.CANCELLED:
        return "Attach cancelled. The owned local kubectl process has been cleaned up."
    if result.status is ProcessStatus.SIGNALLED or result.returncode in {130, 143}:
        return "Attach interrupted. The existing remote process may also have been interrupted."
    if result.status is ProcessStatus.FAILED:
        return (
            f"kubectl attach failed (exit {result.returncode}). Check pods/attach permission, "
            "the existing container process and connectivity."
        )
    return "Attach ended unexpectedly. Check the container process and connectivity."
