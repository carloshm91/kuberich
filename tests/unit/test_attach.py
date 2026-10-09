"""Attach uses a captured running container, literal scope and safe results."""

from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.domain.attach import attach_command, attach_result, verify_attach_target
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessResult, ProcessStatus
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from tests.support.pods import pod, record


def target(**changes):
    value = ResourceTarget(
        SessionIdentity("fixture", 1), "", "pods", "team", "api", "api-uid", "app"
    )
    return replace(value, **changes)


def test_attach_scope_is_literal_captured_and_does_not_start_a_shell(tmp_path):
    selected = target(container="app; echo owned")
    environment = {"KUBECONFIG": "ambient-wrong", "PATH": "captured"}
    path = tmp_path / "private config.json"
    command = attach_command(selected, path, environment=environment, directory=tmp_path)
    environment["PATH"] = "changed"
    assert command.argv == (
        "kubectl",
        f"--kubeconfig={path}",
        "--context=fixture",
        "--namespace=team",
        "attach",
        "--stdin",
        "--tty",
        "--container=app; echo owned",
        "--detach-keys=ctrl-p,ctrl-q",
        "--pod-running-timeout=1s",
        "api",
    )
    assert command.target == selected
    assert command.mode is ProcessMode.FOREGROUND and command.purpose is ProcessPurpose.ATTACH
    assert dict(command.environment) == {"KUBECONFIG": str(path), "PATH": "captured"}


@pytest.mark.parametrize(
    "changes",
    [{"group": "apps"}, {"resource": "services"}, {"namespace": None}, {"container": None}],
)
def test_attach_requires_an_explicit_core_pod_container(tmp_path, changes):
    with pytest.raises(AppError, match="captured pod"):
        attach_command(target(**changes), tmp_path / "config", environment={}, directory=tmp_path)


def test_attach_requires_a_private_absolute_kubeconfig(tmp_path):
    with pytest.raises(AppError, match="absolute"):
        attach_command(target(), Path("relative"), environment={}, directory=tmp_path)


@pytest.mark.parametrize(
    "kind,status_field",
    [
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ],
)
def test_attach_accepts_each_existing_running_container_kind(kind, status_field):
    value = pod("api", uid="api-uid")
    value["spec"] = {kind: [{"name": "app"}]}
    value["status"] = {
        "phase": "Pending" if kind == "initContainers" else "Running",
        status_field: [{"name": "other", "state": {}}, {"name": "app", "state": {"running": {}}}],
    }
    verify_attach_target(target(), record(value))


@pytest.mark.parametrize(
    "failure",
    [
        "uid",
        "name",
        "namespace",
        "deleted",
        "succeeded",
        "failed",
        "missing-container",
        "duplicate-container",
        "missing-status",
        "absent-status",
        "non-list-status",
        "wrong-status-name",
        "duplicate-status",
        "absent-state",
        "non-object-state",
        "waiting",
        "terminated",
        "malformed-running",
    ],
)
def test_attach_refuses_replaced_ambiguous_finished_or_nonrunning_processes(failure):
    value = pod("api", uid="api-uid")
    selected = target()
    if failure == "uid":
        value["metadata"]["uid"] = "replacement"
    elif failure in {"name", "namespace"}:
        value["metadata"][failure] = "other"
    elif failure == "deleted":
        value["metadata"]["deletionTimestamp"] = "now"
    elif failure in {"succeeded", "failed"}:
        value["status"]["phase"] = failure.title()
    elif failure == "missing-container":
        selected = target(container="missing")
    elif failure == "duplicate-container":
        value["spec"]["ephemeralContainers"] = [{"name": "app"}]
    elif failure == "missing-status":
        value["status"] = None
    elif failure == "absent-status":
        value.pop("status")
    elif failure == "non-list-status":
        value["status"]["containerStatuses"] = {}
    elif failure == "wrong-status-name":
        value["status"]["containerStatuses"][0]["name"] = "other"
    elif failure == "duplicate-status":
        value["status"]["containerStatuses"] *= 2
    elif failure == "absent-state":
        value["status"]["containerStatuses"][0].pop("state")
    elif failure == "non-object-state":
        value["status"]["containerStatuses"][0]["state"] = []
    else:
        value["status"]["containerStatuses"][0]["state"] = (
            {"running": False} if failure == "malformed-running" else {failure: {}}
        )
    with pytest.raises(AppError):
        verify_attach_target(selected, record(value))


def test_attach_rejects_a_missing_receipt_uid_and_invalid_container_declarations():
    value = pod("api", uid="api-uid")
    with pytest.raises(AppError, match="stale"):
        verify_attach_target(target(), replace(record(value), uid=None))
    value["spec"]["containers"] = None
    with pytest.raises(AppError, match="unavailable"):
        verify_attach_target(target(), record(value))


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (ProcessStatus.SUCCEEDED, 0, "closed"),
        (ProcessStatus.CANCELLED, -15, "cancelled"),
        (ProcessStatus.SIGNALLED, -2, "interrupted"),
        (ProcessStatus.FAILED, 130, "interrupted"),
        (ProcessStatus.FAILED, 143, "interrupted"),
        (ProcessStatus.FAILED, 1, "pods/attach"),
        (ProcessStatus.TIMED_OUT, -9, "unexpectedly"),
        (ProcessStatus.OUTPUT_LIMIT, -9, "unexpectedly"),
        (ProcessStatus.IO_ERROR, -9, "unexpectedly"),
    ],
)
def test_attach_results_keep_exit_status_without_displaying_private_output(status, code, expected):
    result = ProcessResult(status, code, b"private-output", b"private-output")
    message = attach_result(result)
    assert expected in message and "private-output" not in message
    assert result.returncode == code
