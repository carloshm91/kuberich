"""Execute only synthetic local helpers; verify the real subprocess lifecycle."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.adapters.credentials import ExecToken
from kubetrol.config.catalog import Entry
from kubetrol.domain.connections import ConnectionProblem, ConnectionRequest, ConnectionState
from kubetrol.services.sessions import SessionService
from tests.support.connections import catalog_fixture, fake_api, namespaces

VERSION = "client.authentication.k8s.io/v1"


def helper(directory: Path, source: str, **overrides) -> ExecToken:
    script = directory / "helper.py"
    script.write_text(source)
    spec = {
        "apiVersion": VERSION,
        "interactiveMode": "Never",
        "command": sys.executable,
        "args": ["helper.py"],
        **overrides,
    }
    return ExecToken(Entry(spec, directory), {"server": "https://127.0.0.1:12345"}, 0.4)


def response(**status) -> dict:
    return {
        "apiVersion": VERSION,
        "kind": "ExecCredential",
        "status": {"token": "synthetic", **status},
    }


def printer(value: object) -> str:
    return "print(" + repr(json.dumps(value)) + ")\n"


@pytest.mark.asyncio
async def test_helper_receives_contract_and_has_session_local_cache(tmp_path: Path) -> None:
    source = """import json, os, sys
from pathlib import Path
info = json.loads(os.environ['KUBERNETES_EXEC_INFO'])
assert info['spec']['interactive'] is False
assert info['spec']['cluster']['server'] == 'https://127.0.0.1:12345'
assert os.environ['KUBETROL_TEST_VALUE'] == 'literal;$(never-executed)'
assert sys.stdin.read() == ''
assert sys.argv[1] == 'argument;$(never-executed)'
path = Path('calls')
path.write_text(path.read_text() + 'x' if path.exists() else 'x')
""" + printer(response())
    credentials = helper(
        tmp_path,
        source,
        args=["helper.py", "argument;$(never-executed)"],
        env=[{"name": "KUBETROL_TEST_VALUE", "value": "literal;$(never-executed)"}],
        provideClusterInfo=True,
    )
    assert await asyncio.gather(credentials.token(), credentials.token()) == [
        "synthetic",
        "synthetic",
    ]
    assert (tmp_path / "calls").read_text() == "x"
    credentials.invalidate()
    assert await credentials.token() == "synthetic"
    assert (tmp_path / "calls").read_text() == "xx"
    other = helper(
        tmp_path,
        source,
        args=["helper.py", "argument;$(never-executed)"],
        env=[{"name": "KUBETROL_TEST_VALUE", "value": "literal;$(never-executed)"}],
        provideClusterInfo=True,
    )
    await other.token()
    assert (tmp_path / "calls").read_text() == "xxx"


@pytest.mark.asyncio
async def test_expiration_refresh_and_beta_default_interactive_mode(tmp_path: Path) -> None:
    credentials = helper(
        tmp_path,
        printer(response(expirationTimestamp=(datetime.now(UTC) + timedelta(hours=1)).isoformat())),
    )
    assert await credentials.token() == "synthetic"
    assert credentials.expiration.tzinfo is not None
    credentials.expiration = datetime.now(UTC) - timedelta(seconds=1)
    (tmp_path / "helper.py").write_text(printer(response(token="refreshed")))
    assert await credentials.token() == "refreshed"
    beta = response()
    beta["apiVersion"] = "client.authentication.k8s.io/v1beta1"
    credentials = helper(tmp_path, printer(beta), apiVersion=beta["apiVersion"])
    del credentials.entry.data["interactiveMode"]
    assert await credentials.token() == "synthetic"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"apiVersion": "wrong", "kind": "ExecCredential"},
        {"apiVersion": VERSION, "kind": "wrong"},
        {"apiVersion": VERSION, "kind": "ExecCredential", "status": {}},
        response(token="secret\nheader"),
        response(clientCertificateData="synthetic", clientKeyData="synthetic"),
        response(expirationTimestamp="2020-01-01T00:00:00Z"),
        response(expirationTimestamp="2099-01-01T00:00:00"),
        response(expirationTimestamp="bad"),
    ],
)
async def test_invalid_helper_responses_do_not_expose_output(tmp_path: Path, value: object) -> None:
    credentials = helper(tmp_path, printer(value))
    with pytest.raises(ConnectionProblem) as error:
        await credentials.token()
    assert error.value.state is ConnectionState.AUTH_ERROR
    assert "synthetic" not in str(error.value) and "secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"apiVersion": "v1alpha1"}, "API version"),
        ({"interactiveMode": "Always"}, "terminal input"),
        ({"interactiveMode": "bad"}, "interactiveMode"),
        ({"args": "bad"}, "args"),
        ({"args": ["x"] * 257}, "args"),
        ({"env": "bad"}, "env"),
        ({"env": [{"name": "invalid=name", "value": "secret"}]}, "names"),
        ({"provideClusterInfo": "true"}, "true or false"),
        ({"command": "/definitely-missing/kubetrol-helper"}, "Cannot start"),
    ],
)
async def test_invalid_helper_contract_fails_before_launch(
    tmp_path: Path, overrides: dict, message: str
) -> None:
    credentials = helper(tmp_path, printer(response()), **overrides)
    with pytest.raises(ConnectionProblem, match=message):
        await credentials.token()


@pytest.mark.asyncio
async def test_required_mode_bad_json_and_nonzero_exit_have_owned_errors(tmp_path: Path) -> None:
    credentials = helper(tmp_path, 'print("opaque-secret-not-json")')
    with pytest.raises(ConnectionProblem, match="Invalid"):
        await credentials.token()
    del credentials.entry.data["interactiveMode"]
    with pytest.raises(ConnectionProblem, match="interactiveMode"):
        await credentials.token()
    credentials = helper(
        tmp_path, 'import sys; print("opaque-secret", file=sys.stderr); sys.exit(3)'
    )
    with pytest.raises(ConnectionProblem, match="failed") as error:
        await credentials.token()
    assert "opaque-secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel,limit", [("stdout", 1024 * 1024), ("stderr", 65536)])
async def test_helper_output_limits_drain_both_pipes_and_reap(
    tmp_path: Path, channel: str, limit: int
) -> None:
    credentials = helper(
        tmp_path, f'import sys; sys.{channel}.write("x" * {limit + 1}); sys.{channel}.flush()'
    )
    with pytest.raises(ConnectionProblem, match="size limit"):
        await credentials.token()
    assert not credentials.lock.locked()


@pytest.mark.asyncio
async def test_concurrent_stderr_and_stdout_do_not_deadlock(tmp_path: Path) -> None:
    credentials = helper(
        tmp_path,
        'import sys\nsys.stderr.write("x" * 50000)\nsys.stderr.flush()\n' + printer(response()),
    )
    assert await credentials.token() == "synthetic"


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_timeout_or_cancellation_kills_and_reaps_owned_helper(
    tmp_path: Path, cancel: bool
) -> None:
    credentials = helper(
        tmp_path,
        'import os, time\nfrom pathlib import Path\nPath("pid").write_text(str(os.getpid()))\ntime.sleep(30)',
    )
    task = asyncio.create_task(credentials.token())
    async with asyncio.timeout(2):
        while not (tmp_path / "pid").exists():
            await asyncio.sleep(0.005)
    pid = int((tmp_path / "pid").read_text())
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ConnectionProblem, match="timed out"):
            await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not credentials.lock.locked()


@pytest.mark.asyncio
async def test_relative_helper_command_resolves_against_config_directory(tmp_path: Path) -> None:
    path = tmp_path / "helper"
    path.write_text("#!" + sys.executable + "\n" + printer(response()))
    path.chmod(0o700)
    credentials = helper(tmp_path, "", command="./helper", args=[])
    assert await credentials.token() == "synthetic"


@pytest.mark.asyncio
async def test_exec_401_refresh_retries_once_and_keeps_new_token(tmp_path: Path) -> None:
    script = tmp_path / "auth.py"
    script.write_text(
        'from pathlib import Path\nimport json\np=Path("count")\nn=int(p.read_text())+1 if p.exists() else 1\np.write_text(str(n))\nprint(json.dumps({"apiVersion": "'
        + VERSION
        + '", "kind":"ExecCredential", "status":{"token":str(n)}}))'
    )
    user = {
        "exec": {
            "apiVersion": VERSION,
            "interactiveMode": "IfAvailable",
            "command": sys.executable,
            "args": ["auth.py"],
        }
    }
    seen = []

    async def handler(request):
        seen.append(request.headers["Authorization"])
        return web.Response(status=401) if len(seen) == 1 else namespaces("default")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, user), ConnectionRequest())
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is ConnectionState.CONNECTED
            assert seen == ["Bearer 1", "Bearer 2"]
            await sessions.client.namespaces()
            assert seen[-1] == "Bearer 2" and (tmp_path / "count").read_text() == "2"
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_cancellation_while_process_creation_is_pending_reaps_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = asyncio.create_subprocess_exec
    started, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    credentials = helper(tmp_path, "import time; time.sleep(30)")
    task = asyncio.create_task(credentials.token())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(processes) == 1 and processes[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)
