"""Owned workload and scale/history API fixtures with atomic conditional patches."""

import asyncio
import copy
from contextlib import asynccontextmanager

from aiohttp import web

from kubetrol.domain.resources import ApiResource
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from tests.support.standard import roots
from tests.support.workspace import stable_watch


def selection(family="deployments"):
    kind = {
        "deployments": "Deployment",
        "replicasets": "ReplicaSet",
        "statefulsets": "StatefulSet",
        "daemonsets": "DaemonSet",
    }[family]
    resource = ApiResource("apps", "v1", family, kind, True, frozenset({"get", "patch"}))
    target = ResourceTarget(
        SessionIdentity("kubetrol-test-one", 1), "apps", family, "team", "owned-one", "owned-uid"
    )
    value = {
        "apiVersion": "apps/v1",
        "kind": kind,
        "metadata": {
            "name": "owned-one",
            "namespace": "team",
            "uid": "owned-uid",
            "resourceVersion": "opaque-7",
            "generation": 2,
        },
        "spec": {
            "replicas": 2,
            "template": {
                "metadata": {"labels": {"app": "owned"}},
                "spec": {"containers": [{"name": "app", "image": "owned-image"}]},
            },
        },
        "status": {
            "observedGeneration": 2,
            "replicas": 2,
            "readyReplicas": 2,
            "updatedReplicas": 2,
            "availableReplicas": 2,
            "currentRevision": "rev",
            "updateRevision": "rev",
            "desiredNumberScheduled": 2,
            "updatedNumberScheduled": 2,
            "numberAvailable": 2,
            "currentNumberScheduled": 2,
        },
    }
    return resource, target, value


class WorkloadApi:
    def __init__(self, family="deployments"):
        self.resource, self.target, self.value = selection(family)
        self.value["spec"]["template"]["spec"]["containers"][0]["env"] = [
            {"name": "TOKEN", "value": "private-workload-value"}
        ]
        history = copy.deepcopy(self.value)
        history["apiVersion"], history["kind"] = "apps/v1", "ReplicaSet"
        history["metadata"].update(
            name="owned-old",
            uid="owned-history",
            resourceVersion="history-1",
            ownerReferences=[{"uid": self.target.uid, "controller": True}],
            annotations={"deployment.kubernetes.io/revision": "1"},
        )
        history["spec"]["template"]["spec"]["containers"][0]["image"] = "owned-old-image"
        if family != "deployments":
            history = {
                "apiVersion": "apps/v1",
                "kind": "ControllerRevision",
                "metadata": history["metadata"],
                "revision": 1,
                "data": {
                    "spec": {"template": {**history["spec"]["template"], "$patch": "replace"}}
                },
            }
        self.histories = [history]
        self.hpas = []
        self.hpa_status = None
        self.collections = {}
        self.read_status = None
        self.read_delay = 0
        self.patch_status = None
        self.stall = False
        self.drop = False
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.version = 7

    def scale(self):
        return {
            "apiVersion": "autoscaling/v1",
            "kind": "Scale",
            "metadata": copy.deepcopy(self.value["metadata"]),
            "spec": {"replicas": self.value["spec"]["replicas"]},
            "status": {"replicas": self.value["status"]["replicas"]},
        }

    async def handle(self, request):
        path = self.resource.path("team") + "/owned-one"
        if request.method == "PATCH":
            assert request.path in {path, path + "/scale"}
            body = await request.json()
            self.requests.append((request.path, dict(request.headers), dict(request.query), body))
            self.entered.set()
            if self.patch_status is not None:
                return web.Response(status=self.patch_status, text="private-server-error")
            value = copy.deepcopy(self.scale() if request.path.endswith("/scale") else self.value)
            for item in body:
                parts = [
                    p.replace("~1", "/").replace("~0", "~") for p in item["path"][1:].split("/")
                ]
                current = value
                for part in parts[:-1]:
                    current = current[part]
                if item["op"] == "test":
                    if current[parts[-1]] != item["value"]:
                        return web.Response(status=422)
                else:
                    current[parts[-1]] = item["value"]
            self.version += 1
            if request.path.endswith("/scale"):
                self.value["spec"]["replicas"] = value["spec"]["replicas"]
            else:
                self.value = value
            self.value["metadata"]["resourceVersion"] = f"opaque-{self.version}"
            self.value["metadata"]["generation"] += 1
            if self.drop:
                request.transport.abort()
                return web.Response()
            if self.stall:
                await self.release.wait()
            return web.json_response(
                self.scale() if request.path.endswith("/scale") else self.value
            )
        if request.path in {path, path + "/scale"}:
            if self.read_delay:
                await asyncio.sleep(self.read_delay)
            if self.read_status is not None:
                return web.Response(status=self.read_status, text="private-read-error")
            return web.json_response(
                self.scale() if request.path.endswith("/scale") else self.value
            )
        if "horizontalpodautoscalers" in request.path:
            status = (
                self.hpa_status.get(request.path.split("/")[3])
                if isinstance(self.hpa_status, dict)
                else self.hpa_status
            )
            if status is not None:
                return web.Response(status=status, text="private-hpa-error")
            return web.json_response({"metadata": {}, "items": self.hpas})
        family = "replicasets" if self.resource.name == "deployments" else "controllerrevisions"
        root = f"/apis/apps/v1/namespaces/team/{family}"
        if request.path == root:
            if root in self.collections:
                value = self.collections[root]
                return web.json_response(value(request) if callable(value) else value)
            return web.json_response({"metadata": {}, "items": self.histories})
        if request.path.startswith(root + "/"):
            for item in self.histories:
                if item["metadata"]["name"] == request.path.rsplit("/", 1)[1]:
                    return web.json_response(item)
            return web.Response(status=404)
        discovery = roots().get(request.path)
        if discovery is not None:
            if "resources" in discovery:
                for item in discovery["resources"]:
                    if item["name"] in {"deployments", "replicasets", "statefulsets", "daemonsets"}:
                        item["verbs"].append("patch")
            return web.json_response(discovery)
        if request.path == "/api/v1/namespaces":
            from tests.support.connections import namespaces

            return namespaces("team")
        if "watch" in request.query:
            return await stable_watch(request)
        items = [self.value] if request.path == self.resource.path("team") else []
        return web.json_response(
            {
                "apiVersion": "apps/v1",
                "kind": self.resource.kind + "List",
                "metadata": {"resourceVersion": "list-1"},
                "items": items,
            }
        )


@asynccontextmanager
async def workload_api(*, family="deployments", tls=None):
    fixture = WorkloadApi(family)
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{runner.addresses[0][1]}", fixture
    finally:
        fixture.release.set()
        await runner.cleanup()
