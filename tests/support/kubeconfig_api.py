"""Owned kubeconfig API transport with exact path and authentication capture."""

from contextlib import asynccontextmanager

from aiohttp import web

from tests.support.connections import namespaces


@asynccontextmanager
async def captured_api(tls=None, *, status=200, prefix=""):
    calls = []

    async def handler(request):
        assert request.path == prefix + "/api/v1/namespaces"
        calls.append(
            (
                request.method,
                request.headers.get("Authorization"),
                request.headers.get("Accept-Encoding"),
            )
        )
        if status != 200:
            return web.Response(status=status, text="private-server-body")
        return namespaces("team") if request.method == "GET" else web.json_response({"ok": True})

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{runner.addresses[0][1]}", calls
    finally:
        await runner.cleanup()
