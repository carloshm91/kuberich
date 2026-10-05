"""Owned full fake API for workspace, scope and live-view lifecycle trials."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from aiohttp import web

from tests.support.resources import collection, legacy_roots
from tests.support.watches import frame


async def wait_for(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.001)


async def stable_watch(request: web.Request, *values: dict) -> web.StreamResponse:
    response = web.StreamResponse()
    await response.prepare(request)
    for value in values:
        await response.write(frame(value))
    while request.transport is not None and not request.transport.is_closing():
        await asyncio.sleep(0.005)
    return response


@asynccontextmanager
async def workspace_api(
    namespace_handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    resource_handler: Callable[[web.Request], Awaitable[web.StreamResponse]] | None = None,
) -> AsyncIterator[str]:
    async def handler(request: web.Request) -> web.StreamResponse:
        if request.path == "/api/v1/namespaces" and "watch" not in request.query:
            return await namespace_handler(request)
        roots = legacy_roots()
        if request.path in roots:
            return web.json_response(roots[request.path])
        if resource_handler is not None:
            return await resource_handler(request)
        if "watch" not in request.query:
            return web.json_response(collection())
        response = web.StreamResponse()
        await response.prepare(request)
        while request.transport is not None and not request.transport.is_closing():
            await asyncio.sleep(0.01)
        return response

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    address = runner.addresses[0]
    try:
        yield f"http://127.0.0.1:{address[1]}"
    finally:
        await runner.cleanup()
