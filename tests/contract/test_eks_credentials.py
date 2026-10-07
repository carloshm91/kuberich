"""EKS-shaped local helper contracts, not real AWS/cloud qualification."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web

from kubetrol.adapters.credentials import ExecToken
from kubetrol.config.catalog import Entry
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.errors import AppError
from kubetrol.services.sessions import SessionService
from tests.contract.test_shell import service
from tests.support.connections import catalog_fixture, fake_api, namespaces
from tests.support.eks import ROLE, TOKEN, VERSION, aws_entry, calls, control
from tests.support.pods import pod
from tests.support.resources import reader_fixture


@pytest.fixture
def aws_environment(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("AWS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AWS_PROFILE", "synthetic-inherited")
    monkeypatch.setenv("AWS_CONFIG_FILE", "synthetic-config")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "synthetic-credentials")


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [VERSION, "client.authentication.k8s.io/v1beta1"])
@pytest.mark.parametrize("mode", ["Never", "IfAvailable"])
async def test_aws_args_env_api_versions_and_expiry_refresh_are_preserved(
    tmp_path, aws_environment, version, mode, monkeypatch
):
    entry = aws_entry(tmp_path, version=version, mode=mode)
    credentials = ExecToken(Entry(entry["exec"], tmp_path), {}, 5)
    assert await credentials.token() == TOKEN
    monkeypatch.setenv("AWS_CONFIG_FILE", "changed-after-connect")
    assert await asyncio.gather(*(credentials.token() for _ in range(20))) == [TOKEN] * 20
    assert len(calls(tmp_path)) == 1
    credentials.expiration = datetime.now(UTC) - timedelta(seconds=1)
    control(tmp_path, token="k8s-aws-v1.synthetic-refreshed")
    assert (
        await asyncio.gather(*(credentials.token() for _ in range(20)))
        == ["k8s-aws-v1.synthetic-refreshed"] * 20
    )
    assert len(calls(tmp_path)) == 2
    assert all(record["args"] == entry["exec"]["args"] for record in calls(tmp_path))
    assert all(record["profile"] == "synthetic-declared" for record in calls(tmp_path))
    assert all(record["config"] == "synthetic-config" for record in calls(tmp_path))
    assert all(record["version"] == version for record in calls(tmp_path))
    assert not (tmp_path / "never-executed").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,hint",
    [
        ("missing", "AWS CLI was not found"),
        ("permission", "executable permissions"),
        ("Error loading SSO Token: private-sso-cache", "aws sso login --profile PROFILE"),
        (
            "An error occurred (AccessDenied) when calling the AssumeRole operation",
            "role assumption",
        ),
        ("Unable to locate credentials", "credentials are unavailable"),
        ("ExpiredToken", "credentials have expired"),
        ("unexpected private-failure", "AWS token helper failed"),
        ("invalid", "ExecCredential contract"),
    ],
)
async def test_aws_failures_reach_safe_session_status(tmp_path, aws_environment, failure, hint):
    entry = aws_entry(tmp_path)
    if failure == "missing":
        entry["exec"]["command"] = str(tmp_path / "missing" / "aws")
    elif failure == "permission":
        (tmp_path / "bin" / "aws").chmod(0o600)
    elif failure == "invalid":
        control(tmp_path, invalid=True)
    else:
        control(tmp_path, error=failure + "\x1b[2J private-secret-token")
    sessions = SessionService(
        catalog_fixture(tmp_path, "http://127.0.0.1:12345", entry), ConnectionRequest()
    )
    try:
        observation = await sessions.connect("kubetrol-test-one")
        assert observation.state is ConnectionState.AUTH_ERROR
        assert hint in observation.message
        assert all(value not in observation.message for value in ("private-", "\x1b", ROLE))
        assert sessions.client is None
    finally:
        await sessions.close()


@pytest.mark.asyncio
async def test_delayed_concurrent_401s_do_not_discard_a_new_revision_of_the_same_token(
    tmp_path, aws_environment
):
    entry = aws_entry(tmp_path)
    all_old_started, refreshed = asyncio.Event(), asyncio.Event()
    reject = False
    old_requests = 0

    async def handler(request):
        nonlocal old_requests
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        if reject and old_requests < 4:
            old_requests += 1
            index = old_requests
            if index == 4:
                all_old_started.set()
            await (all_old_started if index == 1 else refreshed).wait()
            return web.Response(status=401, text="private-api-error")
        if reject:
            refreshed.set()
        return namespaces("team")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, entry), ConnectionRequest())
        try:
            assert (await sessions.connect("kubetrol-test-one")).state is ConnectionState.CONNECTED
            reject = True
            async with asyncio.timeout(10):
                assert (
                    await asyncio.gather(*(sessions.client.namespaces() for _ in range(4)))
                    == [("team",)] * 4
                )
            assert len(calls(tmp_path)) == 2
            assert sessions.client.credentials.revision == 2
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_api_rejection_is_distinct_from_an_aws_login_failure(
    tmp_path, aws_environment, status
):
    entry = aws_entry(tmp_path)

    async def handler(request):
        return web.Response(status=status, text="private-api-body")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, entry), ConnectionRequest())
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is (
                ConnectionState.AUTH_ERROR if status == 401 else ConnectionState.LIMITED
            )
            assert str(status) in observation.message and "private-" not in observation.message
            assert len(calls(tmp_path)) == (2 if status == 401 else 1)
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_cancelling_an_aws_refresh_reaps_it_and_waiters_can_retry(tmp_path, aws_environment):
    entry = aws_entry(tmp_path)
    credentials = ExecToken(Entry(entry["exec"], tmp_path), {}, 5)
    assert await credentials.token() == TOKEN
    credentials.invalidate()
    control(tmp_path, sleep=True)
    task = asyncio.create_task(credentials.token())
    async with asyncio.timeout(5):
        while not (tmp_path / "pid").exists():
            await asyncio.sleep(0.005)
    waiting = asyncio.create_task(credentials.token())
    control(tmp_path)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)
    assert await waiting == TOKEN
    assert not credentials.lock.locked()


@pytest.mark.asyncio
async def test_shell_pins_aws_environment_working_directory_and_executable(
    tmp_path, aws_environment, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    entry = aws_entry(tmp_path, command="aws")

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler, user=entry) as reader:
        inherited = {
            **os.environ,
            "AWS_PROFILE": "wrong-profile",
            "AWS_NEW_SETTING": "wrong",
            "HOME": "wrong-home",
        }
        inherited["AWS_CONFIG_FILE"] = "wrong-file"
        shell = service(reader, tmp_path, environment=inherited)
        shell.directory = tmp_path / "different-launch-directory"
        request = shell.capture("app")
        environment = dict(request.command.environment)
        assert environment["AWS_PROFILE"] == "synthetic-inherited"
        assert environment["AWS_CONFIG_FILE"] == "synthetic-config"
        assert environment["HOME"] == str(tmp_path)
        assert "AWS_NEW_SETTING" not in environment
        assert request.command.directory == tmp_path
        spec = json.loads(request.configuration)["users"][0]["user"]["exec"]
        assert spec["command"] == str(tmp_path / "bin" / "aws")
        assert spec["args"] == entry["exec"]["args"] and spec["env"] == entry["exec"]["env"]
        async with shell.stage(request):
            # Exercise the exported exec entry in a separate process with its
            # delegated environment, as kubectl does. Real kubectl is also
            # qualified in the owned-cluster verifier; this remains synthetic.
            delegated = ExecToken(Entry(spec, request.command.directory), {}, 5)
            delegated.environment = environment
            assert await delegated.token() == TOKEN
        assert not request.path.exists()
        assert calls(tmp_path)[0] == calls(tmp_path)[1]
        credentials = reader.session.credentials
        await reader.session.close()
        assert credentials.cached is None
        assert reader.session.credentials is None
        with pytest.raises(AppError, match="closed"):
            reader.session.delegated_config()


def test_generic_delegation_keeps_its_explicit_process_environment(tmp_path):
    credentials = ExecToken(Entry({}, tmp_path), {}, 5)
    assert credentials.delegated_environment({"HOME": "custom", "AWS_PROFILE": "custom"}) == {
        "HOME": "custom",
        "AWS_PROFILE": "custom",
    }
