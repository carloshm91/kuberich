"""Owned distribution listeners exercise auth/origin/TLS/body and cancellation boundaries."""

import asyncio
import base64

import pytest
from aiohttp import web

from kuberich.adapters.helm_catalog_http import CatalogHttp
from kuberich.domain.helm_catalog import HelmRepository, HelmRepositoryKind, RepositoryCredentials
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from tests.support.connections import certificate
from tests.support.history import history_http


def mutate():
    AccessPolicy(False).require(Action.MUTATE)


def repository(origin, *, ca_file=None):
    return HelmRepository(
        "owned",
        origin + "/charts",
        HelmRepositoryKind.HTTP,
        "a" * 64,
        origin.startswith("http:"),
        ca_file,
    )


@pytest.mark.asyncio
async def test_static_bearer_and_same_origin_redirects_never_retain_cookies_or_netrc(
    tmp_path, monkeypatch
):
    seen = []

    async def handler(request):
        seen.append((request.path, dict(request.headers)))
        if request.path == "/start":
            response = web.Response(status=302, headers={"Location": "/finish"})
        else:
            response = web.Response(body=b"bounded")
        response.set_cookie("synthetic-private-cookie", "must-not-return")
        return response

    netrc = tmp_path / "ambient-netrc"
    netrc.write_text("machine 127.0.0.1 login ambient password private\n")
    monkeypatch.setenv("NETRC", str(netrc))
    async with history_http(handler) as origin:
        transport = CatalogHttp(
            repository(origin), RepositoryCredentials(token="synthetic-explicit")
        )
        try:
            for path in ("/start", "/finish"):
                assert (
                    await transport.get(
                        origin + path, max_bytes=64, accept="application/octet-stream", guard=mutate
                    )
                ).data == b"bounded"
        finally:
            await transport.close()
            await transport.close()
    assert [path for path, _ in seen] == ["/start", "/finish", "/finish"]
    assert all(
        headers.get("Authorization") == "Bearer synthetic-explicit" and "Cookie" not in headers
        for _, headers in seen
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["trusted", "untrusted", "missing-ca"])
async def test_independent_tls_requires_explicit_valid_ca_without_a_bypass(tmp_path, mode):
    tls, _ = certificate(tmp_path)

    async def handler(request):
        return web.Response(body=b"verified")

    async with history_http(handler, tls=tls) as origin:
        configured = repository(
            origin,
            ca_file=tmp_path / ("fixture-cert" if mode == "trusted" else "absent")
            if mode != "untrusted"
            else None,
        )
        transport = CatalogHttp(configured, RepositoryCredentials())
        try:
            operation = transport.get(
                origin + "/chart", max_bytes=64, accept="application/octet-stream", guard=mutate
            )
            if mode == "trusted":
                assert (await operation).data == b"verified"
            else:
                with pytest.raises(AppError):
                    await operation
        finally:
            await transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "advertised",
        "chunked",
        "redirect-loop",
        "redirect-query",
        "duplicate-header",
        "bad-basic",
        "not-found",
    ],
)
async def test_transport_bounds_and_refusals_keep_freeform_source_details_private(fault):
    async def handler(request):
        if fault == "advertised":
            return web.Response(body=b"x" * 100)
        if fault == "chunked":
            response = web.StreamResponse()
            response.enable_chunked_encoding()
            await response.prepare(request)
            await response.write(b"x" * 100)
            return response
        if fault in {"redirect-loop", "redirect-query"}:
            return web.Response(
                status=302,
                headers={
                    "Location": "/again" + ("?token=private" if fault == "redirect-query" else "")
                },
            )
        if fault == "duplicate-header":
            response = web.Response(body=b"small")
            response.headers.add("Docker-Content-Digest", "sha256:first")
            response.headers.add("Docker-Content-Digest", "sha256:second")
            return response
        return web.Response(
            status=401 if fault == "bad-basic" else 404,
            headers={"WWW-Authenticate": 'Basic realm="private"'},
            text="must-hide-source-and-secrets",
        )

    async with history_http(handler) as origin:
        transport = CatalogHttp(
            repository(origin),
            RepositoryCredentials(username="explicit", password="synthetic-private"),
        )
        try:
            with pytest.raises(AppError) as error:
                await transport.get(
                    origin + "/chart", max_bytes=64, accept="application/octet-stream", guard=mutate
                )
            assert "must-hide" not in str(error.value) and "synthetic-private" not in str(
                error.value
            )
            with pytest.raises(AppError):
                await transport.get(
                    origin + "/chart", max_bytes=0, accept="application/json", guard=mutate
                )
            with pytest.raises(AppError):
                await transport.get(
                    "https://foreign.invalid/chart",
                    max_bytes=64,
                    accept="application/json",
                    guard=mutate,
                )
        finally:
            await transport.close()
        with pytest.raises(AppError, match="closed"):
            await transport.get(
                origin + "/chart", max_bytes=64, accept="application/json", guard=mutate
            )


@pytest.mark.asyncio
async def test_close_drains_held_request_and_caller_cancellation_releases_listener():
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return web.Response(body=b"late")

    async with history_http(handler) as origin:
        transport = CatalogHttp(repository(origin), RepositoryCredentials())
        task = asyncio.create_task(
            transport.get(origin + "/chart", max_bytes=64, accept="application/json", guard=mutate)
        )
        await entered.wait()
        await transport.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["none", "scope", "realm", "duplicate", "ambiguous-token", "bad-token", "second-401"]
)
async def test_origin_and_pull_bound_bearer_exchange_is_bounded_and_never_forwards_caller_credentials(
    fault,
):
    seen = []
    origin = ""

    async def handler(request):
        seen.append((request.path, dict(request.headers), dict(request.query)))
        if request.path == "/token":
            if fault == "duplicate":
                return web.Response(
                    body=b'{"token":"first","token":"second"}', content_type="application/json"
                )
            if fault == "ambiguous-token":
                return web.json_response({"token": "first", "access_token": "second"})
            return web.json_response(
                {"token": "bad token" if fault == "bad-token" else "synthetic-registry-token"}
            )
        if (
            request.headers.get("Authorization") == "Bearer synthetic-registry-token"
            and fault != "second-401"
        ):
            return web.Response(body=b"manifest")
        realm = "https://foreign.invalid/token" if fault == "realm" else origin + "/token"
        scope = "repository:charts:pull,push" if fault == "scope" else "repository:charts:pull"
        return web.Response(
            status=401,
            headers={"WWW-Authenticate": f'Bearer realm="{realm}",service="owned",scope="{scope}"'},
        )

    async with history_http(handler) as address:
        origin = address
        transport = CatalogHttp(
            repository(origin), RepositoryCredentials(username="explicit", password="private")
        )
        try:
            operation = transport.get(
                origin + "/chart", max_bytes=128, accept="application/json", guard=mutate
            )
            if fault == "none":
                assert (await operation).data == b"manifest"
            else:
                with pytest.raises(AppError):
                    await operation
        finally:
            await transport.close()
    assert len(seen) <= 3
    tokens = [(headers, params) for path, headers, params in seen if path == "/token"]
    if tokens:
        assert (
            tokens[0][0]["Authorization"]
            == "Basic " + base64.b64encode(b"explicit:private").decode()
        )
        assert tokens[0][1] == {"scope": "repository:charts:pull", "service": "owned"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["duplicates", "unknown", "missing-realm", "no-service", "non-object", "missing-token"]
)
async def test_bearer_challenge_shape_and_token_document_are_not_ambient_authority(fault):
    origin = ""

    async def handler(request):
        if request.path == "/token":
            if fault == "non-object":
                return web.json_response([])
            if fault == "missing-token":
                return web.json_response({})
            return web.json_response({"access_token": "synthetic"})
        if request.headers.get("Authorization") == "Bearer synthetic":
            return web.Response(body=b"verified")
        challenge = f'Bearer realm="{origin}/token",scope="repository:charts:pull"'
        if fault == "duplicates":
            challenge += f',realm="{origin}/token"'
        elif fault == "unknown":
            challenge += ',foreign="unsupported"'
        elif fault == "missing-realm":
            challenge = 'Bearer scope="repository:charts:pull"'
        return web.Response(status=401, headers={"WWW-Authenticate": challenge})

    async with history_http(handler) as address:
        origin = address
        transport = CatalogHttp(repository(origin), RepositoryCredentials())
        try:
            operation = transport.get(
                origin + "/chart", max_bytes=128, accept="application/json", guard=mutate
            )
            if fault == "no-service":
                assert (await operation).data == b"verified"
            else:
                with pytest.raises(AppError):
                    await operation
            with pytest.raises(AppError, match="origins"):
                await transport.get(
                    "http://127.0.0.1:1/private",
                    max_bytes=128,
                    accept="application/json",
                    guard=mutate,
                )
        finally:
            await transport.close()


@pytest.mark.asyncio
async def test_actual_owned_slow_body_obeys_the_native_http_read_deadline():
    release = asyncio.Event()

    async def handler(request):
        response = web.StreamResponse()
        await response.prepare(request)
        await release.wait()
        return response

    async with history_http(handler) as origin:
        transport = CatalogHttp(repository(origin), RepositoryCredentials())
        try:
            with pytest.raises(AppError, match="timed out"):
                await transport.get(
                    origin + "/held", max_bytes=64, accept="application/json", guard=mutate
                )
        finally:
            release.set()
            await transport.close()
