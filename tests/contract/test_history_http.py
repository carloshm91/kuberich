"""Actual owned listeners qualify the independent external HTTP boundary."""

import asyncio
import gzip
import ssl

import pytest
from aiohttp import web

from kuberich.adapters.history_http import ExternalHistoryTransport
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.history import ExternalHistoryBackend
from kuberich.errors import AppError
from tests.support.connections import catalog_fixture, certificate
from tests.support.history import history_http


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bearer", "basic", "client-certificate"])
async def test_external_transport_cannot_inherit_api_identity_tls_proxy_netrc_or_cookies(
    tmp_path, monkeypatch, mode
):
    api_directory, external_directory = tmp_path / "api", tmp_path / "external"
    api_directory.mkdir()
    external_directory.mkdir()
    api_tls, material = certificate(api_directory)
    api_tls.verify_mode = ssl.CERT_OPTIONAL
    api_tls.load_verify_locations(cafile=str(api_directory / "fixture-cert"))
    external_tls, _ = certificate(external_directory)
    external_tls.verify_mode = ssl.CERT_OPTIONAL
    external_tls.load_verify_locations(cafile=str(api_directory / "fixture-cert"))
    api_seen, external_seen, trap_seen = [], [], []

    async def api(request):
        api_seen.append((dict(request.headers), request.transport.get_extra_info("peercert")))
        return web.json_response({"api": True})

    async def external(request):
        external_seen.append(
            (request.path, dict(request.headers), request.transport.get_extra_info("peercert"))
        )
        response = web.json_response({"external": True})
        response.set_cookie("synthetic-cookie", "private")
        return response

    async def trap(request):
        trap_seen.append(request.path)
        raise AssertionError("External endpoint used environment proxy")

    async with (
        history_http(api, tls=api_tls) as api_origin,
        history_http(external, tls=external_tls) as external_origin,
        history_http(trap) as trap_origin,
    ):
        user = (
            {"token": "synthetic-api-only"}
            if mode == "bearer"
            else {"username": "synthetic", "password": "api-only"}
            if mode == "basic"
            else {
                "client-certificate-data": material["client-certificate-data"],
                "client-key-data": material["client-key-data"],
            }
        )
        user.update(
            {
                "as": "synthetic-subject",
                "as-groups": ["synthetic-group"],
                "as-uid": "synthetic-uid",
                "as-user-extra": {"scope": ["synthetic-extra"]},
            }
        )
        catalog = catalog_fixture(
            api_directory,
            api_origin,
            user,
            {"certificate-authority-data": material["certificate-authority-data"]},
        )
        connection = catalog.select("kuberich-test-one")
        client = KubernetesSession(connection, 5)
        netrc = tmp_path / "synthetic-netrc"
        netrc.write_text("machine 127.0.0.1 login synthetic-netrc password private\n")
        monkeypatch.setenv("NETRC", str(netrc))
        for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            monkeypatch.setenv(key, trap_origin)
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        adapter = ExternalHistoryTransport(
            ExternalHistoryBackend(
                external_origin + "/select/23/prometheus",
                ca_file=external_directory / "fixture-cert",
            )
        )
        try:
            await client.open()
            assert await client.get_json("/owned-api") == {"api": True}
            for _ in range(2):
                assert await adapter.get_json("query", {"query": "vector(1)"}, max_bytes=1024) == {
                    "external": True
                }
        finally:
            await adapter.close()
            await client.close()
    assert len(api_seen) == 1 and len(external_seen) == 2 and not trap_seen
    api_headers, api_cert = api_seen[0]
    assert api_headers["Impersonate-User"] == "synthetic-subject"
    assert bool(api_cert) == (mode == "client-certificate")
    if mode != "client-certificate":
        assert api_headers["Authorization"].startswith("Bearer " if mode == "bearer" else "Basic ")
    for path, headers, peer in external_seen:
        assert path == "/select/23/prometheus/api/v1/query"
        assert not peer
        assert not any(
            name.lower() in {"authorization", "cookie"} or name.lower().startswith("impersonate-")
            for name in headers
        )


@pytest.mark.asyncio
async def test_external_token_rotation_replaces_pool_and_uses_only_independent_bearer(tmp_path):
    tls, _ = certificate(tmp_path)
    token = tmp_path / "synthetic-independent-bearer"
    token.write_text("synthetic-first")
    token.chmod(0o600)
    seen = []

    async def handler(request):
        seen.append(request.headers.get("Authorization"))
        return web.json_response({"ok": True})

    async with history_http(handler, tls=tls) as origin:
        transport = ExternalHistoryTransport(
            ExternalHistoryBackend(
                origin, ca_file=tmp_path / "fixture-cert", bearer_token_file=token
            )
        )
        try:
            await transport.get_json("status/buildinfo", {}, max_bytes=1024)
            revision = transport.auth_revision
            token.write_text("synthetic-second")
            await transport.get_json("query", {}, max_bytes=1024)
            assert transport.auth_revision != revision
        finally:
            await transport.close()
    assert seen == ["Bearer synthetic-first", "Bearer synthetic-second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 403, 404, 429, 503])
async def test_redirect_and_status_errors_retain_no_body_and_do_not_follow(status):
    seen = []

    async def handler(request):
        seen.append(request.path)
        return web.Response(
            status=status, headers={"Location": "/credential-trap"}, text="synthetic-private-body"
        )

    async with history_http(handler) as origin:
        transport = ExternalHistoryTransport(ExternalHistoryBackend(origin + "/tenant"))
        try:
            with pytest.raises(HttpProblem) as error:
                await transport.get_json("query_range", {}, max_bytes=1024)
            assert error.value.status == status and "private" not in repr(error.value)
        finally:
            await transport.close()
    assert seen == ["/tenant/api/v1/query_range"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["malformed", "chunked", "compressed", "tls", "unreachable"])
async def test_json_decoded_body_tls_and_connection_failures_are_bounded_and_sanitized(
    tmp_path, mode
):
    tls, _ = certificate(tmp_path)

    async def handler(request):
        if mode == "malformed":
            return web.Response(body=b"synthetic-private-error")
        if mode == "compressed":
            return web.Response(
                body=gzip.compress(b"x" * 2048), headers={"Content-Encoding": "gzip"}
            )
        response = web.StreamResponse()
        await response.prepare(request)
        for _ in range(16):
            await response.write(b"x" * 128)
        await response.write_eof()
        return response

    async with history_http(handler, tls=tls if mode == "tls" else None) as origin:
        transport = ExternalHistoryTransport(
            ExternalHistoryBackend("http://127.0.0.1:1" if mode == "unreachable" else origin)
        )
        try:
            with pytest.raises((AppError, ConnectionProblem)) as error:
                await transport.get_json("query", {}, max_bytes=1024)
            assert "synthetic-private" not in str(error.value)
        finally:
            await transport.close()


@pytest.mark.asyncio
async def test_close_cancels_and_drains_a_held_real_socket():
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return web.json_response({"ok": True})

    async with history_http(handler) as origin:
        transport = ExternalHistoryTransport(ExternalHistoryBackend(origin))
        task = asyncio.create_task(transport.get_json("query", {}, max_bytes=1024))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert transport.operation_count == 1
            await transport.close()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert transport.operation_count == 0
        finally:
            release.set()
            await transport.close()
