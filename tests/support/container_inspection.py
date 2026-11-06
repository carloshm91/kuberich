"""Owned HTTP fixture for finite, same-namespace container inspection reads."""

import asyncio
import base64
import copy
import json
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from aiohttp import web

from kuberich.domain.resources import ApiResource, Discovery

NAMESPACE = "inspection-team"
POD_NAME = "inspection-pod"
POD_UID = "inspection-pod-uid"
PRIVATE_VALUE = "inspection-private-value-[red]-password=fixture-only"
POD_PATH = f"/api/v1/namespaces/{NAMESPACE}/pods/{POD_NAME}"
CONFIG_PATH = f"/api/v1/namespaces/{NAMESPACE}/configmaps/inspection-config"
SECRET_PATH = f"/api/v1/namespaces/{NAMESPACE}/secrets/inspection-secret"


def descriptor(kind: str) -> ApiResource:
    return ApiResource(
        "",
        "v1",
        {"Pod": "pods", "ConfigMap": "configmaps", "Secret": "secrets"}[kind],
        kind,
        True,
        frozenset({"get"}),
    )


def discovery() -> Discovery:
    return Discovery(tuple(descriptor(kind) for kind in ("Pod", "ConfigMap", "Secret")))


def pod_fixture() -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": POD_NAME,
            "namespace": NAMESPACE,
            "uid": POD_UID,
            "resourceVersion": "pod-version-1",
            "labels": {"fixture": "inspection"},
        },
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "synthetic/image:declared",
                    "imagePullPolicy": "IfNotPresent",
                    "envFrom": [
                        {"configMapRef": {"name": "inspection-config"}},
                        {"secretRef": {"name": "inspection-secret"}, "prefix": "PRIVATE_"},
                    ],
                    "env": [
                        {"name": "LITERAL", "value": "synthetic-literal"},
                        {"name": "EXPANDED", "value": "$(LITERAL)/$(CONFIG)"},
                        {
                            "name": "CHOSEN",
                            "valueFrom": {
                                "secretKeyRef": {"name": "inspection-secret", "key": "chosen"}
                            },
                        },
                    ],
                    "resources": {"limits": {"cpu": "250m", "memory": "64Mi"}},
                }
            ],
            "initContainers": [
                {"name": "init", "image": "synthetic/init:v1"},
                {"name": "sidecar", "image": "synthetic/sidecar:v1", "restartPolicy": "Always"},
            ],
            "ephemeralContainers": [{"name": "debug", "image": "synthetic/debug:v1"}],
            "imagePullSecrets": [{"name": "image-auth-reference-only"}],
        },
        "status": {
            "containerStatuses": [
                {
                    "name": "app",
                    "image": "status/image:v2",
                    "imageID": "containerd://sha256:synthetic",
                    "containerID": "containerd://fixture",
                }
            ]
        },
    }


def source_fixture(kind: str, name: str, data: dict[str, str]) -> dict:
    return {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "uid": name + "-uid",
            "resourceVersion": name + "-version-1",
        },
        "data": data,
    }


@dataclass(repr=False)
class InspectionApi:
    records: dict[str, dict] = field(
        default_factory=lambda: {
            POD_PATH: pod_fixture(),
            CONFIG_PATH: source_fixture(
                "ConfigMap", "inspection-config", {"CONFIG": "config-current"}
            ),
            SECRET_PATH: source_fixture(
                "Secret",
                "inspection-secret",
                {"chosen": base64.b64encode(PRIVATE_VALUE.encode()).decode()},
            ),
        }
    )
    requests: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    held_paths: set[str] = field(default_factory=set)
    chunked_paths: set[str] = field(default_factory=set)
    truncated_paths: set[str] = field(default_factory=set)
    payloads: dict[str, bytes] = field(default_factory=dict)
    before_response: Callable[["InspectionApi", str], None] | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    active: int = 0

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.requests.append((request.method, request.path, dict(request.query)))
        if request.method != "GET" or request.query:
            return web.Response(status=405, text="inspection-private-server-body")
        self.active += 1
        self.started.set()
        try:
            if request.path in self.held_paths:
                await self.release.wait()
            if self.before_response is not None:
                self.before_response(self, request.path)
            status = self.statuses.get(request.path, 200 if request.path in self.records else 404)
            if status != 200:
                return web.Response(status=status, text="inspection-private-server-body")
            payload = self.payloads.get(request.path)
            if payload is None:
                payload = json.dumps(copy.deepcopy(self.records[request.path])).encode()
            if request.path in self.truncated_paths:
                response = web.StreamResponse(
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(payload) + 100),
                    }
                )
                await response.prepare(request)
                await response.write(payload[:10])
                assert request.transport is not None
                request.transport.close()
                return response
            if request.path not in self.chunked_paths:
                return web.Response(body=payload, content_type="application/json")
            response = web.StreamResponse(headers={"Content-Type": "application/json"})
            response.enable_chunked_encoding()
            await response.prepare(request)
            try:
                for start in range(0, len(payload), 16384):
                    await response.write(payload[start : start + 16384])
                await response.write_eof()
            except ConnectionResetError:
                pass
            return response
        finally:
            self.active -= 1


@asynccontextmanager
async def inspection_api():
    fixture = InspectionApi()
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
        await runner.cleanup()
