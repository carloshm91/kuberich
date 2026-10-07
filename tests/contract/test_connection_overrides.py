"""Effective invocation identity reaches real HTTP/TLS and delegated kubectl."""

import json
import stat
import sys
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.config.catalog import Entry
from kubetrol.domain.connection_overrides import ConnectionOverrides
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.domain.targets import ResourceTarget
from kubetrol.services.access import AccessPolicy
from kubetrol.services.sessions import SessionService
from kubetrol.services.shell import ShellService
from tests.support.connections import catalog_fixture, certificate, fake_api, namespaces
from tests.support.pods import pod
from tests.support.workspace import workspace_api


@pytest.mark.asyncio
async def test_alternate_cluster_user_and_impersonation_reach_reads_streams_and_shell(tmp_path):
    received = []

    def identity(request):
        received.append(request.path)
        assert request.headers["Authorization"] == "Bearer alternate-token"
        assert request.headers["Impersonate-User"] == "system:serviceaccount:team:viewer"
        assert request.headers.getall("Impersonate-Group") == [
            "group-one",
            "group-two",
            "group-one",
        ]

    async def probe(request):
        identity(request)
        return namespaces("team")

    async def resource(request):
        identity(request)
        if request.path.endswith("/log"):
            return web.Response(text="owned log\n")
        if "watch" in request.query:
            return web.Response(
                text='{"type":"BOOKMARK","object":{"metadata":{"resourceVersion":"opaque"}}}\n'
            )
        return web.json_response(pod("api", uid="api-uid"))

    async with workspace_api(probe, resource) as url:
        catalog = catalog_fixture(tmp_path, "http://127.0.0.1:1")
        catalog.clusters["alternate"] = Entry({"server": url}, tmp_path)
        catalog.users["alternate"] = Entry({"token": "alternate-token"}, tmp_path)
        original = (tmp_path / "fixture-config").read_bytes()
        overrides = ConnectionOverrides(
            cluster="alternate",
            user="alternate",
            as_user="system:serviceaccount:team:viewer",
            as_groups=("group-one", "group-two", "group-one"),
        )
        sessions = SessionService(catalog, ConnectionRequest(overrides=overrides))
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is ConnectionState.CONNECTED
            client = sessions.client
            assert (await client.get_json("/api/v1/namespaces/team/pods/api", params={}))[
                "metadata"
            ]["uid"] == "api-uid"
            logs = [
                value
                async for value in client.log_bytes(
                    "/api/v1/namespaces/team/pods/api/log", {}, follow=False
                )
            ]
            assert logs == [None, b"owned log\n"]
            watch = [
                value async for value in client.watch_json("/api/v1/namespaces/team/pods", "opaque")
            ]
            assert watch[1]["type"] == "BOOKMARK"
            target = ResourceTarget(observation.identity, "", "pods", "team", "api", "api-uid")
            shell = ShellService(
                client,
                target,
                AccessPolicy(False),
                lambda: True,
                shell=("sh",),
                directory=tmp_path,
                environment={"PATH": str(tmp_path)},
            )
            executable = tmp_path / "kubectl"
            executable.write_text(f"#!{sys.executable}\n")
            executable.chmod(0o700)
            captured = shell.capture("app")
            catalog.users["alternate"].data["token"] = "changed-after-capture"
            async with shell.stage(captured):
                assert stat.S_IMODE(captured.path.stat().st_mode) == 0o600
                connection = json.loads(captured.path.read_text())
                assert connection["clusters"][0]["cluster"]["server"] == url
                user = connection["users"][0]["user"]
                assert user["token"] == "alternate-token"
                assert user["as"] == overrides.as_user and user["as-groups"] == list(
                    overrides.as_groups
                )
            assert not captured.path.exists()
            catalog.users["alternate"].data["token"] = "alternate-token"
            second = await sessions.connect("kubetrol-test-Two")
            assert second.state is ConnectionState.CONNECTED
            assert (
                client.api is None
                and second.identity.connection_id != observation.identity.connection_id
            )
            assert (tmp_path / "fixture-config").read_bytes() == original
            assert len(received) == 6
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_explicit_token_suppresses_configured_helper_without_running_it(tmp_path):
    marker = tmp_path / "helper-ran"
    helper = tmp_path / "helper.py"
    helper.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('must not run')\n"
    )

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer explicit-token"
        return namespaces("team")

    user = {
        "exec": {
            "command": sys.executable,
            "args": [str(helper)],
            "apiVersion": "client.authentication.k8s.io/v1",
            "interactiveMode": "Never",
        },
        "as": "original",
        "as-groups": ["original-group"],
    }
    async with fake_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url, user)
        sessions = SessionService(
            catalog, ConnectionRequest(overrides=ConnectionOverrides(token="explicit-token"))
        )
        try:
            assert (await sessions.connect("kubetrol-test-one")).state is ConnectionState.CONNECTED
            assert sessions.client.credentials is None
            delegated = sessions.client.delegated_config()["users"][0]["user"]
            assert delegated == {
                "token": "explicit-token",
                "as": "original",
                "as-groups": ["original-group"],
            }
            assert "exec" in catalog.select("kubetrol-test-one").user.data
            assert not marker.exists()
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state", [(401, ConnectionState.AUTH_ERROR), (403, ConnectionState.LIMITED)]
)
async def test_impersonation_denial_keeps_safe_status_and_original_config(tmp_path, status, state):
    async def handler(request):
        assert request.headers["Impersonate-User"] == "denied-subject"
        return web.Response(status=status, text="opaque-private-token")

    async with fake_api(handler) as url:
        sessions = SessionService(
            catalog_fixture(tmp_path, url),
            ConnectionRequest(overrides=ConnectionOverrides(as_user="denied-subject")),
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is state and "opaque-private-token" not in observation.message
            assert (sessions.client is not None) is (status == 403)
        finally:
            await sessions.close()


@pytest.mark.asyncio
async def test_loaded_impersonation_uid_and_repeated_extras_survive_delegation(tmp_path):
    user = {
        "token": "synthetic",
        "as": "subject",
        "as-uid": "owned-uid",
        "as-groups": ["one", "two"],
        "as-user-extra": {"Example.io/Scope": ["first", "second"]},
    }

    async def handler(request):
        assert request.headers["Impersonate-Uid"] == "owned-uid"
        assert request.headers.getall("Impersonate-Extra-example.io%2Fscope") == ["first", "second"]
        return namespaces("team")

    async with fake_api(handler) as url:
        sessions = SessionService(catalog_fixture(tmp_path, url, user), ConnectionRequest())
        try:
            assert (await sessions.connect("kubetrol-test-one")).state is ConnectionState.CONNECTED
            assert sessions.client.delegated_config()["users"][0]["user"] == user
        finally:
            await sessions.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ca", "insecure", "verify", "client-pair"])
async def test_tls_overrides_replace_captured_material_and_keep_verification_explicit(
    tmp_path, mode
):
    tls, _ = certificate(tmp_path, client_auth=mode == "client-pair")
    calls = []

    async def handler(request):
        calls.append(True)
        if mode == "client-pair":
            assert request.transport.get_extra_info("peercert")
        return namespaces("team")

    cluster = {
        "certificate-authority-data": "invalid",
        "certificate-authority": "missing",
        "insecure-skip-tls-verify": True,
    }
    overrides = {
        "ca": ConnectionOverrides(certificate_authority=str(tmp_path / "fixture-cert")),
        "insecure": ConnectionOverrides(insecure=True),
        "verify": ConnectionOverrides(insecure=False),
        "client-pair": ConnectionOverrides(
            certificate_authority=str(tmp_path / "fixture-cert"),
            client_certificate=str(tmp_path / "fixture-cert"),
            client_key=str(tmp_path / "fixture-key"),
        ),
    }[mode]
    if mode == "verify":
        cluster = {"insecure-skip-tls-verify": True}
    user = (
        {"exec": {}, "client-certificate-data": "invalid", "client-key-data": "invalid"}
        if mode == "client-pair"
        else {}
    )
    async with fake_api(handler, tls=tls) as url:
        sessions = SessionService(
            catalog_fixture(tmp_path, url, user, cluster), ConnectionRequest(overrides=overrides)
        )
        try:
            observation = await sessions.connect("kubetrol-test-one")
            assert observation.state is (
                ConnectionState.TLS_ERROR if mode == "verify" else ConnectionState.CONNECTED
            )
            assert observation.insecure is (mode == "insecure")
            if mode != "verify":
                delegated = sessions.client.delegated_config()
                assert delegated["clusters"][0]["cluster"]["insecure-skip-tls-verify"] is (
                    mode == "insecure"
                )
                assert len(calls) == 1
                if mode == "client-pair":
                    assert "exec" not in delegated["users"][0]["user"]
                    assert all(
                        Path(delegated["users"][0]["user"][key]).is_file()
                        for key in ("client-key", "client-certificate")
                    )
            else:
                assert calls == [] and sessions.client is None
        finally:
            await sessions.close()
