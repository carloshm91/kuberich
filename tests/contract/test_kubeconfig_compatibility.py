"""Actual owned transports and read-only OIDC migration, never ambient accounts."""

import base64
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.mutations import guarded_request
from kuberich.cli import main
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, ConnectionState
from kuberich.domain.mutations import MutationState
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.sessions import SessionService
from tests.support.connections import catalog_fixture, certificate, namespaces
from tests.support.kubeconfig_api import captured_api


@pytest.mark.asyncio
@pytest.mark.parametrize("tls", [False, True])
@pytest.mark.parametrize(
    "user,expected",
    [
        ({}, None),
        ({"token": "synthetic"}, "Bearer synthetic"),
        ({"username": "demo", "password": "private"}, "Basic ZGVtbzpwcml2YXRl"),
        ({"username": "demo"}, "Basic ZGVtbzo="),
        ({"password": "private"}, "Basic OnByaXZhdGU="),
    ],
)
async def test_actual_read_and_guarded_write_share_prepared_scheme_without_bearer_confusion(
    tmp_path, tls, user, expected
):
    context, cluster = certificate(tmp_path) if tls else (None, {})
    async with captured_api(context) as (url, calls):
        catalog = catalog_fixture(tmp_path, url, user, {**cluster, "disable-compression": True})
        source = tmp_path / "fixture-config"
        before = source.read_bytes()
        client = KubernetesSession(catalog.select("kuberich-test-one"), 2)
        try:
            assert client.authorization_header() is None
            await client.open()
            assert await client.namespaces() == ("team",)
            result = await guarded_request(
                client,
                lambda: None,
                method="PATCH",
                path="/api/v1/namespaces",
                body=b"{}",
                content_type="application/json",
                accepted=(200,),
                receipt=lambda _: None,
            )
            assert result.state is MutationState.SUCCEEDED
            assert calls == [("GET", expected, "identity"), ("PATCH", expected, "identity")]
            private = client.delegated_config()
            expected_user = (
                {"username": user.get("username", ""), "password": user.get("password", "")}
                if "username" in user or "password" in user
                else user
            )
            assert private["users"][0]["user"] == expected_user
            captured = capture_delegation(client, {}, tmp_path, prefix="exec")
            async with stage_connection(captured.path, captured.configuration):
                assert stat.S_IMODE(captured.path.stat().st_mode) == 0o600
                staged = json.loads(captured.path.read_text())
                assert staged["users"][0]["user"] == expected_user
            assert not captured.path.exists()
            assert private["clusters"][0]["cluster"]["disable-compression"] is True
            if "username" in user or "password" in user:
                assert "BearerToken" not in client.configuration.api_key
        finally:
            directory = Path(client.directory.name)
            await client.close()
        assert client.authorization_header() is None and not directory.exists()
        assert source.read_bytes() == before


@pytest.mark.asyncio
async def test_token_override_replaces_basic_identity_and_does_not_modify_loaded_user(tmp_path):
    async with captured_api() as (url, calls):
        catalog = catalog_fixture(tmp_path, url, {"username": "demo", "password": "private"})
        selected = catalog.select("kuberich-test-one", ConnectionOverrides(token="explicit-token"))
        client = KubernetesSession(selected, 2)
        try:
            await client.open()
            assert await client.namespaces() == ("team",)
            assert calls == [("GET", "Bearer explicit-token", "identity")]
            assert client.delegated_config()["users"][0]["user"] == {"token": "explicit-token"}
        finally:
            await client.close()
        assert catalog.select("kuberich-test-one").user.data == {
            "username": "demo",
            "password": "private",
        }


def oidc_config(path, *, provider=None, context=True):
    data = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": "demo" if context else "",
        "clusters": [{"name": "demo", "cluster": {"server": "https://api.example.invalid"}}],
        "contexts": [{"name": "demo", "context": {"cluster": "demo", "user": "demo"}}],
        "users": [
            {
                "name": "demo",
                "user": {
                    "auth-provider": provider
                    or {
                        "name": "oidc",
                        "config": {
                            "idp-issuer-url": "https://issuer.example.invalid",
                            "client-id": "demo",
                            "client-secret": "private-secret",
                            "id-token": "private-id",
                            "refresh-token": "private-refresh",
                            "idp-certificate-authority": "issuer-ca.pem",
                        },
                    }
                },
            }
        ],
    }
    path.write_text(yaml.safe_dump(data))
    path.chmod(0o600)
    return data


def test_cli_migration_is_secret_free_does_not_execute_or_write_and_keeps_permissions(
    tmp_path, capsys
):
    path = tmp_path / "kubeconfig"
    oidc_config(path)
    before, mode = path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
    assert (
        main(["--kubeconfig", str(path), "--context", "demo", "kubeconfig", "oidc-migration"]) == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert all(
        value not in captured.out for value in ("private-secret", "private-id", "private-refresh")
    )
    fragment = yaml.safe_load(captured.out)
    assert fragment["exec"]["command"] == "kubelogin"
    assert fragment["exec"]["args"][-1] == "--certificate-authority=" + str(
        tmp_path / "issuer-ca.pem"
    )
    assert "REPLACE_WITH_CLIENT_SECRET_IN_PRIVATE_CONFIG" in captured.out
    assert path.read_bytes() == before and stat.S_IMODE(path.stat().st_mode) == mode == 0o600
    assert sorted(x.name for x in tmp_path.iterdir()) == ["kubeconfig"]


def test_fresh_migration_process_never_imports_sdk_or_textual(tmp_path):
    path = tmp_path / "kubeconfig"
    oidc_config(path)
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "importtime",
            "-m",
            "kuberich",
            "--kubeconfig",
            str(path),
            "kubeconfig",
            "oidc-migration",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    modules = [line.rsplit("|", 1)[-1].strip() for line in result.stderr.splitlines()]
    assert not any(name.split(".")[0] in {"textual", "kubernetes_asyncio"} for name in modules)
    assert "private-id" not in result.stdout and "private-refresh" not in result.stdout


@pytest.mark.parametrize(
    "extra",
    [
        ["--config", "never-read"],
        ["--readonly"],
        ["--namespace", "team"],
        ["--token", "private-token"],
        ["--log-level", "DEBUG"],
    ],
)
def test_migration_refuses_unrelated_flags_before_reading_any_source(extra, capsys):
    assert (
        main(["--kubeconfig", "/never/read/private", *extra, "kubeconfig", "oidc-migration"]) == 2
    )
    captured = capsys.readouterr()
    assert "accepts only --kubeconfig and --context" in captured.err
    assert "private" not in captured.err and captured.out == ""


def test_merged_migration_uses_the_original_user_directory_and_preserves_all_sources(
    tmp_path, monkeypatch, capsys
):
    cluster_file = tmp_path / "cluster"
    data = oidc_config(cluster_file)
    user_directory = tmp_path / "users"
    user_directory.mkdir()
    user_file = user_directory / "user"
    user_file.write_text(yaml.safe_dump({"users": data.pop("users")}))
    cluster_file.write_text(yaml.safe_dump(data))
    originals = {p: p.read_bytes() for p in (cluster_file, user_file)}
    monkeypatch.setenv("KUBECONFIG", str(cluster_file) + os.pathsep + str(user_file))
    assert main(["kubeconfig", "oidc-migration"]) == 0
    fragment = yaml.safe_load(capsys.readouterr().out)
    assert fragment["exec"]["args"][-1] == "--certificate-authority=" + str(
        user_directory / "issuer-ca.pem"
    )
    assert all(p.read_bytes() == value for p, value in originals.items())


def test_migration_names_missing_context_without_reading_a_default_context(tmp_path, capsys):
    path = tmp_path / "kubeconfig"
    oidc_config(path, context=False)
    assert main(["--kubeconfig", str(path), "kubeconfig", "oidc-migration"]) == 2
    assert "--context or a kubeconfig current-context" in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [None, ""])
async def test_empty_inline_tls_material_falls_back_to_original_files(tmp_path, empty):
    tls, material = certificate(tmp_path, client_auth=True)
    cluster, user = {}, {}
    for field in ("certificate-authority", "client-certificate", "client-key"):
        path = tmp_path / field
        path.write_bytes(base64.b64decode(material[field + "-data"]))
        target = cluster if field == "certificate-authority" else user
        target.update({field: path.name, field + "-data": empty})
    async with captured_api(tls) as (url, calls):
        client = KubernetesSession(
            catalog_fixture(tmp_path, url, user, cluster).select("kuberich-test-one"), 2
        )
        try:
            await client.open()
            assert await client.namespaces() == ("team",)
            assert calls == [("GET", None, "identity")]
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["token-file", "exec"])
async def test_shared_authorization_port_uses_refreshed_identity_for_read_and_write(
    tmp_path, mechanism
):
    current = tmp_path / "current-token"
    current.write_text("first-token")
    calls = []

    async def handler(request):
        token = request.headers.get("Authorization")
        calls.append((request.method, token))
        if token != "Bearer " + current.read_text():
            return web.Response(status=401)
        return namespaces("team") if request.method == "GET" else web.json_response({"ok": True})

    app = web.Application()
    app.router.add_route("*", "/api/v1/namespaces", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    if mechanism == "token-file":
        user = {"tokenFile": current.name}
    else:
        helper = tmp_path / "helper.py"
        helper.write_text(
            "import json\nfrom pathlib import Path\nprint(json.dumps({'apiVersion':'client.authentication.k8s.io/v1','kind':'ExecCredential','status':{'token':Path('current-token').read_text()}}))\n"
        )
        user = {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1",
                "command": sys.executable,
                "args": [str(helper)],
                "interactiveMode": "Never",
            }
        }
    client = KubernetesSession(catalog_fixture(tmp_path, url, user).select("kuberich-test-one"), 2)
    try:
        await client.open()
        assert await client.namespaces() == ("team",)
        current.write_text("second-token")
        assert await client.namespaces() == ("team",)
        result = await guarded_request(
            client,
            lambda: None,
            method="PATCH",
            path="/api/v1/namespaces",
            body=b"{}",
            content_type="application/json",
            accepted=(200,),
            receipt=lambda _: None,
        )
        assert result.state is MutationState.SUCCEEDED
        assert calls == [
            ("GET", "Bearer first-token"),
            ("GET", "Bearer first-token"),
            ("GET", "Bearer second-token"),
            ("PATCH", "Bearer second-token"),
        ]
    finally:
        await client.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_safe_catalog_field_error_survives_session_boundary_without_source_secrets(tmp_path):
    async with captured_api() as (url, calls):
        catalog = catalog_fixture(
            tmp_path, url, {"username": "demo", "password": "private-password"}
        )
        catalog.contexts["kuberich-test-one"].data["namespace"] = "private-token/invalid"
        sessions = SessionService(catalog, ConnectionRequest())
        try:
            observed = await sessions.connect("kuberich-test-one")
            assert observed.state is ConnectionState.CONFIG_ERROR
            assert observed.message == "contexts.context.namespace must be a valid namespace name."
            assert observed.identity.context == "kuberich-test-one"
            assert observed.identity.generation == 1
            assert sessions.client is None and calls == []
            assert "private" not in repr(observed)
        finally:
            await sessions.close()


@pytest.mark.parametrize("user", [False, "private-missing"])
def test_migration_missing_or_malformed_user_returns_field_message_without_traceback(
    tmp_path, capsys, user
):
    path = tmp_path / "kubeconfig"
    data = oidc_config(path)
    data["contexts"][0]["context"]["user"] = user
    path.write_text(yaml.safe_dump(data))
    assert main(["--kubeconfig", str(path), "kubeconfig", "oidc-migration"]) == 2
    captured = capsys.readouterr()
    assert "contexts.context.user" in captured.err
    assert "private-missing" not in captured.err and "Traceback" not in captured.err
    assert captured.out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user,cluster,field",
    [
        ({"exec": False}, {}, "users.user.exec"),
        ({"token": "private\n"}, {}, "users.user.token"),
        ({"tokenFile": False}, {}, "users.user.tokenFile"),
        ({}, {"proxy-url": "ftp://private.example.invalid"}, "clusters.cluster.proxy-url"),
        (
            {"username": "demo", "password": "private", "token": "private-token"},
            {},
            "username/password",
        ),
        ({"as-groups": ["demo"]}, {}, "users.user.as"),
        ({"as": False}, {}, "users.user.as"),
        ({}, {"disable-compression": "private"}, "disable-compression"),
        ({}, {"tls-server-name": False}, "tls-server-name"),
        ({}, {"certificate-authority-data": "private-invalid-base64"}, "certificate-authority"),
        ({"client-certificate": "private-missing"}, {}, "client-certificate"),
        (
            {"auth-provider": {"name": "oidc", "config": {"id-token": "private-id"}}},
            {},
            "kubeconfig oidc-migration",
        ),
    ],
)
async def test_known_unsupported_or_invalid_fields_have_actionable_safe_session_errors(
    tmp_path, user, cluster, field
):
    async with captured_api() as (url, calls):
        sessions = SessionService(
            catalog_fixture(tmp_path, url, user, cluster), ConnectionRequest()
        )
        try:
            observed = await sessions.connect("kuberich-test-one")
            assert observed.state in {
                ConnectionState.CONFIG_ERROR,
                ConnectionState.AUTH_ERROR,
                ConnectionState.TLS_ERROR,
            }
            assert field in observed.message
            assert "private" not in observed.message and calls == []
            assert sessions.client is None
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_empty_impersonation_fields_remain_anonymous_without_disabling_validation(tmp_path):
    user = {"as": "", "as-uid": "", "as-groups": None, "as-user-extra": None}
    async with captured_api() as (url, calls):
        client = KubernetesSession(
            catalog_fixture(tmp_path, url, user).select("kuberich-test-one"), 2
        )
        try:
            await client.open()
            assert await client.namespaces() == ("team",)
            assert calls == [("GET", None, "identity")]
            assert client.impersonation == ()
        finally:
            await client.close()
