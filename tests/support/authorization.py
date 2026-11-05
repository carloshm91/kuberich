"""Owned loopback HTTP authorization fixtures, with no ambient Kubernetes context."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationRequest,
    AuthorizationScope,
    AuthorizationScopeKind,
    ResourceAccess,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import Discovery, api_resource
from kuberich.domain.targets import SessionIdentity
from kuberich.services.authorization import ACCESS_PATH, IDENTITY_PATH, RBAC_GROUP, RULES_PATH
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.workspace import stable_watch


def auth_resources() -> Discovery:
    return Discovery(
        tuple(
            api_resource(
                RBAC_GROUP + "/v1" if name != "serviceaccounts" else "v1",
                descriptor(name, namespaced=not name.startswith("cluster"), kind=kind),
            )
            for name, kind in (
                ("clusterroles", "ClusterRole"),
                ("clusterrolebindings", "ClusterRoleBinding"),
                ("roles", "Role"),
                ("rolebindings", "RoleBinding"),
                ("serviceaccounts", "ServiceAccount"),
            )
        )
    )


def auth_roots() -> dict:
    roots = legacy_roots()
    resources = auth_resources().resources
    roots["/api/v1"]["resources"].append(descriptor("serviceaccounts", kind="ServiceAccount"))
    roots["/apis"]["groups"] = [
        {
            "name": RBAC_GROUP,
            "versions": [{"groupVersion": RBAC_GROUP + "/v1", "version": "v1"}],
            "preferredVersion": {"groupVersion": RBAC_GROUP + "/v1", "version": "v1"},
        }
    ]
    roots["/apis/" + RBAC_GROUP + "/v1"] = {
        "groupVersion": RBAC_GROUP + "/v1",
        "resources": [
            descriptor(resource.name, kind=resource.kind, namespaced=resource.namespaced)
            for resource in resources
            if resource.group
        ],
    }
    return roots


def auth_scope(namespace: str | None = "team") -> AuthorizationScope:
    return AuthorizationScope(
        AuthorizationScopeKind.NAMESPACE
        if namespace is not None
        else AuthorizationScopeKind.ALL_NAMESPACES,
        namespace,
    )


def auth_request(
    mode=AuthorizationMode.REVIEW, *, namespace="team", access=None, **kwargs
) -> AuthorizationRequest:
    scope = auth_scope(namespace)
    if mode in {AuthorizationMode.REVIEW, AuthorizationMode.WHO_CAN}:
        access = access or ResourceAccess(
            "list", "", "v1", "pods", None, None, scope, ResourceQuery()
        )
        scope = (
            access.scope
            if isinstance(access, ResourceAccess)
            else AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
        )
    return AuthorizationRequest(
        SessionIdentity("kuberich-test-one", 1),
        1,
        AuthorizationIntent(mode, scope, access=access, **kwargs),
    )


def rbac_object(kind="Role", name="reader", namespace="team", *, uid=None, **fields) -> dict:
    metadata = {"name": name, "uid": uid or "uid-" + name, "resourceVersion": "rv-" + name}
    if namespace is not None:
        metadata["namespace"] = namespace
    return {"apiVersion": RBAC_GROUP + "/v1", "kind": kind, "metadata": metadata, **fields}


def policy_rule(**kwargs) -> dict:
    return {"verbs": ["list", "get"], "apiGroups": [""], "resources": ["pods"], **kwargs}


class AuthorizationApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, object]] = []
        self.values: dict[str, list[dict]] = {}
        self.denied: set[str] = set()
        self.status = {
            ACCESS_PATH: {"allowed": True},
            IDENTITY_PATH: {
                "userInfo": {
                    "username": "fixture-user",
                    "uid": "identity-uid",
                    "groups": ["fixture-group"],
                }
            },
            RULES_PATH: {
                "resourceRules": [policy_rule()],
                "nonResourceRules": [],
                "incomplete": False,
            },
        }
        self.held_path: str | None = None
        self.held = asyncio.Event()
        self.release = asyncio.Event()
        self.watchers = 0

    async def __call__(self, request: web.Request) -> web.StreamResponse:
        body = await request.json() if request.method == "POST" else None
        self.calls.append((request.method, request.path, dict(request.query), body))
        if request.path == self.held_path:
            self.held.set()
            await self.release.wait()
        if request.path in self.denied:
            return web.json_response(
                {"message": "PRIVATE server detail Bearer fixture-token"}, status=403
            )
        if request.path in self.status:
            assert request.method == "POST"
            return web.json_response(
                {
                    "apiVersion": body["apiVersion"],
                    "kind": body["kind"],
                    "status": self.status[request.path],
                },
                status=201,
            )
        if request.path in auth_roots():
            return web.json_response(auth_roots()[request.path])
        if request.path == "/api/v1/namespaces" and "watch" not in request.query:
            return namespaces("team", "other", "default")
        if "watch" in request.query:
            self.watchers += 1
            try:
                return await stable_watch(request)
            finally:
                self.watchers -= 1
        values = self.values.get(request.path)
        if values is not None:
            return web.json_response(
                {
                    **collection(*values),
                    "apiVersion": RBAC_GROUP + "/v1" if request.path.startswith("/apis/") else "v1",
                }
            )
        for values in self.values.values():
            for value in values:
                if request.path.endswith("/" + value["metadata"]["name"]):
                    return web.json_response(value)
        if request.path.rsplit("/", 1)[-1] in {
            "clusterroles",
            "clusterrolebindings",
            "roles",
            "rolebindings",
            "serviceaccounts",
            "pods",
        }:
            return web.json_response(
                {
                    **collection(),
                    "apiVersion": RBAC_GROUP + "/v1" if request.path.startswith("/apis/") else "v1",
                }
            )
        return web.json_response({"message": "PRIVATE absent object"}, status=404)


@asynccontextmanager
async def authorization_api(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    tls=None,
) -> AsyncIterator[str]:
    app = web.Application()

    async def dispatch(request):
        return await handler(request)

    app.router.add_route("*", "/{path:.*}", dispatch)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()


@asynccontextmanager
async def authorization_session(
    directory: Path,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    user=None,
    timeout=2,
) -> AsyncIterator[KubernetesSession]:
    async with authorization_api(handler) as url:
        session = KubernetesSession(
            catalog_fixture(directory, url, user).select("kuberich-test-one"), timeout
        )
        try:
            await session.open()
            yield session
        finally:
            await session.close()
