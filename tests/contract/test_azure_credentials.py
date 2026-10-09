"""Native Azure-shaped contracts; actual tenant certification remains opt-in."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp import web

from kuberich.adapters.credentials import ExecToken
from kuberich.config.catalog import Entry
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest, ConnectionState
from kuberich.services.sessions import SessionService
from tests.contract.test_shell import service
from tests.support.azure import TOKEN, VERSION, azure_calls, azure_control, azure_entry
from tests.support.connections import catalog_fixture, fake_api, namespaces
from tests.support.pods import pod
from tests.support.resources import reader_fixture


@pytest.fixture(autouse=True)
def azure_environment(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if (
            name.startswith(("AZURE_", "AAD_", "ARM_", "AZURESUBSCRIPTION_"))
            or name == "KUBECACHEDIR"
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AZURE_CONFIG_DIR", "synthetic-cli-cache")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "login", ["azurecli", "devicecode", "spn", "spn-certificate", "workloadidentity"]
)
@pytest.mark.parametrize("version", [VERSION, "client.authentication.k8s.io/v1beta1"])
async def test_modes_keep_native_args_identity_and_single_concurrent_refresh(
    tmp_path, monkeypatch, login, version
):
    entry = azure_entry(
        tmp_path, login="spn" if login == "spn-certificate" else login, version=version
    )
    spec = entry["exec"]
    if login == "spn":
        spec["args"] += ["--client-secret", "synthetic-secret;$(never-executed)"]
    elif login == "spn-certificate":
        spec["args"] += [
            "--client-certificate",
            "synthetic.pfx",
            "--client-certificate-password",
            "synthetic-password",
        ]
    elif login == "workloadidentity":
        spec["env"] += [
            {"name": name, "value": value}
            for name, value in {
                "AZURE_CLIENT_ID": "synthetic-client",
                "AZURE_FEDERATED_TOKEN_FILE": "synthetic-jwt",
                "AZURE_AUTHORITY_HOST": "https://login.example.invalid/",
            }.items()
        ]
    credentials = ExecToken(Entry(spec, tmp_path), {}, 5)
    assert await credentials.token() == TOKEN
    monkeypatch.setenv("AZURE_CONFIG_DIR", "changed-cache")
    assert await asyncio.gather(*(credentials.token() for _ in range(12))) == [TOKEN] * 12
    assert len(azure_calls(tmp_path)) == 1
    credentials.expiration = datetime.now(UTC) - timedelta(seconds=1)
    azure_control(tmp_path, token="synthetic-refreshed")
    assert (
        await asyncio.gather(*(credentials.token() for _ in range(12)))
        == ["synthetic-refreshed"] * 12
    )
    records = azure_calls(tmp_path)
    assert len(records) == 2
    assert all(value["args"] == spec["args"] and value["version"] == version for value in records)
    assert all(
        value["environment"]["AZURE_CONFIG_DIR"] == "synthetic-cli-cache" for value in records
    )
    assert all(
        value["environment"]["AZURE_TENANT_ID"] == "declared-synthetic-tenant" for value in records
    )
    assert all(not value["interactive"] and not value["stdin_tty"] for value in records)
    if login == "workloadidentity":
        assert records[0]["environment"]["AZURE_FEDERATED_TOKEN_FILE"] == "synthetic-jwt"
    assert not (tmp_path / "never-executed").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["Never", "IfAvailable", "Always"])
async def test_explicit_login_encodes_stdin_contract_and_caches_only_valid_output(tmp_path, mode):
    credentials = ExecToken(Entry(azure_entry(tmp_path, mode=mode)["exec"], tmp_path), {}, 5)
    command = credentials.invocation(interactive=True)
    info = json.loads(dict(command.environment)["KUBERNETES_EXEC_INFO"])
    assert command.terminal_input is (mode != "Never")
    assert info["spec"]["interactive"] is command.terminal_input
    assert (
        credentials.accept(
            json.dumps(
                {"kind": "ExecCredential", "apiVersion": VERSION, "status": {"token": TOKEN}}
            ).encode(),
            command,
        )
        == TOKEN
    )
    assert await credentials.token() == TOKEN and not (tmp_path / "azure-calls").exists()
    with pytest.raises(ConnectionProblem, match="contract"):
        credentials.accept(b"private-invalid-token", command)
    assert credentials.revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["flag", "environment", "always"])
async def test_browser_and_required_input_refuse_automatic_launch(tmp_path, setting):
    entry = azure_entry(
        tmp_path,
        login="interactive" if setting == "flag" else "azurecli",
        mode="Always" if setting == "always" else "Never",
    )
    if setting == "environment":
        entry["exec"]["env"].append({"name": "AAD_LOGIN_METHOD", "value": "interactive"})
    credentials = ExecToken(Entry(entry["exec"], tmp_path), {}, 5)
    with pytest.raises(ConnectionProblem, match=":login"):
        await credentials.token()
    assert not (tmp_path / "azure-calls").exists()


@pytest.mark.asyncio
async def test_hidden_device_prompt_is_detected_immediately_and_owned_process_reaped(tmp_path):
    credentials = ExecToken(
        Entry(azure_entry(tmp_path, login="devicecode")["exec"], tmp_path), {}, 10
    )
    azure_control(tmp_path, prompt=True)
    async with asyncio.timeout(3):
        with pytest.raises(ConnectionProblem, match=":login") as error:
            await credentials.token()
    assert "SYNTHETIC-ONLY" not in str(error.value)
    assert credentials.cached is None and not credentials.lock.locked()
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "azure-pid").read_text()), 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,hint",
    [
        ("missing", "kubelogin was not found"),
        ("permission", "permissions"),
        ("AADSTS90002", "tenant configuration"),
        ("AADSTS7000222", "service-principal"),
        ("AADSTS70021", "workload identity"),
        ("Please run az login", "login is unavailable"),
        ("Azure CLI not found", "CLI was not found"),
        ("unknown private-failure", "kubelogin failed"),
        ("invalid", "ExecCredential contract"),
    ],
)
async def test_provider_failures_have_safe_distinct_session_status(tmp_path, failure, hint):
    entry = azure_entry(tmp_path)
    if failure == "missing":
        entry["exec"]["command"] = str(tmp_path / "missing" / "kubelogin")
    elif failure == "permission":
        (tmp_path / "bin" / "kubelogin").chmod(0o600)
    else:
        azure_control(
            tmp_path,
            **(
                {"invalid": True}
                if failure == "invalid"
                else {"error": failure + "\x1b[2J private-secret-token"}
            ),
        )
    sessions = SessionService(
        catalog_fixture(tmp_path, "http://127.0.0.1:1", entry), ConnectionRequest()
    )
    try:
        observation = await sessions.connect("kuberich-test-one")
        assert observation.state is ConnectionState.AUTH_ERROR and hint in observation.message
        assert all(value not in observation.message for value in ("private-", "\x1b", TOKEN))
        assert sessions.client is None
    finally:
        await sessions.close()


@pytest.mark.asyncio
async def test_large_group_jwt_reaches_actual_http_request_without_truncation(tmp_path):
    token = "synthetic." + "x" * 16384 + ".signature"
    entry = azure_entry(tmp_path)
    azure_control(tmp_path, token=token)

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer " + token
        return namespaces("team")

    async with fake_api(handler, max_field_size=65536 + 64) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, entry), ConnectionRequest())
        try:
            assert (await sessions.connect("kuberich-test-one")).state is ConnectionState.CONNECTED
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_api_credentials_rejection_and_rbac_are_not_provider_failures(tmp_path, status):
    entry = azure_entry(tmp_path)

    async def handler(request):
        return web.Response(status=status, text="private-api-body")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, entry), ConnectionRequest())
        try:
            observation = await sessions.connect("kuberich-test-one")
            assert observation.state is (
                ConnectionState.AUTH_ERROR if status == 401 else ConnectionState.LIMITED
            )
            assert str(status) in observation.message and "private-" not in observation.message
            assert len(azure_calls(tmp_path)) == (2 if status == 401 else 1)
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_api_and_delegated_helper_use_captured_azure_environment_and_path(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("KUBECACHEDIR", "synthetic-cache")
    entry = azure_entry(tmp_path, command="kubelogin")

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler, user=entry) as reader:
        inherited = {
            **os.environ,
            "AZURE_CONFIG_DIR": "wrong",
            "AAD_LOGIN_METHOD": "wrong",
            "ARM_CLIENT_ID": "wrong",
            "AZURESUBSCRIPTION_CLIENT_ID": "wrong",
            "HOME": "wrong",
            "PATH": "/wrong",
            "KUBECACHEDIR": "wrong",
            "KEEP_VALUE": "unchanged",
        }
        shell = service(reader, tmp_path, environment=inherited)
        request = shell.capture("app")
        environment = dict(request.command.environment)
        assert environment["AZURE_CONFIG_DIR"] == "synthetic-cli-cache" and environment[
            "HOME"
        ] == str(tmp_path)
        assert (
            environment["PATH"] == os.environ["PATH"]
            and environment["KUBECACHEDIR"] == "synthetic-cache"
        )
        assert all(
            name not in environment
            for name in ("AAD_LOGIN_METHOD", "ARM_CLIENT_ID", "AZURESUBSCRIPTION_CLIENT_ID")
        )
        assert "KEEP_VALUE" not in environment and request.command.directory == tmp_path
        spec = json.loads(request.configuration)["users"][0]["user"]["exec"]
        assert spec["command"] == str(tmp_path / "bin" / "kubelogin")
        assert spec["args"] == entry["exec"]["args"] and spec["env"] == entry["exec"]["env"]
        async with shell.stage(request):
            delegated = ExecToken(Entry(spec, request.command.directory), {}, 5)
            delegated.environment = environment
            assert await delegated.token() == TOKEN
        assert not request.path.exists() and azure_calls(tmp_path)[0] == azure_calls(tmp_path)[1]


@pytest.mark.asyncio
async def test_cancelling_helper_reaps_process_and_next_attempt_can_connect(tmp_path):
    credentials = ExecToken(Entry(azure_entry(tmp_path)["exec"], tmp_path), {}, 5)
    azure_control(tmp_path, sleep=True)
    task = asyncio.create_task(credentials.token())
    async with asyncio.timeout(3):
        while not (tmp_path / "azure-pid").exists():
            await asyncio.sleep(0.005)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "azure-pid").read_text()), 0)
    azure_control(tmp_path)
    assert await credentials.token() == TOKEN


@pytest.mark.asyncio
async def test_explicit_login_refuses_static_credentials_and_allows_declared_generic_helpers(
    tmp_path,
):
    async def authenticate(credentials):
        return credentials.accept(b"", credentials.invocation(interactive=True))

    sessions = SessionService(catalog_fixture(tmp_path, "http://127.0.0.1:1"), ConnectionRequest())
    try:
        assert (
            await sessions.connect("kuberich-test-one", authenticate=authenticate)
        ).state is ConnectionState.AUTH_ERROR
        assert "no exec helper" in sessions.observation.message
    finally:
        await sessions.close()
    credentials = ExecToken(
        Entry({"apiVersion": VERSION, "interactiveMode": "Never", "command": "other"}, tmp_path),
        {},
        5,
    )
    command = credentials.invocation(interactive=True)
    assert command.terminal_input is False
    assert (
        json.loads(dict(command.environment)["KUBERNETES_EXEC_INFO"])["spec"]["interactive"]
        is False
    )


@pytest.mark.asyncio
async def test_exec_maximum_argument_count_is_preserved_by_invocation_capture(tmp_path):
    entry = azure_entry(tmp_path)
    entry["exec"]["args"] += ["literal"] * (256 - len(entry["exec"]["args"]))
    credentials = ExecToken(Entry(entry["exec"], tmp_path), {}, 5)
    assert await credentials.token() == TOKEN
    assert azure_calls(tmp_path)[0]["args"] == entry["exec"]["args"]
