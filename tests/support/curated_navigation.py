"""Owned loopback API with an all-method ledger for explicit navigation contracts."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.curated_navigation import CuratedLink, ReferenceDestination
from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.services.curated_navigation import CuratedOrigin
from tests.support.connections import catalog_fixture

SOURCE = ApiResource(
    "autoscaling",
    "v2",
    "horizontalpodautoscalers",
    "HorizontalPodAutoscaler",
    True,
    frozenset({"get", "list", "watch"}),
)
TARGET = ApiResource(
    "apps", "v1", "deployments", "Deployment", True, frozenset({"get", "list", "watch"})
)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))
NODES = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list", "watch"}))
ROOT = ApiResource(
    "node.k8s.io",
    "v1",
    "runtimeclasses",
    "RuntimeClass",
    False,
    frozenset({"get", "list", "watch"}),
)


def payload(
    resource: ApiResource,
    name: str,
    *,
    uid: str = "target-uid",
    namespace: str | None = "team",
    rv: str = "target-rv",
) -> dict[str, Any]:
    return {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "metadata": {
            "name": name,
            "uid": uid,
            "resourceVersion": rv,
            **({"namespace": namespace} if resource.namespaced else {}),
        },
    }


def path(resource: ApiResource, name: str, namespace: str | None = "team") -> str:
    return resource.path(namespace if resource.namespaced else None) + "/" + name


def reference(
    *,
    resource: ApiResource = TARGET,
    uid: str | None = None,
    namespace: str | None = "team",
    name: str = "owned-target",
    require_uid: bool = False,
) -> CuratedLink:
    return CuratedLink(
        "target",
        "Declared target",
        "Declared reference",
        ReferenceDestination(
            RelationshipRef(resource.api_version, resource.kind, namespace, name, uid, None),
            require_uid,
        ),
    )


type Response = (
    dict[str, Any] | web.StreamResponse | Callable[[web.Request], Awaitable[web.StreamResponse]]
)


@dataclass
class OwnedAPI:
    resources: tuple[ApiResource, ...] = (SOURCE, TARGET, PODS, NODES, ROOT)
    responses: dict[str, Response] = field(default_factory=dict)
    ledger: list[tuple[str, str, tuple[tuple[str, str], ...]]] = field(default_factory=list)

    @property
    def discovery(self) -> Discovery:
        return Discovery(self.resources)

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.ledger.append((request.method, request.path, tuple(sorted(request.query.items()))))
        value = self.responses.get(request.path)
        if callable(value):
            return await value(request)
        if isinstance(value, web.StreamResponse):
            return value
        return (
            web.json_response(value)
            if value is not None
            else web.Response(status=404, text="synthetic-response-canary")
        )

    def origin(self, client: KubernetesSession, *, resource: ApiResource = SOURCE) -> CuratedOrigin:
        namespace = "team" if resource.namespaced else None
        value = CuratedOrigin(
            SessionIdentity(client.context.name, 7),
            11,
            resource,
            "owned-source",
            "source-uid",
            namespace,
            "source-rv",
        )
        self.responses[path(resource, value.record_name, namespace)] = payload(
            resource, value.record_name, uid=value.record_uid, namespace=namespace, rv="source-rv"
        )
        return value


@asynccontextmanager
async def navigation_fixture(directory: Path) -> AsyncIterator[tuple[KubernetesSession, OwnedAPI]]:
    api = OwnedAPI()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", api.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    address = runner.addresses[0]
    client = KubernetesSession(
        catalog_fixture(directory, f"http://127.0.0.1:{address[1]}").select("kuberich-test-one"), 2
    )
    try:
        await client.open()
        yield client, api
    finally:
        await client.close()
        await runner.cleanup()
