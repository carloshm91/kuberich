"""Actual owned proxy transport, TLS names, identity headers and lifecycle."""

import asyncio
import base64
import socket
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from aiohttp.resolver import DefaultResolver
from kubernetes_asyncio import client

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, ConnectionState
from tests.conftest import _CLIENT
from tests.support.connections import catalog_fixture, certificate, fake_api, namespaces
from tests.support.http_proxy import http_proxy
from tests.support.socks_proxy import socks_proxy


@pytest.mark.asyncio
async def test_socks_certificate_validation_is_disabled_only_by_explicit_configuration(
    tmp_path, owned_test_proxies
):
    called = []

    async def handler(request):
        called.append(True)
        return namespaces("team")

    tls, _ = certificate(tmp_path, dns_name="untrusted.invalid")
    async with fake_api(handler, tls=tls) as server, socks_proxy(server) as (proxy, witness):
        owned_test_proxies.add(proxy)
        session = KubernetesSession(
            catalog_fixture(
                tmp_path, server, cluster={"proxy-url": proxy, "insecure-skip-tls-verify": True}
            ).select("kuberich-test-one"),
            3,
        )
        try:
            await session.open()
            assert session.insecure
            assert await session.namespaces() == ("team",)
            assert called == [True] and witness.destinations
        finally:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["logs", "watch"])
@pytest.mark.parametrize(
    "mode,state",
    [
        ("disconnect", ConnectionState.UNREACHABLE),
        ("hang", ConnectionState.TIMEOUT),
        ("invalid-tls", ConnectionState.TLS_ERROR),
    ],
)
async def test_socks_stream_failures_keep_classification_and_owned_cleanup(
    tmp_path, owned_test_proxies, operation, mode, state
):
    async def handler(request):
        raise AssertionError("A refused proxy/TLS handshake cannot reach the API.")

    tls, material = certificate(tmp_path, dns_name="owned-api.invalid")
    async with fake_api(handler, tls=tls if mode == "invalid-tls" else None) as server:
        async with socks_proxy(server, mode="relay" if mode == "invalid-tls" else mode) as (
            proxy,
            witness,
        ):
            owned_test_proxies.add(proxy)
            cluster = {"proxy-url": proxy}
            if mode == "invalid-tls":
                cluster.update(
                    {
                        "certificate-authority-data": material["certificate-authority-data"],
                        "tls-server-name": "incorrect.invalid",
                    }
                )
            session = KubernetesSession(
                catalog_fixture(tmp_path, server, cluster=cluster).select("kuberich-test-one"), 0.2
            )
            try:
                await session.open()
                stream = (
                    session.log_bytes("/api/v1/namespaces", {}, follow=True)
                    if operation == "logs"
                    else session.watch_json("/api/v1/namespaces", "opaque")
                )
                try:
                    with pytest.raises(ConnectionProblem) as error:
                        async with asyncio.timeout(2):
                            await anext(stream)
                    assert error.value.state is state
                finally:
                    await stream.aclose()
            finally:
                await session.close()
        assert not witness.active


def owned_dns(monkeypatch, server, proxy):
    """Resolve one reserved fixture name; never permit a remote API fallback."""
    alias = "owned-api.invalid"
    port = urlsplit(server).port
    target = server.replace("127.0.0.1", alias)
    original_resolve = DefaultResolver.resolve

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host == alias:
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": 0,
                }
            ]
        return await original_resolve(self, host, port, family)

    def explicit_client(*args, **kwargs):
        configuration = kwargs["configuration"]
        assert configuration.host == target and configuration.proxy == proxy
        assert urlsplit(server).hostname == "127.0.0.1" and port is not None
        assert urlsplit(proxy).hostname == "127.0.0.1" and urlsplit(proxy).port is not None
        return _CLIENT(*args, **kwargs)

    monkeypatch.setattr(DefaultResolver, "resolve", resolve)
    monkeypatch.setattr(client, "ApiClient", explicit_client)
    return target


@pytest.mark.asyncio
@pytest.mark.parametrize("environment_proxy", [False, True])
async def test_original_dns_name_and_captured_environment_proxy_survive_socks_resolution(
    tmp_path, monkeypatch, owned_test_proxies, environment_proxy
):
    observed = []

    async def handler(request):
        observed.append(request.headers["Authorization"])
        return namespaces("team")

    tls, material = certificate(tmp_path, dns_name="owned-api.invalid")
    async with (
        fake_api(handler, tls=tls) as server,
        socks_proxy(server, aliases=("owned-api.invalid",)) as (proxy, witness),
    ):
        owned_test_proxies.add(proxy)
        target = owned_dns(monkeypatch, server, proxy)
        monkeypatch.setenv("HTTPS_PROXY", proxy)
        monkeypatch.setenv("NO_PROXY", "")
        cluster = {
            "certificate-authority-data": material["certificate-authority-data"],
            "tls-server-name": "",
        }
        if not environment_proxy:
            cluster["proxy-url"] = proxy
        session = KubernetesSession(
            catalog_fixture(tmp_path, target, cluster=cluster).select("kuberich-test-one"), 3
        )
        monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.1:1")
        try:
            await session.open()
            assert await session.namespaces() == ("team",)
            assert observed == ["Bearer synthetic"]
            assert witness.destinations == [("owned-api.invalid", urlsplit(server).port)]
            assert session.delegated_config()["clusters"][0]["cluster"]["proxy-url"] == proxy
        finally:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("encrypted_proxy", [False, True])
@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("authenticated", [False, True])
async def test_http_proxy_and_connect_use_distinct_api_and_proxy_credentials(
    tmp_path, owned_test_proxies, encrypted, authenticated, encrypted_proxy
):
    seen = []

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer selected-api-identity"
        assert "Proxy-Authorization" not in request.headers
        assert request.headers.getall("Impersonate-Group") == ["first", "second"]
        seen.append(True)
        return namespaces("team")

    tls, material = certificate(tmp_path, dns_name="owned-api.invalid")
    proxy_dir = tmp_path / "proxy-tls"
    proxy_dir.mkdir()
    proxy_tls, proxy_material = certificate(proxy_dir, common_name="owned-proxy")
    async with fake_api(handler, tls=tls if encrypted else None) as server:
        async with http_proxy(
            server,
            credentials=("proxy-user", "private-proxy-secret") if authenticated else None,
            tls=proxy_tls if encrypted_proxy else None,
        ) as (proxy, witness):
            owned_test_proxies.add(proxy)
            cluster = {
                "proxy-url": proxy,
                "certificate-authority-data": base64.b64encode(
                    base64.b64decode(material["certificate-authority-data"])
                    + base64.b64decode(proxy_material["certificate-authority-data"])
                ).decode(),
                **({"tls-server-name": "owned-api.invalid"} if encrypted else {}),
            }
            session = KubernetesSession(
                catalog_fixture(
                    tmp_path,
                    server,
                    {
                        "token": "selected-api-identity",
                        "as": "user",
                        "as-groups": ["first", "second"],
                    },
                    cluster,
                ).select("kuberich-test-one"),
                3,
            )
            try:
                await session.open()
                assert await session.namespaces() == ("team",)
                assert seen == [True]
                assert witness.requests == [
                    (
                        "CONNECT" if encrypted else "GET",
                        "Basic " + base64.b64encode(b"proxy-user:private-proxy-secret").decode()
                        if authenticated
                        else None,
                    )
                ]
            finally:
                await session.close()
        assert not witness.active


@pytest.mark.asyncio
@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("authenticated", [False, True])
async def test_socks_transport_preserves_tls_bearer_and_repeated_impersonation(
    tmp_path, owned_test_proxies, encrypted, authenticated
):
    observed = []

    async def handler(request):
        observed.append(
            (request.headers["Authorization"], request.headers.getall("Impersonate-Group"))
        )
        return namespaces("team")

    tls, material = certificate(tmp_path)
    cluster = (
        {"certificate-authority-data": material["certificate-authority-data"]} if encrypted else {}
    )
    async with fake_api(handler, tls=tls if encrypted else None) as server:
        async with socks_proxy(
            server, credentials=("proxy-user", "private-proxy-password") if authenticated else None
        ) as (proxy, witness):
            owned_test_proxies.add(proxy)
            cluster["proxy-url"] = proxy
            session = KubernetesSession(
                catalog_fixture(
                    tmp_path,
                    server,
                    {"token": "api-token", "as": "owned-user", "as-groups": ["one", "two"]},
                    cluster,
                ).select("kuberich-test-one"),
                3,
            )
            try:
                await session.open()
                assert session.request_proxy is None
                assert await session.namespaces() == ("team",)
                assert await session.namespaces() == ("team",)
                private = session.delegated_config()
                assert private["clusters"][0]["cluster"]["proxy-url"] == proxy
                assert private["users"][0]["user"]["as-groups"] == ["one", "two"]
                assert observed == [("Bearer api-token", ["one", "two"])] * 2
                assert witness.destinations == [("127.0.0.1", urlsplit(server).port)]
                assert witness.authentications == (
                    [(b"proxy-user", b"private-proxy-password")] if authenticated else []
                )
            finally:
                directory = Path(session.directory.name)
                await session.close()
            assert not directory.exists()
        assert not witness.active


@pytest.mark.asyncio
@pytest.mark.parametrize("proxy_enabled", [False, True])
@pytest.mark.parametrize("valid_name", [False, True])
async def test_tls_server_name_override_is_verified_even_through_socks(
    tmp_path, owned_test_proxies, proxy_enabled, valid_name
):
    called = []

    async def handler(request):
        called.append(True)
        return namespaces("team")

    tls, material = certificate(tmp_path, dns_name="owned-api.invalid")
    async with fake_api(handler, tls=tls) as server, socks_proxy(server) as (proxy, witness):
        cluster = {
            "certificate-authority-data": material["certificate-authority-data"],
            "tls-server-name": "owned-api.invalid" if valid_name else "incorrect.invalid",
        }
        if proxy_enabled:
            cluster["proxy-url"] = proxy
            owned_test_proxies.add(proxy)
        session = KubernetesSession(
            catalog_fixture(tmp_path, server, cluster=cluster).select("kuberich-test-one"), 3
        )
        try:
            await session.open()
            if valid_name:
                assert await session.namespaces() == ("team",)
                assert called == [True]
            else:
                with pytest.raises(ConnectionProblem) as error:
                    await session.namespaces()
                assert error.value.state is ConnectionState.TLS_ERROR
                assert not called
            assert bool(witness.destinations) is proxy_enabled
        finally:
            await session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,state",
    [
        ("reject", ConnectionState.UNREACHABLE),
        ("disconnect", ConnectionState.UNREACHABLE),
        ("hang", ConnectionState.TIMEOUT),
        ("wrong-password", ConnectionState.UNREACHABLE),
    ],
)
async def test_socks_failures_are_classified_without_proxy_credentials(
    tmp_path, owned_test_proxies, mode, state
):
    called = []

    async def handler(request):
        called.append(True)
        return namespaces("team")

    async with fake_api(handler) as server:
        async with socks_proxy(
            server, credentials=("user", "secret") if mode == "wrong-password" else None, mode=mode
        ) as (proxy, witness):
            if mode == "wrong-password":
                proxy = proxy.replace("user:secret@", "user:private-rejected-secret@")
            owned_test_proxies.add(proxy)
            session = KubernetesSession(
                catalog_fixture(tmp_path, server, cluster={"proxy-url": proxy}).select(
                    "kuberich-test-one"
                ),
                0.2,
            )
            try:
                await session.open()
                with pytest.raises(ConnectionProblem) as error:
                    await session.namespaces()
                assert error.value.state is state
                assert "secret" not in str(error.value) and "user" not in str(error.value)
                assert not called
            finally:
                await session.close()
        assert not witness.active
