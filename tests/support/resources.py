"""Owned discovery/resource HTTP fixtures with Kubernetes-shaped responses."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import web

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.resources import ApiResource, api_resource
from kubetrol.services.resources import ResourceReader
from tests.support.connections import catalog_fixture


def descriptor(name: str = "pods", *, namespaced: bool = True, kind: str = "Pod") -> dict:
    return {
        "name": name,
        "kind": kind,
        "namespaced": namespaced,
        "verbs": ["get", "list", "watch"],
        "singularName": "pod" if name == "pods" else "",
        "shortNames": ["po"] if name == "pods" else [],
    }


def pod_resource() -> ApiResource:
    return api_resource("v1", descriptor())


def item(name: str = "one", *, namespace: str | None = "team", uid: str | None = None) -> dict:
    metadata = {"name": name, "uid": uid or f"owned-{name}", "resourceVersion": "opaque/object"}
    if namespace is not None:
        metadata["namespace"] = namespace
    return {"metadata": metadata, "spec": {"containers": [{"name": "app", "image": "synthetic"}]}}


def collection(*items: dict, rv: str | None = "opaque/snapshot", token: str = "") -> dict:
    metadata = {"continue": token}
    if rv is not None:
        metadata["resourceVersion"] = rv
    return {"apiVersion": "v1", "kind": "PodList", "metadata": metadata, "items": list(items)}


def legacy_roots() -> dict[str, dict]:
    return {
        "/api": {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]},
        "/apis": {"kind": "APIGroupList", "apiVersion": "v1", "groups": []},
        "/api/v1": {
            "kind": "APIResourceList",
            "groupVersion": "v1",
            "resources": [
                descriptor(),
                descriptor("namespaces", namespaced=False, kind="Namespace"),
                {**descriptor(), "name": "pods/log"},
            ],
        },
    }


def aggregated_resource(name: str = "pods", *, scope: str = "Namespaced") -> dict:
    return {
        "resource": name,
        "scope": scope,
        "responseKind": {"group": "", "version": "v1", "kind": "Pod"},
        "verbs": ["get", "list", "watch"],
        "singularResource": "pod",
        "shortNames": ["po"],
    }


def aggregated_group(name: str = "", version: str = "v1", *, freshness: str = "Current") -> dict:
    return {
        "metadata": {"name": name},
        "versions": [
            {"version": version, "freshness": freshness, "resources": [aggregated_resource()]}
        ],
    }


def aggregated(*groups: dict) -> dict:
    return {
        "apiVersion": "apidiscovery.k8s.io/v2",
        "kind": "APIGroupDiscoveryList",
        "items": list(groups),
    }


@asynccontextmanager
async def reader_fixture(
    directory: Path,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    timeout: float = 5,
    user: dict | None = None,
) -> AsyncIterator[ResourceReader]:
    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    address = runner.addresses[0]
    session = KubernetesSession(
        catalog_fixture(directory, f"http://127.0.0.1:{address[1]}", user).select(
            "kubetrol-test-one"
        ),
        timeout,
    )
    try:
        await session.open()
        yield ResourceReader(session)
    finally:
        await session.close()
        await runner.cleanup()
