"""Real HTTP/TLS requests qualify session isolation, status and cleanup."""

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from kubernetes_asyncio.client import Configuration

from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.errors import AppError
from kubetrol.services.sessions import SessionService
from tests.support.connections import catalog_fixture, certificate, fake_api, namespaces


@pytest.mark.asyncio
async def test_context_and_scope_changes_close_old_clients_without_changing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    async def handler(request):
        calls.append(request.headers.get("Authorization"))
        return namespaces("team", "default")

    def reject_default(*args):
        pytest.fail("Global SDK configuration changed")

    monkeypatch.setattr(Configuration, "set_default", reject_default)
    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url)
        original = (tmp_path / "fixture-config").read_bytes()
        sessions = SessionService(catalog, ConnectionRequest())
        try:
            first = await sessions.connect("kubetrol-test-one")
            assert first.state is ConnectionState.CONNECTED and first.namespace == "team"
            assert first.namespaces == ("default", "team") and first.insecure
            assert sessions.client and sessions.client.api
            old_api = sessions.client.api
            old_directory = Path(sessions.client.directory.name)
            changed = sessions.select_namespace("default")
            assert changed.identity != first.identity
            assert changed.identity.connection_id == first.identity.connection_id
            assert changed.identity.generation > first.identity.generation
            assert sessions.select_namespace(None).namespace is None
            second = await sessions.connect("kubetrol-test-Two")
            assert second.identity.connection_id != first.identity.connection_id
            assert second.namespace == "default"
            assert old_api.rest_client.pool_manager.closed and not old_directory.exists()
            assert (tmp_path / "fixture-config").read_bytes() == original
            assert calls == ["Bearer synthetic", "Bearer synthetic"]
        finally:
            current_api = sessions.client.api
            await sessions.close()
            await sessions.close()
            assert current_api.rest_client.pool_manager.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (401, ConnectionState.AUTH_ERROR),
        (403, ConnectionState.LIMITED),
        (500, ConnectionState.API_ERROR),
        (302, ConnectionState.API_ERROR),
    ],
)
async def test_permission_auth_and_api_errors_are_distinct_without_raw_body(
    tmp_path: Path, status: int, state: ConnectionState
) -> None:
    async def handler(request):
        return web.Response(
            status=status,
            text="opaque-private-response",
            headers={"Location": "https://never-contact.invalid"},
        )

    async with fake_api(handler) as url:
        sessions = SessionService(
            catalog_fixture(tmp_path, url), ConnectionRequest(namespace="allowed")
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is state
            assert "opaque-private" not in observation.message
            if state is ConnectionState.LIMITED:
                assert sessions.client is not None
                assert sessions.select_namespace("allowed").namespace == "allowed"
            else:
                assert sessions.client is None
                with pytest.raises(AppError, match="Connect"):
                    sessions.select_namespace("default")
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_delayed_api_timeout_and_cancel_close_owned_client(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def handler(request):
        started.set()
        await asyncio.sleep(1)
        return namespaces("default")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest(timeout=0.1))
        timed_out = await sessions.connect("kubetrol-test-one")
        assert timed_out.state is ConnectionState.TIMEOUT and sessions.client is None
        started.clear()
        task = asyncio.create_task(sessions.connect("kubetrol-test-one"))
        await started.wait()
        api = sessions.client.api
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sessions.client is None and api.rest_client.pool_manager.closed


@pytest.mark.asyncio
async def test_unreachable_endpoint_does_not_use_old_identity(tmp_path: Path) -> None:
    async def handler(request):
        return namespaces("default")

    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url)
    sessions = SessionService(catalog, ConnectionRequest())
    observation = await sessions.connect("kubetrol-test-one")
    assert observation.state is ConnectionState.UNREACHABLE and sessions.client is None
    invalid = await sessions.connect("absent")
    assert (
        invalid.state is ConnectionState.CONFIG_ERROR and invalid.identity != observation.identity
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted,insecure", [(True, False), (False, False), (False, True)])
async def test_tls_is_verified_by_default_and_explicit_insecure_is_visible(
    tmp_path: Path, trusted: bool, insecure: bool
) -> None:
    tls, materials = certificate(tmp_path)

    async def handler(request):
        return namespaces("default")

    async with fake_api(handler, tls=tls) as url:
        cluster = (
            {"certificate-authority-data": materials["certificate-authority-data"]}
            if trusted
            else {}
        )
        if insecure:
            cluster["insecure-skip-tls-verify"] = True
        sessions = SessionService(
            catalog_fixture(tmp_path, url, cluster=cluster), ConnectionRequest()
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is (
                ConnectionState.CONNECTED if trusted or insecure else ConnectionState.TLS_ERROR
            )
            assert observation.insecure is insecure
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("embedded", [True, False])
async def test_client_certificate_pair_and_relative_ca_files(
    tmp_path: Path, embedded: bool
) -> None:
    tls, materials = certificate(tmp_path, client_auth=True)

    async def handler(request):
        assert request.transport.get_extra_info("peercert")
        return namespaces("default")

    async with fake_api(handler, tls=tls) as url:
        user = (
            {key: value for key, value in materials.items() if key.startswith("client-")}
            if embedded
            else {"client-certificate": "fixture-cert", "client-key": "fixture-key"}
        )
        cluster = (
            {"certificate-authority-data": materials["certificate-authority-data"]}
            if embedded
            else {"certificate-authority": "fixture-cert"}
        )
        sessions = SessionService(
            catalog_fixture(tmp_path, url, user, cluster), ConnectionRequest()
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is ConnectionState.CONNECTED
            directory = Path(sessions.client.directory.name)
            assert directory.stat().st_mode & 0o777 == 0o700
            assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())
        finally:
            await sessions.close()
        assert not directory.exists()


@pytest.mark.asyncio
async def test_namespace_pagination_is_bounded_and_complete(tmp_path: Path) -> None:
    tokens = []

    async def handler(request):
        tokens.append(request.query["continue"])
        return (
            namespaces("team", continuation="opaque-token")
            if len(tokens) == 1
            else namespaces("default")
        )

    async with fake_api(handler) as url:
        sessions = SessionService(
            catalog_fixture(tmp_path, url), ConnectionRequest(all_namespaces=True)
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.namespaces == ("default", "team") and observation.namespace is None
            assert tokens == ["", "opaque-token"]
            with pytest.raises(AppError):
                sessions.select_namespace("INVALID")
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b'{"items":null}',
        b'{"items":[null]}',
        b'{"items":[{"metadata":{"name":"BAD"}}]}',
        b'{"items":[],"metadata":{"continue":1}}',
        b"x" * (1024 * 1024 + 1),
    ],
)
async def test_invalid_or_excessive_response_is_not_an_empty_cluster(
    tmp_path: Path, body: bytes
) -> None:
    async def handler(request):
        return web.Response(body=body)

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        observation = await sessions.connect("kubetrol-test-one")
        assert observation.state is ConnectionState.API_ERROR and sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cluster,user,state",
    [
        ({"server": "ftp://127.0.0.1:12345"}, {}, ConnectionState.CONFIG_ERROR),
        ({"server": "http://user:secret@127.0.0.1:12345"}, {}, ConnectionState.CONFIG_ERROR),
        ({"server": "http://127.0.0.1:0"}, {}, ConnectionState.CONFIG_ERROR),
        ({"certificate-authority-data": 1}, {}, ConnectionState.CONFIG_ERROR),
        ({"certificate-authority-data": "!"}, {}, ConnectionState.CONFIG_ERROR),
        ({"certificate-authority-data": "eA=="}, {}, ConnectionState.TLS_ERROR),
        ({"certificate-authority": "missing"}, {}, ConnectionState.CONFIG_ERROR),
        ({"insecure-skip-tls-verify": 1}, {}, ConnectionState.CONFIG_ERROR),
        ({}, {"client-certificate-data": "eA=="}, ConnectionState.AUTH_ERROR),
        ({}, {"auth-provider": {"name": "oidc"}}, ConnectionState.AUTH_ERROR),
        ({}, {"username": "synthetic", "password": "synthetic"}, ConnectionState.AUTH_ERROR),
        ({}, {"exec": {}, "token": "synthetic"}, ConnectionState.AUTH_ERROR),
        ({}, {"exec": {}}, ConnectionState.AUTH_ERROR),
    ],
)
async def test_invalid_config_and_missing_auth_are_actionable_and_cleaned(
    tmp_path: Path, cluster: dict, user: dict, state: ConnectionState
) -> None:
    async def handler(request):
        pytest.fail("Invalid configuration reached API")

    async with fake_api(handler) as url:
        sessions = SessionService(
            catalog_fixture(tmp_path, url, user, cluster), ConnectionRequest()
        )
        observation = await sessions.connect("kubetrol-test-one")
        assert observation.state is state
        assert sessions.client is None
        assert "synthetic" not in observation.message


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [{}, {"tokenFile": "token"}])
async def test_anonymous_and_relative_token_file_credentials(tmp_path: Path, user: dict) -> None:
    (tmp_path / "token").write_text("synthetic-token-file\n")
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return namespaces("default")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, user), ConnectionRequest())
        try:
            assert (await sessions.connect("kubetrol-test-one")).state is ConnectionState.CONNECTED
            assert seen == (["Bearer synthetic-token-file"] if user else [None])
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_wrong_tls_server_name_is_rejected(tmp_path: Path) -> None:
    tls, material = certificate(tmp_path)

    async def handler(request):
        return namespaces("default")

    async with fake_api(handler, tls=tls) as url:
        cluster = {
            "certificate-authority-data": material["certificate-authority-data"],
            "tls-server-name": "incorrect.invalid",
        }
        sessions = SessionService(
            catalog_fixture(tmp_path, url, cluster=cluster), ConnectionRequest()
        )
        observation = await sessions.connect("kubetrol-test-one")
        assert observation.state is ConnectionState.TLS_ERROR and sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["items", "total", "pages"])
async def test_namespace_count_and_page_limits_do_not_loop_or_truncate_silently(
    tmp_path: Path, mode: str
) -> None:
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        if mode == "items":
            return namespaces(*(f"ns-{i}" for i in range(2049)))
        if mode == "total":
            return namespaces(*(f"ns-{calls}-{i}" for i in range(1500)), continuation="next")
        return namespaces("default", continuation="next")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        observation = await sessions.connect("kubetrol-test-one")
        assert observation.state is ConnectionState.API_ERROR and sessions.client is None
        assert calls == {"items": 1, "total": 2, "pages": 32}[mode]


@pytest.mark.asyncio
async def test_cancel_during_owned_filesystem_preparation_waits_for_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from kubetrol.adapters import kubernetes

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = kubernetes._prepare

    def delayed(context, directory):
        started.set()
        release.wait(timeout=2)
        try:
            return original(context, directory)
        finally:
            finished.set()

    monkeypatch.setattr(kubernetes, "_prepare", delayed)

    async def handler(request):
        return namespaces("default")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        task = asyncio.create_task(sessions.connect("kubetrol-test-one"))
        await asyncio.to_thread(started.wait, 2)
        directory = Path(sessions.client.directory.name)
        task.cancel()
        await asyncio.sleep(0)
        assert directory.exists()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and not directory.exists() and sessions.client is None


@pytest.mark.asyncio
async def test_explicit_owned_proxy_and_exec_extension_are_honored(
    tmp_path: Path, owned_test_proxies: set[str]
) -> None:
    import sys

    direct, proxied = [], []

    async def backend(request):
        direct.append(True)
        return namespaces("direct")

    async def proxy(request):
        proxied.append(request.headers.get("Authorization"))
        return namespaces("proxied")

    async with fake_api(backend) as server, fake_api(proxy) as proxy_url:
        owned_test_proxies.add(proxy_url)
        script = tmp_path / "proxy-helper.py"
        script.write_text(
            'import os,json\ni=json.loads(os.environ["KUBERNETES_EXEC_INFO"])\nassert i["spec"]["cluster"]["config"] == {"audience":"synthetic"}\nassert i["spec"]["cluster"]["proxy-url"] == '
            + repr(proxy_url)
            + '\nprint(json.dumps({"apiVersion":"client.authentication.k8s.io/v1","kind":"ExecCredential","status":{"token":"synthetic-proxy"}}))'
        )
        cluster = {
            "proxy-url": proxy_url,
            "extensions": [
                {"name": "unrelated", "extension": {}},
                {
                    "name": "client.authentication.k8s.io/exec",
                    "extension": {"audience": "synthetic"},
                },
            ],
        }
        user = {
            "exec": {
                "command": sys.executable,
                "args": ["proxy-helper.py"],
                "apiVersion": "client.authentication.k8s.io/v1",
                "interactiveMode": "Never",
                "provideClusterInfo": True,
            }
        }
        sessions = SessionService(
            catalog_fixture(tmp_path, server, user, cluster), ConnectionRequest()
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is ConnectionState.CONNECTED
            assert observation.namespaces == ("proxied",)
            assert direct == [] and proxied == ["Bearer synthetic-proxy"]
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_selected_namespace_is_remembered_when_returning_to_context(tmp_path: Path) -> None:
    async def handler(request):
        return namespaces("default", "team")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        try:
            await sessions.connect("kubetrol-test-one")
            sessions.select_namespace("default")
            await sessions.connect("kubetrol-test-Two")
            assert (await sessions.connect("kubetrol-test-one")).namespace == "default"
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_owned_process_close_hook_precedes_sdk_and_private_directory_cleanup(
    tmp_path, outcome
):
    async def handler(request):
        return namespaces("default")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        await sessions.connect("kubetrol-test-one")
        captured = sessions.client
        directory = Path(captured.directory.name)
        started, release = asyncio.Event(), asyncio.Event()

        async def before_close(client):
            assert client is captured and directory.exists() and client.api is not None
            started.set()
            if outcome == "cancel":
                await release.wait()
            if outcome == "failure":
                raise AppError("owned close-hook failure")

        sessions.before_close = before_close
        closing = asyncio.create_task(sessions.close())
        await started.wait()
        if outcome == "failure":
            with pytest.raises(AppError, match="close-hook"):
                await closing
        elif outcome == "cancel":
            closing.cancel()
            with pytest.raises(asyncio.CancelledError):
                await closing
        else:
            await closing
        assert sessions.client is None and not directory.exists()
        await sessions.close()
