"""Owned executable helpers exercise capture, delegation, cancellation and cleanup."""

import asyncio
import json
import os
import signal
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.config.popeye import PopeyeSettings
from kuberich.domain.cluster_diagnostics import (
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticStatus,
    diagnostic_text_bytes,
)
from kuberich.domain.processes import ProcessStatus
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services import popeye as service_module
from kuberich.services.access import AccessPolicy
from kuberich.services.popeye import PopeyeService
from tests.support.resources import pod_resource, reader_fixture
from tests.unit.test_popeye_parser72 import NOW, document


def executable(tmp_path, scan="", version="print('Version: v0.22.1')"):
    path = tmp_path / "owned-popeye"
    value = document()
    value["ContextName"] = "kuberich-test-one"
    path.write_text(
        f"#!{sys.executable}\nimport os,sys,json,time,signal,stat,subprocess\nfrom pathlib import Path\n"
        "if sys.argv[1:] == ['version']:\n"
        + "".join("    " + line + "\n" for line in version.splitlines())
        + "    raise SystemExit(0)\n"
        + f"report={value!r}\n"
        + scan
        + "\nprint(json.dumps(report),flush=True)\n"
    )
    path.chmod(0o700)
    return path


@asynccontextmanager
async def owner(
    tmp_path,
    path,
    *,
    policy=None,
    current=lambda request: True,
    environment=None,
    trusted=False,
    namespace="team",
    timeout=1,
):
    async def response(request):
        return web.json_response({"kind": "Status", "status": "Success"})

    async with reader_fixture(tmp_path, response) as reader:
        policy = AccessPolicy(False) if policy is None else policy
        scope = DiagnosticScope(SessionIdentity(reader.session.context.name, 1), namespace)
        request = DiagnosticRequest(scope, 1)
        service = PopeyeService(
            reader.session,
            policy,
            PopeyeSettings(path, timeout_seconds=timeout, trusted_read_only=trusted),
            dict(os.environ) if environment is None else environment,
            tmp_path,
            current,
            discovery=Discovery((pod_resource(),)),
            now=lambda: NOW,
        )
        private_directory = Path(reader.session.directory.name)
        try:
            yield service, request, private_directory
        finally:
            await service.close()
            assert not list(private_directory.glob("plugin-*.json"))


async def wait_for_file(path):
    async with asyncio.timeout(10):
        while not path.exists():
            await asyncio.sleep(0.01)


async def require_gone(pid):
    async with asyncio.timeout(5):
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            proc = Path(f"/proc/{pid}/stat")
            if proc.exists() and proc.read_text().split()[2] == "Z":
                return  # Reaped by the system's child owner, unable to execute or hold descriptors.
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["team", None])
@pytest.mark.parametrize("code", [0, 1])
async def test_fixed_scope_vector_explicit_private_connection_and_faithful_codes(
    tmp_path, namespace, code
):
    receipt = tmp_path / "receipt.json"
    script = """
p=Path(os.environ['KUBECONFIG'])
assert stat.S_IMODE(p.stat().st_mode)==0o600
assert stat.S_IMODE(p.parent.stat().st_mode)==0o700
configuration=json.loads(p.read_text())
assert configuration['current-context']=='kuberich-test-one'
assert configuration['clusters'][0]['name']=='kuberich-session'
assert configuration['users'][0]['user']['token']=='synthetic'
Path(os.environ['RECEIPT']).write_text(json.dumps({'argv':sys.argv,'kubeconfig':str(p),'cwd':str(Path.cwd())}))
print(json.dumps(report),flush=True)
raise SystemExit(CODE)
""".replace("CODE", str(code))
    path = executable(tmp_path, script)
    environment = {**os.environ, "KUBECONFIG": "/poison/never-read", "RECEIPT": str(receipt)}
    async with owner(tmp_path, path, environment=environment, namespace=namespace) as (
        service,
        request,
        private,
    ):
        environment["KUBECONFIG"] = "/later/poison"
        result = await service.run(request, max_findings=1, max_text_bytes=8192)
        assert result.returncode == code and result.status is (
            ProcessStatus.SUCCEEDED if code == 0 else ProcessStatus.FAILED
        )
        assert (
            len(result.findings) == 1
            and result.producer_version == "0.22.1"
            and result.parser_id == "popeye-json/0.22.1"
        )
        assert result.report_time is not None and diagnostic_text_bytes(result.sources) <= 16384
        recorded = json.loads(receipt.read_text())
        assert recorded["cwd"] == str(tmp_path)
        assert recorded["argv"] == [
            str(path),
            "--kubeconfig=" + recorded["kubeconfig"],
            "--context=kuberich-test-one",
            "--all-namespaces" if namespace is None else "--namespace=team",
            "--out=json",
            "--sections=pods",
            "--lint=ok",
            "--logs=none",
            "--log-level=0",
            "--request-timeout=10s",
        ]
        assert Path(recorded["kubeconfig"]).parent == private
        assert not Path(recorded["kubeconfig"]).exists()
        assert not (tmp_path / "NEVER").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "unexecutable",
        "version",
        "bad-version",
        "version-exit",
        "version-overflow",
        "empty",
        "invalid",
        "forbidden",
        "exit",
        "signal",
        "timeout",
        "overflow",
    ],
)
async def test_real_helper_missing_versions_failures_and_deadlines_are_explicit(tmp_path, kind):
    script = {
        "empty": "raise SystemExit(0)",
        "invalid": "print('not JSON');raise SystemExit(0)",
        "forbidden": "print('Forbidden (403) token=synthetic-sensitive',file=sys.stderr);raise SystemExit(1)",
        "exit": "print(json.dumps(report));raise SystemExit(7)",
        "signal": "os.kill(os.getpid(),signal.SIGTERM)",
        "timeout": "time.sleep(20)",
        "overflow": "os.write(2,b'x'*(8*1024*1024+1));time.sleep(20)",
    }.get(kind, "")
    version = {
        "version": "print('Version: v0.22.0')",
        "bad-version": "print('not a version')",
        "version-exit": "raise SystemExit(5)",
        "version-overflow": "os.write(2,b'x'*16385);time.sleep(20)",
    }.get(kind, "print('Version: v0.22.1')")
    path = executable(tmp_path, script, version)
    if kind == "missing":
        path.unlink()
    elif kind == "unexecutable":
        path.chmod(0o600)
    expected = {
        "missing": DiagnosticStatus.UNAVAILABLE,
        "unexecutable": DiagnosticStatus.UNAVAILABLE,
        "version": DiagnosticStatus.UNSUPPORTED,
        "bad-version": DiagnosticStatus.UNSUPPORTED,
        "version-exit": DiagnosticStatus.FAILED,
        "version-overflow": DiagnosticStatus.PARTIAL,
        "empty": DiagnosticStatus.UNAVAILABLE,
        "invalid": DiagnosticStatus.FAILED,
        "forbidden": DiagnosticStatus.FORBIDDEN,
        "exit": DiagnosticStatus.FAILED,
        "signal": DiagnosticStatus.FAILED,
        "timeout": DiagnosticStatus.PARTIAL,
        "overflow": DiagnosticStatus.PARTIAL,
    }[kind]
    async with owner(tmp_path, path) as (service, request, private):
        result = await service.run(request)
        assert not result.findings and result.sources[0].status is expected
        assert "synthetic-sensitive" not in repr(result)
        assert not list(private.glob("plugin-*"))
        if kind == "exit":
            assert result.returncode == 7
        if kind == "signal":
            assert result.returncode == -signal.SIGTERM


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted", [False, True])
async def test_read_only_policy_is_checked_before_version_lookup_or_staging(tmp_path, trusted):
    marker = tmp_path / "executed"
    path = executable(tmp_path, version=f"Path({str(marker)!r}).touch();print('Version: v0.22.1')")
    async with owner(tmp_path, path, policy=AccessPolicy(True), trusted=trusted) as (
        service,
        request,
        private,
    ):
        result = await service.run(request)
        assert marker.exists() is trusted
        assert bool(result.findings) is trusted
        if not trusted:
            assert result.sources[0].status is DiagnosticStatus.FORBIDDEN
        assert not list(private.glob("plugin-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "scope"])
async def test_scope_or_policy_change_during_version_prevents_staging(tmp_path, change):
    ready, release = tmp_path / "ready", tmp_path / "release"
    path = executable(
        tmp_path,
        version=f"Path({str(ready)!r}).touch()\nwhile not Path({str(release)!r}).exists(): time.sleep(0.01)\nprint('Version: v0.22.1')",
    )
    policy, live = AccessPolicy(False), [True]
    async with owner(tmp_path, path, policy=policy, current=lambda request: live[0]) as (
        service,
        request,
        private,
    ):
        task = asyncio.create_task(service.run(request))
        await wait_for_file(ready)
        if change == "policy":
            policy.tighten()
        else:
            live[0] = False
        release.touch()
        result = await task
        assert result.sources[0].status is (
            DiagnosticStatus.FORBIDDEN if change == "policy" else DiagnosticStatus.CANCELLED
        )
        assert not list(private.glob("plugin-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["version", "scan", "leader-exits"])
async def test_close_or_cancellation_reaps_owned_children_before_private_cleanup(tmp_path, phase):
    marker = tmp_path / "pids.json"
    child = "import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    start = f"child=subprocess.Popen([sys.executable,'-c',{child!r}]);Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid]));"
    body = start + (
        "print(json.dumps(report),flush=True);raise SystemExit(0)"
        if phase == "leader-exits"
        else "time.sleep(30)"
    )
    path = executable(
        tmp_path,
        body if phase != "version" else "",
        body if phase == "version" else "print('Version: v0.22.1')",
    )
    async with owner(tmp_path, path, timeout=30) as (service, request, private):
        task = asyncio.create_task(service.run(request))
        await wait_for_file(marker)
        pids = json.loads(marker.read_text())
        if phase == "leader-exits":
            result = await task
            assert result.findings
        elif phase == "version":
            await service.close()
            assert task.cancelled()
        else:
            assert list(private.glob("plugin-*"))
            task.cancel()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        for pid in pids:
            await require_gone(pid)
        assert not list(private.glob("plugin-*"))
        await service.close()
        result = await service.run(request)
        assert result.sources[0].status is DiagnosticStatus.CANCELLED


@pytest.mark.asyncio
async def test_parser_cancellation_is_drained_before_credential_teardown(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    real_parse = service_module.parse_popeye_report
    private_path = []

    def held_parse(data, **options):
        private_path.extend(private.glob("plugin-*"))
        started.set()
        assert release.wait(10)
        assert private_path[0].exists()
        return real_parse(data, **options)

    monkeypatch.setattr(service_module, "parse_popeye_report", held_parse)
    async with owner(tmp_path, executable(tmp_path)) as (service, request, private):
        task = asyncio.create_task(service.run(request))
        async with asyncio.timeout(10):
            while not started.is_set():
                await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done() and private_path[0].exists()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not private_path[0].exists()


@pytest.mark.asyncio
async def test_concurrent_run_stale_entry_and_empty_publication_allowance(tmp_path):
    marker = tmp_path / "ready"
    path = executable(tmp_path, f"Path({str(marker)!r}).touch();time.sleep(30)")
    async with owner(tmp_path, path) as (service, request, _private):
        task = asyncio.create_task(service.run(request))
        await wait_for_file(marker)
        with pytest.raises(AppError, match="already owned"):
            await service.run(request)
        await service.close()
        assert task.cancelled()
    async with owner(tmp_path, executable(tmp_path), current=lambda request: False) as (
        service,
        request,
        _private,
    ):
        result = await service.run(request, max_source_text_bytes=0)
        assert not result.findings and not result.sources


@pytest.mark.asyncio
async def test_staging_failure_does_not_run_scan_or_retain_private_material(tmp_path, monkeypatch):
    @asynccontextmanager
    async def fail_stage(path, configuration):
        raise AppError("Synthetic private staging failure")
        yield

    monkeypatch.setattr(service_module, "stage_connection", fail_stage)
    async with owner(tmp_path, executable(tmp_path)) as (service, request, _private):
        result = await service.run(request)
        assert result.sources[0].status is DiagnosticStatus.FAILED


@pytest.mark.asyncio
async def test_combined_native_remaining_limits_flow_into_parser_and_process_notice(tmp_path):
    async with owner(tmp_path, executable(tmp_path)) as (service, request, _private):
        result = await service.run(
            request, max_findings=0, max_text_bytes=0, max_source_text_bytes=2048
        )
        assert not result.findings and any(source.omitted_findings for source in result.sources)
        assert diagnostic_text_bytes(result.sources) <= 2048


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "scope", "cancel"])
async def test_staging_await_cannot_retarget_or_outlive_credential_owner(
    tmp_path, monkeypatch, change
):
    ready, release = asyncio.Event(), asyncio.Event()
    original = service_module.stage_connection

    @asynccontextmanager
    async def held_stage(path, configuration):
        async with original(path, configuration):
            ready.set()
            await release.wait()
            yield

    monkeypatch.setattr(service_module, "stage_connection", held_stage)
    marker = tmp_path / "scan-ran"
    path = executable(tmp_path, f"Path({str(marker)!r}).touch()")
    policy, live = AccessPolicy(False), [True]
    async with owner(tmp_path, path, policy=policy, current=lambda request: live[0]) as (
        service,
        request,
        private,
    ):
        task = asyncio.create_task(service.run(request))
        await asyncio.wait_for(ready.wait(), 10)
        assert list(private.glob("plugin-*"))
        if change == "policy":
            policy.tighten()
        elif change == "scope":
            live[0] = False
        else:
            task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.sources[0].status is (
                DiagnosticStatus.FORBIDDEN if change == "policy" else DiagnosticStatus.CANCELLED
            )
        assert not marker.exists() and not list(private.glob("plugin-*"))


@pytest.mark.asyncio
async def test_close_during_actual_launch_drains_the_created_kernel_process(tmp_path, monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original = loop.subprocess_exec
    created = []

    async def held_launch(factory, *args, **kwargs):
        transport, protocol = await original(factory, *args, **kwargs)
        created.append(transport.get_pid())
        ready.set()
        await release.wait()
        return transport, protocol

    monkeypatch.setattr(loop, "subprocess_exec", held_launch)
    path = executable(tmp_path, version="time.sleep(30)")
    async with owner(tmp_path, path) as (service, request, private):
        task = asyncio.create_task(service.run(request))
        await asyncio.wait_for(ready.wait(), 10)
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0.05)
        assert not closing.done() and not task.done()
        release.set()
        await asyncio.wait_for(closing, 10)
        assert task.cancelled() and created
        for pid in created:
            await require_gone(pid)
        assert not list(private.glob("plugin-*"))
