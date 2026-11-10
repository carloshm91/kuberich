"""Task-owned HTTP Node maintenance API; never selects an ambient cluster."""

import asyncio
import copy
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.node_maintenance import NodeMaintenanceService
from tests.support.connections import catalog_fixture

NODE = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list", "patch"}))
POD = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
PDB = ApiResource(
    "policy", "v1", "poddisruptionbudgets", "PodDisruptionBudget", True, frozenset({"get", "list"})
)
RS = ApiResource("apps", "v1", "replicasets", "ReplicaSet", True, frozenset({"get", "list"}))
DS = ApiResource("apps", "v1", "daemonsets", "DaemonSet", True, frozenset({"get", "list"}))
PVC = ApiResource(
    "", "v1", "persistentvolumeclaims", "PersistentVolumeClaim", True, frozenset({"get", "list"})
)
PV = ApiResource(
    "", "v1", "persistentvolumes", "PersistentVolume", False, frozenset({"get", "list"})
)
DISCOVERY = Discovery((NODE, POD, PDB, RS, DS, PVC, PV))


def pod(name="one", *, managed=True, emptydir=False, daemonset=False, mirror=False):
    value = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": "team",
            "uid": "pod-" + name,
            "resourceVersion": "opaque/pod-" + name,
            "labels": {"app": "test"},
        },
        "spec": {"nodeName": "node-one", "containers": [{"name": "main", "image": "synthetic"}]},
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
    }
    if managed:
        value["metadata"]["ownerReferences"] = [
            {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet" if daemonset else "ReplicaSet",
                "name": "owner",
                "uid": "owner-uid",
                "controller": True,
            }
        ]
    if emptydir:
        value["spec"]["volumes"] = [{"name": "scratch", "emptyDir": {"medium": "Memory"}}]
    if mirror:
        value["metadata"]["annotations"] = {"kubernetes.io/config.mirror": "synthetic"}
    return value


class MaintenanceApi:
    def __init__(self):
        self.node = {
            "apiVersion": "v1",
            "kind": "Node",
            "metadata": {"name": "node-one", "uid": "node-uid", "resourceVersion": "opaque/node"},
            "spec": {},
        }
        self.pods = [pod()]
        self.pdbs = []
        self.pdbs_by_namespace = {}
        self.requests = []
        self.reads = []
        self.statuses = {}
        self.retry_after = "1"
        self.retry_seconds = None
        self.delete_accepted = True
        self.post_mode = "normal"
        self.success_status = 200
        self.receipt_override = None
        self.patch_mode = "normal"
        self.patch_status = None
        self.read_status = None
        self.pod_read_status = None
        self.node_mode = "normal"
        self.owner_status = None
        self.owner_uid = "owner-uid"
        self.owner_version = "owner-version"
        self.pvc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": "claim",
                "namespace": "team",
                "uid": "claim-uid",
                "resourceVersion": "claim-rv",
            },
            "spec": {"volumeName": "disk"},
        }
        self.pv = {
            "apiVersion": "v1",
            "kind": "PersistentVolume",
            "metadata": {"name": "disk", "uid": "disk-uid", "resourceVersion": "disk-rv"},
            "spec": {
                "claimRef": {"name": "claim", "namespace": "team", "uid": "claim-uid"},
                "local": {"path": "/private-host-value"},
                "nodeAffinity": {},
            },
        }
        self.storage_status = None
        self.pdb_status = None
        self.list_mode = "normal"
        self.eviction_supported = True
        self.discovery_body = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.before_patch = None
        self.after_post = None
        self.after_read = None
        self.block_node_after_patch = False
        self.node_entered = asyncio.Event()
        self.node_release = asyncio.Event()

    async def handle(self, request):
        path = request.path
        if request.method == "PATCH":
            body = await request.json()
            self.requests.append(("PATCH", path, body, dict(request.headers)))
            if self.before_patch:
                self.before_patch(self)
            if self.patch_status:
                return web.json_response({"private": "error"}, status=self.patch_status)
            if any(self.node["metadata"][o["path"].split("/")[-1]] != o["value"] for o in body[:2]):
                return web.json_response({}, status=422)
            self.node["spec"]["unschedulable"] = body[2]["value"]
            self.node["metadata"]["resourceVersion"] = "opaque/node-after"
            if self.patch_mode == "drop":
                request.transport.abort()
                return web.Response()
            value = copy.deepcopy(self.node)
            if self.patch_mode == "wrong-state":
                value["spec"]["unschedulable"] = not value["spec"]["unschedulable"]
            if self.patch_mode == "missing-kind":
                value.pop("kind")
            return web.json_response(value)
        if request.method == "POST":
            body = await request.json()
            self.requests.append(("POST", path, body, dict(request.headers)))
            self.entered.set()
            name = path.split("/")[-2]
            statuses = self.statuses.get(name, [])
            status = statuses.pop(0) if statuses else 200
            if status != 200:
                if self.post_mode == "bad-refusal":
                    return web.Response(
                        status=status,
                        text="private-invalid-status",
                        headers={"Retry-After": self.retry_after},
                    )
                return web.json_response(
                    {
                        "apiVersion": "v1",
                        "kind": "Status",
                        "status": "Failure",
                        "details": {"retryAfterSeconds": self.retry_seconds},
                    },
                    status=status,
                    headers={"Retry-After": self.retry_after},
                )
            found = next((p for p in self.pods if p["metadata"]["name"] == name), None)
            expected = body["deleteOptions"]["preconditions"]
            if found is not None and any(found["metadata"][k] != v for k, v in expected.items()):
                return web.json_response({}, status=409)
            if self.delete_accepted:
                self.pods = [p for p in self.pods if p is not found]
            if self.after_post:
                self.after_post(self, name)
            if self.post_mode == "drop":
                request.transport.abort()
                return web.Response()
            if self.post_mode == "stall":
                await self.release.wait()
            if self.post_mode == "bad-json":
                return web.Response(text="private-invalid")
            if self.post_mode == "bad-receipt":
                return web.json_response({"status": "Success"})
            return web.json_response(
                self.receipt_override
                if self.receipt_override is not None
                else {
                    "apiVersion": "v1",
                    "kind": "Status",
                    "status": "Success",
                    "code": self.success_status,
                },
                status=self.success_status,
            )
        self.reads.append((path, dict(request.query)))
        if self.after_read:
            self.after_read(self, path)
        if path == "/api/v1/nodes/node-one":
            if self.node_mode == "bad-json":
                return web.Response(text="private-invalid")
            if self.block_node_after_patch and any(r[0] == "PATCH" for r in self.requests):
                self.node_entered.set()
                await self.node_release.wait()
            return web.json_response(
                self.node if self.read_status is None else {}, status=self.read_status or 200
            )
        if path == "/api/v1":
            if self.discovery_body is not None:
                return web.json_response(self.discovery_body)
            return web.json_response(
                {
                    "resources": [
                        {
                            "name": "pods/eviction",
                            "kind": "Eviction",
                            "namespaced": True,
                            "group": "policy",
                            "version": "v1",
                            "verbs": ["create"],
                        }
                    ]
                    if self.eviction_supported
                    else []
                }
            )
        if path == "/api/v1/pods":
            items = copy.deepcopy(self.pods)
            if self.list_mode == "duplicate":
                items *= 2
            if self.list_mode == "wrong-node" and items:
                items[0]["spec"]["nodeName"] = "wrong"
            return web.json_response(
                {
                    "kind": "PodList",
                    "apiVersion": "v1",
                    "metadata": {"resourceVersion": "list-version"},
                    "items": items,
                }
            )
        if path.startswith("/api/v1/namespaces/") and "/pods/" in path:
            if self.pod_read_status is not None:
                return web.json_response({}, status=self.pod_read_status)
            found = next(
                (p for p in self.pods if p["metadata"]["name"] == path.split("/")[-1]), None
            )
            return web.json_response(found or {}, status=200 if found else 404)
        if path.endswith("/poddisruptionbudgets"):
            return web.json_response(
                {
                    "apiVersion": "policy/v1",
                    "kind": "PodDisruptionBudgetList",
                    "metadata": {"resourceVersion": "pdb-list"},
                    "items": self.pdbs_by_namespace.get(path.split("/")[-2], self.pdbs),
                },
                status=self.pdb_status or 200,
            )
        if path == "/api/v1/namespaces/team/persistentvolumeclaims/claim":
            return web.json_response(self.pvc, status=self.storage_status or 200)
        if path == "/api/v1/persistentvolumes/disk":
            return web.json_response(self.pv, status=self.storage_status or 200)
        if "/replicasets/" in path or "/daemonsets/" in path:
            return web.json_response(
                {
                    "apiVersion": "apps/v1",
                    "kind": "DaemonSet" if "/daemonsets/" in path else "ReplicaSet",
                    "metadata": {
                        "name": "owner",
                        "namespace": path.split("/")[-3],
                        "uid": self.owner_uid,
                        "resourceVersion": self.owner_version,
                    },
                },
                status=self.owner_status or 200,
            )
        return web.json_response({}, status=404)


@asynccontextmanager
async def maintenance_api():
    fixture = MaintenanceApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}", fixture
    finally:
        fixture.release.set()
        fixture.node_release.set()
        await runner.cleanup()


@asynccontextmanager
async def maintenance_source(tmp_path, *, timeout=2, read_only=False, **kwargs):
    async with maintenance_api() as (url, api):
        client = KubernetesSession(
            catalog_fixture(tmp_path, url).select("kuberich-test-one"), timeout
        )
        await client.open()
        current = [True]
        target = ResourceTarget(
            SessionIdentity("kuberich-test-one", 1), "", "nodes", None, "node-one", "node-uid"
        )
        source = NodeMaintenanceService(
            client, NODE, target, DISCOVERY, AccessPolicy(read_only), lambda: current[0], **kwargs
        )
        try:
            yield source, api, current
        finally:
            await source.close()
            await client.close()
