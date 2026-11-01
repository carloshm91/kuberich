"""Real local children, captured HTTP targets, credential files and cancellation."""

import asyncio
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.domain.plugins import PluginSelection, parse_plugin
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services import plugins as plugin_service
from kuberich.services.access import AccessPolicy
from kuberich.services.plugins import PluginManager, PluginSource
from tests.support.pods import pod
from tests.support.resources import reader_fixture


def plugin(tmp_path, script="print('ok')", **changes):
    return parse_plugin(
        "trial", {"command": sys.executable, "args": ["-c", script], **changes}, tmp_path
    )


def source(
    reader, tmp_path, *, readonly=False, current=lambda: True, target=True, environment=None
):
    from tests.support.resources import pod_resource

    resource = pod_resource()
    selected = (
        ResourceTarget(
            SessionIdentity(reader.session.context.name, 1), "", "pods", "team", "api", "api-uid"
        )
        if target
        else None
    )
    return PluginSource(
        reader.session,
        resource,
        PluginSelection(reader.session.context.name, "v1/pods", selected),
        AccessPolicy(readonly),
        current,
        dict(os.environ) if environment is None else environment,
    )


async def handler(request):
    return web.json_response(pod("api", uid="api-uid"))


@pytest.mark.asyncio
async def test_literal_argv_working_directory_private_connection_and_redacted_output(tmp_path):
    work = tmp_path / "other"
    work.mkdir()
    code = """import json,os,stat,sys
from pathlib import Path
p=Path(os.environ['KUBECONFIG'])
assert stat.S_IMODE(p.stat().st_mode)==0o600
assert stat.S_IMODE(p.parent.stat().st_mode)==0o700
c=json.loads(p.read_text())
assert c['current-context']=='kuberich-test-one'
assert c['users'][0]['user']['token']=='synthetic'
assert Path.cwd()==Path(sys.argv[1])
assert sys.argv[2]=='$(touch NEVER); [red]'
assert sys.argv[3]==str(p)
assert os.environ['PROFILE']=='plugin-profile'
print('synthetic opaque-sensitive-input api_token=other-secret \\x1b]52;c;HOSTILE\\x07')
print('stderr-owned', file=sys.stderr)
"""
    script_path = tmp_path / "inspect.py"
    script_path.write_text(code)
    command = plugin(
        tmp_path,
        args=[str(script_path), str(work), "${INPUT_VALUE}", "${KUBECONFIG}"],
        directory=str(work),
        environment={"PROFILE": "plugin-profile"},
        inputs=[{"name": "value"}],
    )
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        request = await owner.prepare(command, {"value": "$(touch NEVER); [red]"})
        assert request is not None
        assert all(not path.exists() for path, _ in request.files)
        assert "synthetic" not in repr(request) and "plugin-profile" not in repr(request)
        manager = PluginManager(owner.policy)
        with pytest.raises(AppError, match="confirmation"):
            manager.start(owner, request)
        job = manager.start(owner, request, confirmed=True)
        with pytest.raises(AppError, match="consumed"):
            manager.start(owner, request, confirmed=True)
        await job.wait()
        assert job.status == "Succeeded" and job.returncode == 0
        assert "synthetic" not in job.output and "other-secret" not in job.output
        assert (
            "stderr-owned" in job.output and "\x1b" not in job.output and "\x07" not in job.output
        )
        assert all(not path.exists() for path, _ in request.files)
        assert not (work / "NEVER").exists()
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["capture", "background"])
@pytest.mark.parametrize(
    "script,settings,status,code",
    [
        ("raise SystemExit(7)", {}, "Failed", 7),
        ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", {}, "Signalled", -15),
        ("import time;time.sleep(20)", {"timeout": 0.05}, "Timed Out", None),
        (
            "import os;os.write(1,b'x'*2048);os.write(2,b'y'*2048)",
            {"output_limit": 1024},
            "Output Limit",
            None,
        ),
    ],
)
async def test_real_exit_signal_timeout_and_combined_output_bound(
    tmp_path, mode, script, settings, status, code
):
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        request = await owner.prepare(plugin(tmp_path, script, mode=mode, **settings), {})
        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True)
        await job.wait()
        assert job.status == status
        if code is not None:
            assert job.returncode == code
        assert len(job.output) <= 65536
        assert job.runner.active_count == 0
        assert all(not path.exists() for path, _ in request.files)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trusted,dangerous,allowed", [(False, False, False), (True, True, False), (True, False, True)]
)
async def test_readonly_explicit_classification_before_any_helper_lookup(
    tmp_path, monkeypatch, trusted, dangerous, allowed
):
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path, readonly=True)
        command = plugin(tmp_path, trusted_read_only=trusted, dangerous=dangerous)
        manager = PluginManager(owner.policy)
        if not allowed:
            monkeypatch.setattr(
                plugin_service,
                "capture_delegation",
                lambda *args, **kwargs: pytest.fail("capture/lookup must not occur"),
            )
            with pytest.raises(AppError, match="Read-only"):
                await owner.prepare(command, {})
        else:
            request = await owner.prepare(command, {})
            assert request.command.trusted_read_only
            job = manager.start(owner, request, confirmed=True)
            await job.wait()
            assert job.status == "Succeeded"
        await manager.close()


@pytest.mark.asyncio
async def test_background_waiter_cancel_keeps_owner_then_context_stop_reaps_descendants(tmp_path):
    pidfile = tmp_path / "pid"
    script = (
        "import os,subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        f"pid_path=Path({str(pidfile)!r});pending=pid_path.with_suffix(f'.{{os.getpid()}}.pending');"
        "pending.write_text(str(p.pid));pending.replace(pid_path);time.sleep(30)"
    )
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        request = await owner.prepare(plugin(tmp_path, script, mode="background"), {})
        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True)
        for _ in range(500):
            if pidfile.exists():
                break
            await asyncio.sleep(0.01)
        assert pidfile.exists()
        waiter = asyncio.create_task(job.wait())
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert job.running and all(path.exists() for path, _ in request.files)
        await manager.stop_for_client(reader.session)
        assert job.status == "Cancelled" and job.runner.active_count == 0
        assert all(not path.exists() for path, _ in request.files)
        # An exited descendant can remain a zombie briefly until the platform's
        # init reaps it; it must not remain running or hold a private file.
        pid = int(pidfile.read_text())
        if sys.platform == "linux" and (os.path.exists(f"/proc/{pid}/stat")):
            assert Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        else:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["replaced", "403", "404", "stale", "missing", "cwd", "environment"]
)
async def test_refusals_never_run_a_target_replacement_or_echo_raw_errors(tmp_path, failure):
    calls = []

    async def api(request):
        calls.append(request.path)
        if failure in {"403", "404"}:
            return web.json_response({"message": "token=PRIVATE"}, status=int(failure))
        return web.json_response(pod("api", uid="replaced" if failure == "replaced" else "api-uid"))

    async with reader_fixture(tmp_path, api) as reader:
        current = [True]
        owner = source(reader, tmp_path, current=lambda: current[0])
        settings = (
            {"command": "/missing/executable"}
            if failure == "missing"
            else {"directory": "/missing/directory"}
            if failure == "cwd"
            else {}
        )
        command = plugin(tmp_path, **settings)
        if failure == "environment":
            owner.environment["INVALID=KEY"] = "PRIVATE"
            with pytest.raises(AppError, match="environment"):
                await owner.prepare(command, {})
            return
        request = await owner.prepare(command, {})
        current[0] = failure != "stale"
        manager = PluginManager(owner.policy)
        if failure == "stale":
            with pytest.raises(AppError, match="stale"):
                manager.start(owner, request, confirmed=True)
            assert not calls
        else:
            job = manager.start(owner, request, confirmed=True)
            await job.wait()
            assert job.status.startswith("Error:") and "PRIVATE" not in job.output
            assert all(not path.exists() for path, _ in request.files)
        await manager.close()


@pytest.mark.asyncio
async def test_cancel_empty_inputs_discard_forged_reviews_bounds_and_closed_owner(tmp_path):
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path, target=False)
        command = plugin(tmp_path, confirm=False, dangerous=False)
        assert await owner.prepare(command, None) is None
        requests = [await owner.prepare(command, {}) for _ in range(8)]
        with pytest.raises(AppError, match="pending"):
            await owner.prepare(command, {})
        with pytest.raises(AppError, match="unavailable"):
            owner.consume(replace(requests[0]), True)
        owner.discard(requests[0])
        owner.discard(requests[0])
        owner.discard(None)
        manager = PluginManager(owner.policy)
        jobs = [manager.start(owner, request) for request in requests[1:5]]
        with pytest.raises(AppError, match="four active"):
            manager.start(owner, requests[5])
        for job in jobs:
            await job.wait()
            assert job.status == "Succeeded"
        for _ in range(36):
            request = await owner.prepare(command, {})
            job = manager.start(owner, request)
            await job.wait()
        assert len(manager.jobs) <= 32
        with pytest.raises(AppError, match="Unknown"):
            await manager.stop(jobs[0])
        await manager.close()
        with pytest.raises(AppError, match="closed"):
            manager.start(owner, requests[5])
        with pytest.raises(AppError, match="stale"):
            await owner.prepare(command, {})


@pytest.mark.asyncio
async def test_capture_preparation_cancellation_drains_owned_worker_without_publishing_review(
    tmp_path, monkeypatch
):
    import kuberich.services.plugins as module

    entered, release = threading.Event(), threading.Event()
    original = module.capture_delegation

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "capture_delegation", delayed)
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        task = asyncio.create_task(owner.prepare(plugin(tmp_path), {}))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert owner.pending_reviews == 0 and not list(
            Path(reader.session.directory.name).glob("plugin*")
        )


@pytest.mark.asyncio
async def test_delegated_exec_preserves_helper_profile_and_relative_files_separately_from_plugin(
    tmp_path,
):
    helper = tmp_path / "credential-helper.py"
    (tmp_path / "identity").write_text("original-helper-directory")
    helper.write_text("""import json,os
from pathlib import Path
assert Path('identity').read_text()=='original-helper-directory'
assert os.environ['PROFILE']=='original-helper-profile'
info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])
print(json.dumps({'apiVersion':info['apiVersion'],'kind':'ExecCredential','status':{'token':'captured-helper-token'}}))
""")
    plugin_dir = tmp_path / "plugin-directory"
    plugin_dir.mkdir()
    inspect = tmp_path / "inspect-helper.py"
    inspect.write_text("""import json,os,subprocess
from pathlib import Path
assert Path.cwd().name=='plugin-directory'
assert os.environ['PROFILE']=='plugin-profile'
config=json.loads(Path(os.environ['KUBECONFIG']).read_text())
helper=config['users'][0]['user']['exec']
assert helper['env']==[]
assert helper['interactiveMode']=='Never'
env={**os.environ,'KUBERNETES_EXEC_INFO':json.dumps({'apiVersion':helper['apiVersion'],'kind':'ExecCredential','spec':{'interactive':False}})}
result=subprocess.run([helper['command'],*helper['args']],env=env,capture_output=True)
assert result.returncode==0, result.stderr
assert json.loads(result.stdout)['status']['token']=='captured-helper-token'
print('helper identity preserved')
""")
    user = {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1",
            "interactiveMode": "Never",
            "command": sys.executable,
            "args": [str(helper)],
            "env": [{"name": "PROFILE", "value": "original-helper-profile"}],
        }
    }
    async with reader_fixture(tmp_path, handler, user=user) as reader:
        owner = source(reader, tmp_path)
        command = plugin(
            tmp_path,
            args=[str(inspect)],
            directory=str(plugin_dir),
            environment={"PROFILE": "plugin-profile"},
        )
        request = await owner.prepare(command, {})
        assert len(request.files) == 2
        assert "original-helper-profile" not in " ".join(request.command.argv)
        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True)
        await job.wait()
        assert job.status == "Succeeded", job.output
        assert "helper identity preserved" in job.output
        assert all(not path.exists() for path, _ in request.files)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_foreground_requires_explicit_terminal_owner_and_preserves_exit(tmp_path, native):
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        request = await owner.prepare(plugin(tmp_path, mode="foreground"), {})

        async def handoff(runner, command, guard, timeout):
            guard()
            assert timeout == 300 and command.mode.name == "FOREGROUND"
            assert all(path.exists() for path, _ in request.files)
            return ProcessResult(ProcessStatus.FAILED, 7)

        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True, handoff=handoff if native else None)
        await job.wait()
        assert job.status == ("Failed" if native else "Error: AppError")
        assert job.returncode == (7 if native else None)
        assert all(not path.exists() for path, _ in request.files)
        await manager.close()


@pytest.mark.asyncio
async def test_policy_scope_descriptor_and_foreground_conflicts_are_explicit(tmp_path):
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        with pytest.raises(AppError, match="apply"):
            await owner.prepare(plugin(tmp_path, scopes=["apps/v1/deployments"]), {})
        owner.resource = None
        request = await owner.prepare(plugin(tmp_path), {})
        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True)
        await job.wait()
        assert job.status == "Error: AppError"
        other = PluginManager(AccessPolicy(True))
        request = await owner.prepare(plugin(tmp_path), {})
        with pytest.raises(AppError, match="policy"):
            other.start(owner, request, confirmed=True)
        owner.resource = reader.resource if hasattr(reader, "resource") else None
        first = await owner.prepare(plugin(tmp_path, mode="foreground"), {})
        second = await owner.prepare(plugin(tmp_path, mode="foreground"), {})
        job = manager.start(owner, first, confirmed=True)
        with pytest.raises(AppError, match="foreground"):
            manager.start(owner, second, confirmed=True)
        await manager.stop(job)
        assert job.status == "Cancelled"
        await manager.close()
        await other.close()


@pytest.mark.asyncio
async def test_live_invalidated_selection_cancels_job_and_unrelated_client_does_not(tmp_path):
    async with reader_fixture(tmp_path, handler) as reader:
        present = [True]
        owner = source(reader, tmp_path, current=lambda: present[0])
        request = await owner.prepare(
            plugin(tmp_path, "import time;time.sleep(30)", mode="background"), {}
        )
        manager = PluginManager(owner.policy)
        job = manager.start(owner, request, confirmed=True)
        for _ in range(500):
            if job.status == "Running":
                break
            await asyncio.sleep(0.001)
        assert job.status == "Running"
        await manager.stop_for_client(object())
        assert job.running
        present[0] = False
        manager.invalidate()
        await job.wait()
        assert job.status == "Cancelled"
        manager.invalidate()
        await manager.close()


@pytest.mark.asyncio
async def test_concurrent_preparations_reserve_the_bound_and_freeze_inputs_before_await(
    tmp_path, monkeypatch
):
    release = threading.Event()
    entered = threading.Event()
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        original = plugin_service.capture_delegation

        def delayed(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return original(*args, **kwargs)

        monkeypatch.setattr(plugin_service, "capture_delegation", delayed)
        command = plugin(
            tmp_path, args=["-c", "print('ok')", "${INPUT_VALUE}"], inputs=[{"name": "value"}]
        )
        values = {"value": "original-value"}
        tasks = [asyncio.create_task(owner.prepare(command, values)) for _ in range(8)]
        try:
            async with asyncio.timeout(5):
                while owner.pending_reviews != 8 or not entered.is_set():
                    await asyncio.sleep(0.001)
            values["value"] = "changed-value"
            with pytest.raises(AppError, match="pending"):
                await owner.prepare(command, values)
        finally:
            release.set()
            requests = await asyncio.gather(*tasks, return_exceptions=True)
        assert not any(isinstance(request, BaseException) for request in requests)
        assert all(request.command.argv[-1] == "original-value" for request in requests)
        assert owner.pending_reviews == 8
        owner.close()
        assert owner.pending_reviews == 0


@pytest.mark.asyncio
async def test_completed_status_is_not_published_before_output_and_private_cleanup(
    tmp_path, monkeypatch
):
    import kuberich.services.plugins as module

    entered, release = asyncio.Event(), asyncio.Event()
    original = module.file_worker

    async def delayed(operation):
        if getattr(operation, "__name__", "") == "redact":
            entered.set()
            await release.wait()
        return await original(operation)

    monkeypatch.setattr(module, "file_worker", delayed)
    async with reader_fixture(tmp_path, handler) as reader:
        owner = source(reader, tmp_path)
        reviewed = await owner.prepare(
            plugin(tmp_path, "print('complete-output')", mode="background"), {}
        )
        manager = PluginManager(owner.policy)
        job = manager.start(owner, reviewed, confirmed=True)
        try:
            async with asyncio.timeout(5):
                await entered.wait()
            assert job.status == "Running" and job.output == ""
            assert all(path.exists() for path, _ in reviewed.files)
            release.set()
            await job.wait()
            assert job.status == "Succeeded" and "complete-output" in job.output
            assert all(not path.exists() for path, _ in reviewed.files)
        finally:
            release.set()
            await manager.close()
