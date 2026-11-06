"""Explicit synthetic matrices and owned HTTP listeners for history contracts."""

import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.domain.resources import Discovery, api_resource
from tests.support.resources import descriptor


def history_discovery() -> Discovery:
    return Discovery(
        tuple(
            api_resource("v1", descriptor(name, kind=kind))
            for name, kind in (
                ("services", "Service"),
                ("pods", "Pod"),
            )
        )
    )


def matrix(parameters: Mapping[str, str], *, value: str = "1", labels: dict | None = None) -> dict:
    """One explicitly synthetic complete matrix; no claim of native availability."""
    start, end = int(float(parameters["start"])), int(float(parameters["end"]))
    step = int(parameters["step"])
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": labels or {},
                    "values": [[at, value] for at in range(start, end + 1, step)],
                }
            ],
        },
    }


def service(name: str = "metrics", uid: str = "service-owned", namespace: str = "team") -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "uid": uid,
            "resourceVersion": "owned-v1",
            "labels": {"app.kubernetes.io/name": "prometheus"},
        },
        "spec": {"ports": [{"name": "http-query", "port": 9090}]},
    }


@asynccontextmanager
async def history_http(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    tls: ssl.SSLContext | None = None,
) -> AsyncIterator[str]:
    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    address = runner.addresses[0]
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{address[1]}"
    finally:
        await runner.cleanup()
