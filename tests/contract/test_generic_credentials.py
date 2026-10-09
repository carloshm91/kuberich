"""Owned token-file and certificate refresh effects over actual HTTP/TLS."""

import asyncio
import base64
import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from cryptography.hazmat.primitives import serialization

from kuberich.adapters import kubernetes
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest, ConnectionState
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.sessions import SessionService
from tests.support.connections import catalog_fixture, certificate, fake_api, namespaces

VERSION = "client.authentication.k8s.io/v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("traditional", [False, True])
async def test_static_encrypted_key_refuses_before_tls_can_prompt_or_contact_api(
    tmp_path, inline, traditional
):
    _, material = certificate(tmp_path)
    key = serialization.load_pem_private_key(
        base64.b64decode(material["client-key-data"]), password=None
    )
    encrypted = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL
        if traditional
        else serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"owned-private-password"),
    )
    path = tmp_path / "encrypted-key"
    path.write_bytes(encrypted)
    user = {
        "client-certificate-data": material["client-certificate-data"],
        **(
            {"client-key-data": base64.b64encode(encrypted).decode()}
            if inline
            else {"client-key": path.name}
        ),
    }
    called = []

    async def handler(request):
        called.append(True)
        return namespaces("wrong")

    async with fake_api(handler) as server:
        sessions = SessionService(catalog_fixture(tmp_path, server, user), ConnectionRequest())
        try:
            async with asyncio.timeout(2):
                result = await sessions.connect("kuberich-test-one")
            assert result.state is ConnectionState.AUTH_ERROR
            assert "Encrypted client TLS keys" in result.message
            assert (
                "owned-private-password" not in result.message
                and "PRIVATE KEY" not in result.message
            )
            assert not called and sessions.client is None
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_token_file_precedes_static_token_refreshes_on_401_and_delegates_same_file(tmp_path):
    path = tmp_path / "token"
    path.write_text("first-token\n")
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        if request.headers.get("Authorization") != "Bearer " + path.read_text().strip():
            return web.Response(status=401)
        return namespaces("team")

    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url, {"token": "static-fallback", "tokenFile": "token"})
        session = KubernetesSession(catalog.select(catalog.current), 5)
        try:
            await session.open()
            assert await session.namespaces() == ("team",)
            assert seen == ["Bearer first-token"]
            path.write_text("second-token\n")
            assert await session.namespaces() == ("team",)
            assert seen[-2:] == ["Bearer first-token", "Bearer second-token"]
            private = session.delegated_config()["users"][0]["user"]
            assert private == {"token": "second-token", "tokenFile": str(path)}
            # Unavailable rotations retain the last successfully read value.
            path.unlink()
            session.token_read_after = 0
            await session.refresh_credentials()
            assert session.configuration.api_key["BearerToken"] == "Bearer second-token"
        finally:
            directory = Path(session.directory.name)
            await session.close()
        assert not directory.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["exec", "forward", "helm"])
@pytest.mark.parametrize(
    "helper_name,args",
    [
        ("gke-gcloud-auth-plugin", ["--use_application_default_credentials"]),
        ("kubelogin", ["get-token", "--oidc-issuer-url=https://issuer.invalid"]),
        ("oidc-helper", ["literal;$(never-executed)"]),
    ],
)
async def test_generic_provider_contract_pins_path_environment_cluster_info_and_delegation(
    tmp_path, monkeypatch, owned_test_proxies, helper_name, args, purpose
):
    monkeypatch.setattr(kubernetes.os, "environ", {"PATH": kubernetes.os.defpath})
    monkeypatch.setenv("CAPTURED_IDENTITY", "original-private-identity")
    monkeypatch.delenv("OIDC_INJECTED_IDENTITY", raising=False)
    helper_dir = tmp_path / "bin"
    helper_dir.mkdir()
    helper = helper_dir / helper_name
    helper.write_text(
        f"#!{sys.executable}\n"
        + "import os,json,sys\nfrom pathlib import Path\n"
        + "assert sys.stdin.read()==''\nassert os.environ['CAPTURED_IDENTITY']=='original-private-identity'\nassert 'OIDC_INJECTED_IDENTITY' not in os.environ\nassert os.environ['DECLARED_IDENTITY']=='selected'\n"
        + f"assert sys.argv[1:]=={args!r}\n"
        + "Path('invocation.json').write_text(os.environ['KUBERNETES_EXEC_INFO'])\n"
        + f"print(json.dumps({{'apiVersion':{VERSION!r},'kind':'ExecCredential','status':{{'token':'generic-selected'}}}}))\n"
    )
    helper.chmod(0o700)
    user = {
        "exec": {
            "command": helper_name,
            "args": args,
            "apiVersion": VERSION,
            "interactiveMode": "Never",
            "provideClusterInfo": True,
            "env": [
                {"name": "PATH", "value": "bin"},
                {"name": "DECLARED_IDENTITY", "value": "selected"},
            ],
        }
    }
    called = []

    async def backend(request):
        called.append("wrong-direct-route")
        return namespaces("wrong")

    async def proxy(request):
        assert request.headers["Authorization"] == "Bearer generic-selected"
        called.append("captured-proxy")
        return namespaces("team")

    tls, material = certificate(tmp_path)
    async with fake_api(backend, tls=tls) as server, fake_api(proxy) as proxy_url:
        owned_test_proxies.add(proxy_url)
        cluster = {
            "certificate-authority-data": material["certificate-authority-data"],
            "tls-server-name": "owned-api.invalid",
            "proxy-url": proxy_url,
            "extensions": [
                {"name": "client.authentication.k8s.io/exec", "extension": {"audience": "selected"}}
            ],
        }
        # A plaintext API request through the proxy still carries the cluster's
        # declared CA/name fields in ExecCredential; TLS itself is tested separately.
        server = server.replace("https:", "http:")
        catalog = catalog_fixture(tmp_path, server, user, cluster)
        original = (tmp_path / "fixture-config").read_bytes()
        session = KubernetesSession(catalog.select("kuberich-test-one"), 3)
        monkeypatch.setenv("CAPTURED_IDENTITY", "changed-identity")
        monkeypatch.setenv("OIDC_INJECTED_IDENTITY", "different-identity")
        try:
            await session.open()
            assert await session.namespaces() == ("team",)
            info = json.loads((tmp_path / "invocation.json").read_text())["spec"]
            assert info["interactive"] is False
            assert info["cluster"] == {
                "server": server,
                "insecure-skip-tls-verify": False,
                "certificate-authority-data": material["certificate-authority-data"],
                "tls-server-name": "owned-api.invalid",
                "proxy-url": proxy_url,
                "config": {"audience": "selected"},
            }
            captured = capture_delegation(
                session,
                {"PATH": "wrong", "OIDC_INJECTED_IDENTITY": "wrong"},
                tmp_path / "wrong",
                prefix=purpose,
            )
            private = json.loads(captured.configuration)
            assert private["users"][0]["user"]["exec"]["command"] == str(helper)
            assert captured.directory == tmp_path
            assert dict(captured.environment)["CAPTURED_IDENTITY"] == "original-private-identity"
            assert "OIDC_INJECTED_IDENTITY" not in dict(captured.environment)
            assert private["clusters"][0]["cluster"]["proxy-url"] == proxy_url
            async with stage_connection(captured.path, captured.configuration):
                assert captured.path.stat().st_mode & 0o777 == 0o600
                assert json.loads(captured.path.read_text()) == private
            assert not captured.path.exists() and called == ["captured-proxy"]
            assert (tmp_path / "fixture-config").read_bytes() == original
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_missing_token_file_uses_only_explicit_fallback_and_never_anonymous_identity(
    tmp_path,
):
    async def handler(request):
        assert request.headers["Authorization"] == "Bearer configured-fallback"
        return namespaces("team")

    async with fake_api(handler) as url:
        sessions = SessionService(
            catalog_fixture(
                tmp_path, url, {"token": "configured-fallback", "tokenFile": "missing"}
            ),
            ConnectionRequest(),
        )
        try:
            assert (await sessions.connect("kuberich-test-one")).state is ConnectionState.CONNECTED
        finally:
            await sessions.close()
        sessions = SessionService(
            catalog_fixture(tmp_path, url, {"tokenFile": "missing"}), ConnectionRequest()
        )
        assert (await sessions.connect("kuberich-test-one")).state is ConnectionState.AUTH_ERROR
        assert sessions.client is None


def exec_user(path: Path):
    script = path / "generic-helper.py"
    script.write_text("from pathlib import Path\nprint(Path('credential.json').read_text())\n")
    return {
        "exec": {
            "command": sys.executable,
            "args": [script.name],
            "apiVersion": VERSION,
            "interactiveMode": "Never",
        }
    }


def write_certificate(path, materials):
    status = {
        "clientCertificateData": base64.b64decode(materials["client-certificate-data"]).decode(),
        "clientKeyData": base64.b64decode(materials["client-key-data"]).decode(),
        "expirationTimestamp": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    (path / "credential.json").write_text(
        json.dumps({"apiVersion": VERSION, "kind": "ExecCredential", "status": status})
    )


@pytest.mark.asyncio
async def test_exec_certificate_rotation_closes_old_pool_and_handshakes_with_new_pair(tmp_path):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    tls, first = certificate(first_dir, client_auth=True)
    _, second = certificate(second_dir, client_auth=True, common_name="second-owned-client")
    tls.load_verify_locations(cafile=str(second_dir / "fixture-cert"))
    peers = []

    async def handler(request):
        peers.append(request.transport.get_extra_info("peercert")["serialNumber"])
        assert "Authorization" not in request.headers
        return namespaces("team")

    write_certificate(tmp_path, first)
    async with fake_api(handler, tls=tls) as url:
        session = KubernetesSession(
            catalog_fixture(
                tmp_path,
                url,
                exec_user(tmp_path),
                {"certificate-authority-data": first["certificate-authority-data"]},
            ).select("kuberich-test-one"),
            5,
        )
        try:
            await session.open()
            assert await session.namespaces() == ("team",)
            original = session.api.rest_client.pool_manager
            files = session.certificate_files
            assert len(files) == 2 and all(p.stat().st_mode & 0o777 == 0o600 for p in files)
            snapshot = session.delegated_config()["users"][0]["user"]
            assert set(snapshot) == {
                "exec"
            }  # Never export conflicting static cert + exec identities.
            write_certificate(tmp_path, second)
            session.credentials.expiration = datetime.now(UTC) - timedelta(seconds=1)
            assert (
                await asyncio.gather(*(session.namespaces() for _ in range(8))) == [("team",)] * 8
            )
            assert original.closed and session.api.rest_client.pool_manager is not original
            assert len(set(peers)) == 2 and all(p == peers[-1] for p in peers[1:])
            assert all(not p.exists() for p in files)
            assert len(session.certificate_files) == 2
            assert len(list(Path(session.directory.name).iterdir())) == 3
            # A mismatched replacement key never falls back to the old TLS identity.
            invalid = dict(second, **{"client-key-data": first["client-key-data"]})
            write_certificate(tmp_path, invalid)
            session.credentials.invalidate()
            before = len(peers)
            with pytest.raises(ConnectionProblem) as error:
                await session.namespaces()
            assert error.value.state is ConnectionState.TLS_ERROR
            assert "PRIVATE KEY" not in str(error.value) and len(peers) == before
            write_certificate(tmp_path, second)
            session.credentials.invalidate()
            assert await session.namespaces() == ("team",)
        finally:
            directory = Path(session.directory.name)
            await session.close()
        assert not directory.exists()


@pytest.mark.asyncio
async def test_certificate_to_token_transition_replaces_pool_and_removes_old_private_pair(tmp_path):
    _, material = certificate(tmp_path)
    write_certificate(tmp_path, material)
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return namespaces("team")

    async with fake_api(handler) as server:
        session = KubernetesSession(
            catalog_fixture(tmp_path, server, exec_user(tmp_path)).select("kuberich-test-one"), 3
        )
        try:
            await session.open()
            assert await session.namespaces() == ("team",)
            pair, pool = session.certificate_files, session.api.rest_client.pool_manager
            (tmp_path / "credential.json").write_text(
                json.dumps(
                    {
                        "apiVersion": VERSION,
                        "kind": "ExecCredential",
                        "status": {"token": "replacement-token"},
                    }
                )
            )
            session.credentials.invalidate()
            assert await session.namespaces() == ("team",)
            assert seen == [None, "Bearer replacement-token"]
            assert pool.closed and session.api.rest_client.pool_manager is not pool
            assert not session.certificate_files and all(not path.exists() for path in pair)
            assert (
                session.configuration.cert_file is None and session.configuration.key_file is None
            )
        finally:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["cert", "key"])
async def test_certificate_file_collision_preserves_existing_file_and_previous_identity(
    tmp_path, collision
):
    _, material = certificate(tmp_path)
    write_certificate(tmp_path, material)

    async def handler(request):
        return namespaces("team")

    async with fake_api(handler) as server:
        session = KubernetesSession(
            catalog_fixture(tmp_path, server, exec_user(tmp_path)).select("kuberich-test-one"), 3
        )
        try:
            await session.open()
            original = session.certificate_files
            pool = session.api.rest_client.pool_manager
            protected = (
                Path(session.directory.name)
                / f"exec-{session.credentials.revision + 1}-{collision}.pem"
            )
            protected.write_text("owned-preexisting-sentinel")
            session.credentials.invalidate()
            with pytest.raises(FileExistsError):
                await session.refresh_credentials()
            assert protected.read_text() == "owned-preexisting-sentinel"
            assert all(path.exists() for path in original)
            assert (
                session.certificate_files == original
                and session.api.rest_client.pool_manager is pool
            )
            assert session.configuration.cert_file == str(original[0])
            assert len(list(Path(session.directory.name).iterdir())) == 3
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_real_certificate_preparation_before_close(
    tmp_path, monkeypatch
):
    _, material = certificate(tmp_path)
    write_certificate(tmp_path, material)
    started, release = threading.Event(), threading.Event()
    original_context = kubernetes._ssl_context

    def held_context(configuration, **kwargs):
        started.set()
        assert release.wait(3)
        return original_context(configuration, **kwargs)

    async def handler(request):
        return namespaces("team")

    async with fake_api(handler) as server:
        session = KubernetesSession(
            catalog_fixture(tmp_path, server, exec_user(tmp_path)).select("kuberich-test-one"), 3
        )
        await session.open()
        monkeypatch.setattr(kubernetes, "_ssl_context", held_context)
        session.credentials.invalidate()
        refresh = asyncio.create_task(session.refresh_credentials())
        try:
            async with asyncio.timeout(3):
                while not started.is_set():
                    await asyncio.sleep(0.001)
            directory = Path(session.directory.name)
            refresh.cancel()
            await asyncio.sleep(0)
            refresh.cancel()
            closing = asyncio.create_task(session.close())
            await asyncio.sleep(0.01)
            assert not refresh.done() and not closing.done() and directory.exists()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await refresh
            await closing
            assert not directory.exists() and session.api is None
        finally:
            release.set()
            await asyncio.gather(refresh, return_exceptions=True)
            await session.close()
