"""Real selected-client GET, private attach staging and a literal owned executable."""

import json
import os
import stat
import sys
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.attach import AttachService
from kuberich.services.processes import ProcessRunner
from tests.support.pods import pod
from tests.support.resources import reader_fixture


def service(reader, directory, *, current=lambda: True, readonly=False, environment=None):
    return AttachService(
        reader.session,
        ResourceTarget(
            SessionIdentity(reader.session.context.name, 1), "", "pods", "team", "api", "api-uid"
        ),
        AccessPolicy(readonly),
        current,
        environment=environment or dict(os.environ),
        directory=directory,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,observed",
    [
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ],
)
async def test_attach_stages_exact_identity_and_executes_a_literal_container_without_shell(
    tmp_path, kind, observed
):
    requests = []

    async def handler(request):
        requests.append(request.path)
        value = pod("api", uid="api-uid")
        value["spec"] = {kind: [{"name": "app"}]}
        value["status"] = {
            "phase": "Running",
            observed: [{"name": "app", "state": {"running": {}}}],
        }
        return web.json_response(value)

    executable = tmp_path / "kubectl"
    executable.write_text(
        f"#!{sys.executable}\nimport json,sys,stat\nfrom pathlib import Path\n"
        'p=Path(sys.argv[1].split("=",1)[1])\nassert stat.S_IMODE(p.stat().st_mode)==0o600\n'
        'c=json.loads(p.read_text())\nassert c["current-context"]=="kuberich-test-one"\n'
        'assert c["users"][0]["user"]["token"]=="synthetic"\nprint(json.dumps(sys.argv[1:]))\n'
    )
    executable.chmod(0o700)
    environment = {**os.environ, "PATH": str(tmp_path), "KUBECONFIG": "ambient-wrong"}
    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path, environment=environment)
        request = owner.capture("app")
        environment["PATH"] = "changed"
        assert not request.path.exists() and "synthetic" not in repr(request)
        async with owner.stage(request) as command:
            assert stat.S_IMODE(request.path.stat().st_mode) == 0o600
            async with ProcessRunner(AccessPolicy(False)) as runner:
                result = await runner.capture(
                    replace(command, mode=ProcessMode.CAPTURE), guard=owner.require_current
                )
            assert result.status is ProcessStatus.SUCCEEDED
            assert json.loads(result.stdout) == [
                f"--kubeconfig={request.path}",
                "--context=kuberich-test-one",
                "--namespace=team",
                "attach",
                "--stdin",
                "--tty",
                "--container=app",
                "--detach-keys=ctrl-p,ctrl-q",
                "--pod-running-timeout=1s",
                "api",
            ]
        assert not request.path.exists() and requests == ["/api/v1/namespaces/team/pods/api"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [(403, "pods/attach"), (404, "unavailable"), (401, "credentials"), (500, "HTTP 500")],
)
async def test_attach_get_failure_keeps_private_output_and_creates_no_connection_file(
    tmp_path, status, expected
):
    async def handler(request):
        return web.Response(status=status, text="private-response-body")

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path)
        request = owner.capture("app")
        with pytest.raises((AppError, ConnectionProblem), match=expected) as error:
            async with owner.stage(request):
                pytest.fail("must not yield")
        assert "private-response-body" not in str(error.value) and not request.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "readonly",
        "stale-before",
        "context",
        "stale-after-get",
        "replacement",
        "container",
        "foreign-target",
        "foreign-purpose",
        "foreign-directory",
        "missing-target",
    ],
)
async def test_attach_capture_and_staging_refuse_retargeting_and_readonly(tmp_path, failure):
    current = True
    requests = []

    async def handler(request):
        nonlocal current
        requests.append(request.path)
        if failure == "stale-after-get":
            current = False
        return web.json_response(
            pod("api", uid="replacement" if failure == "replacement" else "api-uid")
        )

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path, current=lambda: current, readonly=failure == "readonly")
        if failure == "stale-before":
            current = False
        if failure == "context":
            owner.target = replace(owner.target, session=SessionIdentity("other", 1))
        if failure in {"readonly", "stale-before", "context"}:
            with pytest.raises(AppError):
                owner.capture("app")
            assert not requests
            return
        request = owner.capture("missing" if failure == "container" else "app")
        if failure == "foreign-target":
            request = replace(
                request,
                command=replace(
                    request.command, target=replace(request.command.target, name="other")
                ),
            )
        if failure == "foreign-purpose":
            request = replace(
                request, command=replace(request.command, purpose=ProcessPurpose.EXEC)
            )
        if failure == "foreign-directory":
            request = replace(request, path=tmp_path / "foreign")
        if failure == "missing-target":
            request = replace(request, command=replace(request.command, target=None))
        with pytest.raises(AppError):
            async with owner.stage(request):
                pytest.fail("must not yield")
        assert not request.path.exists()
        if failure.startswith("foreign") or failure == "missing-target":
            assert not requests


@pytest.mark.asyncio
async def test_attach_never_removes_or_overwrites_a_preexisting_connection_path(tmp_path):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path)
        request = owner.capture("app")
        request.path.write_text("preexisting-owned-sentinel")
        with pytest.raises(AppError, match="private kubectl connection"):
            async with owner.stage(request):
                pytest.fail("must not yield")
        assert request.path.read_text() == "preexisting-owned-sentinel"
