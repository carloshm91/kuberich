"""Owned proxy fixture bounds include the pinned CLI's validation schema routes."""

import asyncio

import aiohttp
import pytest
import yaml
from aiohttp import web

from kuberich.errors import AppError
from scripts.helm_lifecycle_fault_cases import bounded_body, held_owned_write, owned_api_path
from scripts.owned_kind import OwnedCluster
from tests.support.connections import certificate


@pytest.mark.parametrize(
    "path",
    [
        "/api",
        "/api/v1",
        "/apis/apps/v1",
        "/version",
        "/openapi/v2",
        "/openapi/v3",
        "/openapi/v3/api/v1",
    ],
)
def test_owned_proxy_serves_bounded_api_and_pinned_openapi_routes(path):
    assert owned_api_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/metrics",
        "/openapi/v4",
        "/openapi/v3-foreign",
        "https://foreign.invalid/api",
        "//foreign.invalid/api",
    ],
)
def test_owned_proxy_never_becomes_a_general_destination_proxy(path):
    assert not owned_api_path(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [100_000, 99_999])
async def test_proxy_retains_complete_delayed_chunks_and_refuses_cumulative_overflow(limit):
    payload = b"x" * 100_000

    async def stream(request):
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(payload[:40_000])
        await asyncio.sleep(0.01)
        await response.write(payload[40_000:])
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/openapi/v3/api/v1", stream)
    listener = web.AppRunner(app)
    await listener.setup()
    site = web.TCPSite(listener, "127.0.0.1", 0)
    await site.start()
    try:
        async with (
            aiohttp.ClientSession(trust_env=False, cookie_jar=aiohttp.DummyCookieJar()) as client,
            client.get(
                f"http://127.0.0.1:{listener.addresses[0][1]}/openapi/v3/api/v1?hash=owned"
            ) as response,
        ):
            if limit == len(payload):
                assert await bounded_body(response.content, limit) == payload
            else:
                with pytest.raises(AssertionError, match="fixture limit"):
                    await bounded_body(response.content, limit)
    finally:
        await listener.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_proxy_closure_witness_survives_caller_failure_after_actual_owner_cleanup(
    tmp_path, fail
):
    _, material = certificate(tmp_path)
    path = tmp_path / "owned-kubeconfig"
    path.write_text(
        yaml.safe_dump(
            {
                "current-context": "owned",
                "contexts": [{"name": "owned", "context": {"cluster": "owned", "user": "owned"}}],
                "clusters": [
                    {
                        "name": "owned",
                        "cluster": {
                            "server": "https://127.0.0.1:1",
                            "certificate-authority-data": material["certificate-authority-data"],
                        },
                    }
                ],
                "users": [
                    {
                        "name": "owned",
                        "user": {
                            key: material[key]
                            for key in ("client-certificate-data", "client-key-data")
                        },
                    }
                ],
            }
        )
    )
    path.chmod(0o600)
    cluster = OwnedCluster("kuberich-test-owned-unit", path, tmp_path, "owned", ())
    try:
        async with held_owned_write(cluster, "owned", "owned") as (origin, witness):
            assert not witness.closed
            if fail:
                raise AppError("Original owned proof failure.")
    except AppError as error:
        assert fail and str(error) == "Original owned proof failure."
    else:
        assert not fail
    assert witness.closed and not witness.active and not witness.persistent_writes
    async with aiohttp.ClientSession(trust_env=False) as client:
        with pytest.raises(aiohttp.ClientConnectorError):
            await client.get(origin + "/version")
