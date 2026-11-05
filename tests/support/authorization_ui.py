"""Owned loopback authorization API with distinct reviews, declarations and UID races."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy

from aiohttp import web

from tests.support.connections import namespaces
from tests.support.pods import pod
from tests.support.relationships import descriptor, manifest
from tests.support.resources import descriptor as discovered
from tests.support.workspace import stable_watch

GROUP = "rbac.authorization.k8s.io"
ROLES = descriptor("roles", "Role", GROUP, verbs=("get", "list", "watch"))
BINDINGS = descriptor("rolebindings", "RoleBinding", GROUP, verbs=("get", "list", "watch"))
CLUSTER_ROLES = descriptor(
    "clusterroles", "ClusterRole", GROUP, namespaced=False, verbs=("get", "list", "watch")
)
CLUSTER_BINDINGS = descriptor(
    "clusterrolebindings",
    "ClusterRoleBinding",
    GROUP,
    namespaced=False,
    verbs=("get", "list", "watch"),
)
PODS = descriptor(verbs=("get", "list", "watch"))
ACCOUNTS = descriptor("serviceaccounts", "ServiceAccount", verbs=("get", "list", "watch"))
RULE = {
    "verbs": ["get", "list"],
    "apiGroups": [""],
    "resources": ["pods"],
    "resourceNames": ["example"],
}


class AuthorizationAPI:
    def __init__(self):
        self.reads = []
        self.reviews = []
        self.objects = {}
        self.forbidden = set()
        self.list_replacements = {}
        self.allowed, self.denied = True, False
        self.review_status = 201
        self.reason = "Server reviewed the exact request"
        self.hold_path = None
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self.active_watches = 0
        for namespace in ("team", "default", "other"):
            self.objects[("", "pods", namespace, "example")] = pod("example", namespace=namespace)
            self.add(ACCOUNTS, "runner", namespace=namespace)
            self.add(ROLES, "reader", namespace=namespace, rules=[RULE])
            self.add(
                BINDINGS,
                "readers",
                namespace=namespace,
                roleRef={"apiGroup": GROUP, "kind": "Role", "name": "reader"},
                subjects=[
                    {"kind": "User", "apiGroup": GROUP, "name": "Alice"},
                    {"kind": "Group", "apiGroup": GROUP, "name": "Operators"},
                    {"kind": "ServiceAccount", "name": "runner"},
                ],
            )
        self.add(
            CLUSTER_ROLES,
            "aggregate",
            rules=[RULE],
            aggregationRule={"clusterRoleSelectors": [{"matchLabels": {"demo": "true"}}]},
        )
        self.add(
            CLUSTER_ROLES,
            "contributor",
            rules=[{"verbs": ["get"], "apiGroups": [""], "resources": ["pods/log"]}],
            metadata={"labels": {"demo": "true"}},
        )
        self.add(
            CLUSTER_BINDINGS,
            "cluster-readers",
            roleRef={"apiGroup": GROUP, "kind": "ClusterRole", "name": "aggregate"},
            subjects=[{"kind": "Group", "apiGroup": GROUP, "name": "Operators"}],
        )

    def add(self, resource, name, *, namespace=None, **fields):
        actual_namespace = namespace if resource.namespaced else None
        self.objects[(resource.group, resource.name, actual_namespace, name)] = manifest(
            resource,
            name=name,
            namespace=actual_namespace,
            uid=f"{resource.name}-{actual_namespace or 'cluster'}-{name}",
            **fields,
        )

    def roots(self):
        core = (PODS, ACCOUNTS)
        rbac = (ROLES, BINDINGS, CLUSTER_ROLES, CLUSTER_BINDINGS)
        return {
            "/api": {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]},
            "/apis": {
                "kind": "APIGroupList",
                "apiVersion": "v1",
                "groups": [
                    {
                        "name": GROUP,
                        "versions": [{"groupVersion": GROUP + "/v1", "version": "v1"}],
                        "preferredVersion": {"groupVersion": GROUP + "/v1", "version": "v1"},
                    }
                ],
            },
            "/api/v1": {
                "kind": "APIResourceList",
                "groupVersion": "v1",
                "resources": [
                    *(
                        discovered(
                            resource.name, kind=resource.kind, namespaced=resource.namespaced
                        )
                        for resource in core
                    ),
                    discovered("namespaces", kind="Namespace", namespaced=False),
                ],
            },
            "/apis/" + GROUP + "/v1": {
                "kind": "APIResourceList",
                "groupVersion": GROUP + "/v1",
                "resources": [
                    discovered(resource.name, kind=resource.kind, namespaced=resource.namespaced)
                    for resource in rbac
                ],
            },
        }

    async def handler(self, request):
        if request.path == self.hold_path:
            self.started.set()
            await self.release.wait()
        if request.method == "POST":
            body = await request.json()
            self.reviews.append((request.path, body))
            if request.path.endswith("/selfsubjectreviews"):
                status = {
                    "userInfo": {
                        "username": "Alice",
                        "uid": "identity-uid",
                        "groups": ["Operators"],
                    }
                }
            elif request.path.endswith("/selfsubjectrulesreviews"):
                status = {
                    "resourceRules": [RULE],
                    "nonResourceRules": [{"verbs": ["get"], "nonResourceURLs": ["/healthz"]}],
                    "incomplete": True,
                    "evaluationError": "Synthetic partial rule evidence",
                }
            else:
                if self.review_status == 403:
                    return web.Response(status=403)
                status = {
                    "allowed": self.allowed,
                    "denied": self.denied,
                    "reason": self.reason,
                    "evaluationError": "Synthetic evaluation warning",
                }
            return web.json_response(
                {"apiVersion": body["apiVersion"], "kind": body["kind"], "status": status},
                status=201,
            )
        self.reads.append((request.path, dict(request.query)))
        if request.path in self.roots():
            return web.json_response(self.roots()[request.path])
        if "watch" in request.query:
            self.active_watches += 1
            try:
                return await stable_watch(request)
            finally:
                self.active_watches -= 1
        if request.path == "/api/v1/namespaces":
            return namespaces("team", "default", "other")
        parts = request.path.strip("/").split("/")
        group, tail = ("", parts[2:]) if parts[0] == "api" else (parts[1], parts[3:])
        namespace = None
        if len(tail) > 2 and tail[0] == "namespaces":
            namespace, tail = tail[1], tail[2:]
        plural = tail[0]
        if plural in self.forbidden and len(tail) == 1:
            return web.Response(status=403)
        if len(tail) == 2:
            value = self.objects.get((group, plural, namespace, tail[1]))
            return web.json_response(value) if value is not None else web.Response(status=404)
        values = []
        for key, value in self.objects.items():
            if key[:2] != (group, plural) or (namespace is not None and key[2] != namespace):
                continue
            value = deepcopy(value)
            if key in self.list_replacements:
                value["metadata"]["uid"] = self.list_replacements[key]
            values.append(value)
        return web.json_response(
            {"metadata": {"resourceVersion": "synthetic-list"}, "items": values}
        )


@asynccontextmanager
async def authorization_api(api: AuthorizationAPI) -> AsyncIterator[str]:
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", api.handler)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        api.release.set()
        await runner.cleanup()
