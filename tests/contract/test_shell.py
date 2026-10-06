"""Real HTTP preflight, explicit fake-kubectl argv and private file ownership."""

import asyncio
import json
import os
import stat
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path

import pytest
from aiohttp import web

import kubetrol.services.shell as module
from kubetrol.domain.connections import ConnectionProblem
from kubetrol.domain.processes import ProcessMode
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.processes import ProcessRunner
from kubetrol.services.shell import ShellService
from tests.support.pods import pod
from tests.support.resources import reader_fixture


def service(
    reader, tmp_path, *, current=lambda: True, readonly=False, target=None, environment=None
):
    selected = target or ResourceTarget(
        SessionIdentity(reader.session.context.name, 1), "", "pods", "team", "api", "api-uid"
    )
    return ShellService(
        reader.session,
        selected,
        AccessPolicy(readonly),
        current,
        shell=("sh", "-l"),
        environment=environment or dict(os.environ),
        directory=tmp_path,
    )


@pytest.mark.asyncio
async def test_fake_kubectl_receives_literal_scope_private_snapshot_and_configured_shell(tmp_path):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return web.json_response(pod("api", uid="api-uid"))

    executable = tmp_path / "kubectl"
    executable.write_text(
        f'#!{sys.executable}\nimport json,sys,os,stat\nfrom pathlib import Path\np=Path(sys.argv[1].split("=",1)[1])\nassert stat.S_IMODE(p.stat().st_mode)==0o600\nc=json.loads(p.read_text())\nassert c["current-context"]=="kubetrol-test-one"\nassert c["users"][0]["user"]["token"]=="synthetic"\nprint(json.dumps(sys.argv[1:]))\n'
    )
    executable.chmod(0o700)
    environment = {**os.environ, "PATH": str(tmp_path), "KUBECONFIG": "ambient-wrong-config"}
    async with reader_fixture(tmp_path, handler) as reader:
        shell = service(reader, tmp_path, environment=environment)
        request = shell.capture("app")
        environment["PATH"] = "changed"
        reader.session.context.cluster.data["server"] = "https://changed.example"
        assert not request.path.exists() and "synthetic" not in repr(request)
        with pytest.raises(FrozenInstanceError):
            request.configuration = "changed"
        async with shell.stage(request) as command:
            assert stat.S_IMODE(request.path.parent.stat().st_mode) == 0o700
            async with ProcessRunner(AccessPolicy(False)) as runner:
                result = await runner.capture(
                    replace(command, mode=ProcessMode.CAPTURE), guard=shell.require_current
                )
            arguments = json.loads(result.stdout)
            assert arguments == [
                f"--kubeconfig={request.path}",
                "--context=kubetrol-test-one",
                "--namespace=team",
                "exec",
                "--stdin",
                "--tty",
                "--container=app",
                "api",
                "--",
                "sh",
                "-l",
            ]
            assert json.loads(request.path.read_text())["clusters"][0]["cluster"][
                "server"
            ].startswith("http://127.0.0.1:")
        assert not request.path.exists() and requests == ["/api/v1/namespaces/team/pods/api"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [(403, "get pods"), (404, "deleted"), (401, "credentials"), (500, "HTTP 500")],
)
async def test_preflight_failures_are_safe_and_never_create_connection_files(
    tmp_path, status, expected
):
    async def handler(request):
        return web.Response(status=status, text="opaque-private-body")

    async with reader_fixture(tmp_path, handler) as reader:
        shell = service(reader, tmp_path)
        request = shell.capture("app")
        with pytest.raises((AppError, ConnectionProblem), match=expected) as error:
            async with shell.stage(request):
                pytest.fail("must not yield")
        assert "opaque-private-body" not in str(error.value) and not request.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "readonly",
        "context",
        "stale-before",
        "stale-after-get",
        "stale-after-write",
        "foreign-target",
        "foreign-directory",
        "missing-target",
        "replacement",
        "missing-container",
        "wrong-namespace",
    ],
)
async def test_scope_and_readonly_guards_reject_without_retargeting(tmp_path, failure, monkeypatch):
    current = True

    async def handler(request):
        nonlocal current
        value = pod(
            "api",
            uid="replacement" if failure == "replacement" else "api-uid",
            namespace="other" if failure == "wrong-namespace" else "team",
        )
        if failure == "stale-after-get":
            current = False
        return web.json_response(value)

    async with reader_fixture(tmp_path, handler) as reader:
        shell = service(reader, tmp_path, current=lambda: current, readonly=failure == "readonly")
        if failure == "context":
            shell.target = replace(shell.target, session=SessionIdentity("wrong", 1))
        if failure == "stale-before":
            current = False
        if failure in {"readonly", "context", "stale-before"}:
            with pytest.raises(AppError):
                shell.capture("app")
            return
        request = shell.capture("missing" if failure == "missing-container" else "app")
        if failure == "foreign-target":
            request = replace(
                request,
                command=replace(
                    request.command, target=replace(request.command.target, name="other")
                ),
            )
        if failure == "missing-target":
            request = replace(request, command=replace(request.command, target=None))
        if failure == "foreign-directory":
            request = replace(request, path=tmp_path / "must-not-write")
        if failure == "stale-after-write":
            original = module._ConnectionFile.write

            def write(owner, configuration):
                nonlocal current
                original(owner, configuration)
                current = False

            monkeypatch.setattr(module._ConnectionFile, "write", write)
        with pytest.raises(AppError):
            async with shell.stage(request):
                pytest.fail("must not yield")
        assert not request.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exists", "write", "cleanup"])
async def test_file_failures_are_safe_and_do_not_remove_unowned_files(
    tmp_path, failure, monkeypatch
):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        shell = service(reader, tmp_path)
        request = shell.capture("app")
        if failure == "exists":
            request.path.write_text("unowned-sentinel")
        if failure == "write":

            def write(owner, configuration):
                descriptor = os.open(owner.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                owner.created = True
                os.close(descriptor)
                raise OSError("private-path-error")

            monkeypatch.setattr(module._ConnectionFile, "write", write)
        if failure == "cleanup":

            def remove(owner):
                owner.path.unlink()
                raise OSError("private-path-error")

            monkeypatch.setattr(module._ConnectionFile, "remove", remove)
        with pytest.raises(AppError, match="private kubectl connection") as error:
            async with shell.stage(request):
                assert failure == "cleanup"
        assert "private-path-error" not in str(error.value)
        if failure == "exists":
            assert request.path.read_text() == "unowned-sentinel"
        else:
            assert not request.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["write", "cleanup", "body"])
async def test_cancelled_preparation_and_cleanup_are_drained(tmp_path, phase, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = getattr(module._ConnectionFile, "write" if phase == "write" else "remove")
    if phase != "body":

        def delayed(owner, *args):
            started.set()
            assert release.wait(5)
            original(owner, *args)

        monkeypatch.setattr(
            module._ConnectionFile, "write" if phase == "write" else "remove", delayed
        )
    entered = asyncio.Event()

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        shell = service(reader, tmp_path)
        request = shell.capture("app")

        async def operation():
            async with shell.stage(request):
                entered.set()
                if phase == "body":
                    await asyncio.Event().wait()

        task = asyncio.create_task(operation())
        try:
            if phase == "body":
                await entered.wait()
            else:
                async with asyncio.timeout(5):
                    while not started.is_set():
                        await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not request.path.exists()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [date(2026, 10, 5), float("nan")])
async def test_non_json_kubeconfig_extensions_fail_safely_before_read_or_spawn(tmp_path, extension):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        reader.session.context.cluster.data["extensions"] = [
            {"name": "unused", "extension": {"recorded": extension}}
        ]
        with pytest.raises(AppError, match="cannot be delegated") as error:
            service(reader, tmp_path).capture("app")
        assert "synthetic" not in str(error.value) and not requests
        assert not list(Path(reader.session.directory.name).glob("exec-*.json"))
