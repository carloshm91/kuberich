"""Owned loopback API for irreversible debug service lifecycle contracts."""

import asyncio
import copy
import os
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.ephemeral_debug import EphemeralDebugOptions
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.ephemeral_debug import EphemeralDebugService
from tests.support.connections import catalog_fixture

PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}))
OPTIONS = EphemeralDebugOptions(
    "debug-one", "example.test/debug@sha256:" + "a" * 64, ("/bin/sh",), "main"
)


class DebugApi:
    def __init__(self):
        self.pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": "api",
                "namespace": "team",
                "uid": "pod-uid",
                "resourceVersion": "opaque-before",
            },
            "spec": {"containers": [{"name": "main", "image": "synthetic"}]},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {
                        "name": "main",
                        "containerID": "runtime://main",
                        "restartCount": 0,
                        "state": {"running": {"startedAt": "2026-01-01T00:00:00Z"}},
                    }
                ],
            },
        }
        self.requests = []
        self.reads = []
        self.mode = "normal"
        self.status = None
        self.read_status = None
        self.discovery = True
        self.running = True
        self.wait_reason = "ContainerCreating"
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.read_entered = asyncio.Event()
        self.read_release = asyncio.Event()
        self.block_read = False
        self.after_get = None
        self.active_reads = 0
        self.maximum_reads = 0

    async def handle(self, request):
        if request.method == "PATCH":
            body = await request.json()
            dry = request.query.get("dryRun") == "All"
            self.requests.append(
                (request.method, request.path, dict(request.query), body, dict(request.headers))
            )
            if self.status and not dry:
                return web.json_response({"private": "server-secret"}, status=self.status)
            if self.mode == "dry-refuse" and dry:
                return web.json_response({"private": "server-secret"}, status=422)
            if any(
                self.pod["metadata"][op["path"].split("/")[-1]] != op["value"] for op in body[:2]
            ):
                return web.json_response({}, status=409)
            value = copy.deepcopy(self.pod)
            entry = body[-1]["value"] if body[-1]["path"].endswith("/-") else body[-1]["value"][0]
            value["spec"].setdefault("ephemeralContainers", []).append(entry)
            if self.mode == "bad-profile" and not dry:
                entry["env"] = [{"name": "PRIVATE", "value": "server-secret"}]
            if not dry:
                value["metadata"]["resourceVersion"] = "opaque-" + entry["name"]
                value["status"].setdefault("ephemeralContainerStatuses", []).append(
                    {
                        "name": entry["name"],
                        "containerID": "runtime://" + entry["name"],
                        "restartCount": 0,
                        "state": {"running": {"startedAt": "2026-01-01T00:00:01Z"}},
                    }
                    if self.running
                    else {
                        "name": entry["name"],
                        "state": {"waiting": {"reason": self.wait_reason}},
                    }
                )
                self.pod = copy.deepcopy(value)
                self.entered.set()
                if self.mode == "drop":
                    request.transport.abort()
                    return web.Response()
                if self.mode == "stall":
                    await self.release.wait()
            return web.json_response(value)
        if request.method != "GET":
            self.requests.append((request.method, request.path))
            return web.json_response({}, status=405)
        self.reads.append(request.path)
        if request.path == "/api/v1":
            return web.json_response(
                {
                    "kind": "APIResourceList",
                    "groupVersion": "v1",
                    "resources": [
                        {
                            "name": "pods/ephemeralcontainers",
                            "kind": "Pod",
                            "namespaced": True,
                            "verbs": ["get", "patch"],
                        }
                    ]
                    if self.discovery
                    else [],
                }
            )
        self.active_reads += 1
        self.maximum_reads = max(self.maximum_reads, self.active_reads)
        try:
            if self.block_read:
                self.read_entered.set()
                await self.read_release.wait()
            if self.read_status:
                return web.json_response({"private": "server-secret"}, status=self.read_status)
            value = copy.deepcopy(self.pod)
            if self.after_get:
                self.after_get(self)
            return web.json_response(value)
        finally:
            self.active_reads -= 1


@asynccontextmanager
async def debug_source(tmp_path, *, read_only=False, timeout=2):
    api = DebugApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", api.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    client = KubernetesSession(
        catalog_fixture(tmp_path, f"http://127.0.0.1:{runner.addresses[0][1]}").select(
            "kuberich-test-one"
        ),
        timeout,
    )
    await client.open()
    current = [True]
    service = EphemeralDebugService(
        client,
        PODS,
        ResourceTarget(
            SessionIdentity(client.context.name, 1), "", "pods", "team", "api", "pod-uid"
        ),
        AccessPolicy(read_only),
        lambda: current[0],
        environment=os.environ,
        directory=tmp_path,
    )
    try:
        yield service, api, current
    finally:
        api.release.set()
        api.read_release.set()
        await service.stop_owned()
        await client.close()
        await runner.cleanup()
