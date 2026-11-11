"""Owned proxy fixture bounds include the pinned CLI's validation schema routes."""

import asyncio

import aiohttp
import pytest
from aiohttp import web

from scripts.helm_lifecycle_fault_cases import bounded_body, owned_api_path


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
