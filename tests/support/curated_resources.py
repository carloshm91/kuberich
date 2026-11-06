"""Owned served-schema API, real watches and deterministic curated-view barriers."""

import asyncio
import copy
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace

from aiohttp import web

from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.resources import api_resource
from tests.support.curated_access import KINDS as ACCESS_KINDS
from tests.support.curated_access import access_manifest
from tests.support.curated_policy import FAMILIES as POLICY_FAMILIES
from tests.support.curated_policy import policy_manifest
from tests.support.resources import descriptor, legacy_roots
from tests.support.standard import api as standard_resource
from tests.support.standard import manifest as standard_manifest
from tests.support.watches import frame

PRINTER_CANARY = "SYNTHETIC_MALICIOUS_PRINTER_CELL_NOT_A_CURATED_FIELD"
ERROR_CANARY = "token=SYNTHETIC_CURATED_ERROR_BODY_NOT_FOR_DISPLAY"
POLICY_NAMES = frozenset(item.resource for item in POLICY_FAMILIES)


@dataclass
class RequestEntry:
    method: str
    path: str
    query: dict
    accept: str


@dataclass
class ReadBarrier:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False


@dataclass
class WatchBarrier:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    queues: set = field(default_factory=set)


def _variant(definition, ordinal):
    resource = standard_resource(definition)
    if definition.name in POLICY_NAMES:
        body = policy_manifest(definition.name, ordinal)
    elif resource.kind in ACCESS_KINDS:
        body = access_manifest(resource.kind, variant=ordinal)
    else:
        body = standard_manifest(definition)
    if ordinal and definition.name == "horizontalpodautoscalers":
        body["spec"].update(minReplicas=1, maxReplicas=15)
        body["status"].update(currentReplicas=3, desiredReplicas=10)
    elif ordinal and definition.name == "verticalpodautoscalers":
        body["spec"]["updatePolicy"]["updateMode"] = "Initial"
        template = body["status"]["recommendation"]["containerRecommendations"][0]
        body["status"]["recommendation"]["containerRecommendations"] = [
            {**copy.deepcopy(template), "containerName": f"owned-{index}"} for index in range(10)
        ]
    elif ordinal and definition.name == "poddisruptionbudgets":
        body["status"].update(disruptionsAllowed=2, currentHealthy=10, expectedPods=10)
    elif ordinal and definition.name == "priorityclasses":
        body.update(value=20, globalDefault=False)
    elif ordinal and definition.name == "runtimeclasses":
        body["handler"] = "other-handler"
        body["overhead"]["podFixed"].update(cpu="500m", memory="1Gi")
    elif ordinal and definition.name == "leases":
        body["spec"].update(
            leaseDurationSeconds=30, leaseTransitions=2, renewTime="2026-11-06T11:00:00+01:00"
        )
    return body


class CuratedResourcesApi:
    """Fixture state is keyed by real GVRs/full paths; mutations never execute."""

    def __init__(
        self,
        *,
        hpa_versions=("v2", "v1"),
        absent=frozenset(),
        denied_paths=None,
        empty=frozenset(),
        metadata_only=frozenset(),
        normalized=frozenset(),
        descriptor_overrides=None,
    ):
        self.hpa_versions = hpa_versions
        self.absent, self.empty = set(absent), set(empty)
        self.denied_paths = dict(denied_paths or {})
        self.metadata_only, self.normalized = set(metadata_only), set(normalized)
        self.resources, self.bodies, self.collections = {}, {}, {}
        self.printer_values, self.object_resources = {}, {}
        self.requests, self.holds, self.watches = [], {}, {}
        self.active_requests = set()
        overrides = descriptor_overrides or {}
        for definition in STANDARD_RESOURCES:
            original = standard_resource(definition)
            versions = (
                hpa_versions
                if definition.name == "horizontalpodautoscalers"
                else (original.version,)
            )
            for version in versions:
                resource = replace(original, version=version)
                resource = overrides.get(
                    (resource.group, resource.version, resource.name), resource
                )
                for namespace in ("team", "other") if resource.namespaced else (None,):
                    for ordinal in range(2):
                        body = _variant(definition, ordinal)
                        body.update(apiVersion=resource.api_version, kind=resource.kind)
                        if resource.kind == "HorizontalPodAutoscaler" and resource.version == "v1":
                            body["spec"].pop("metrics", None)
                            body["status"].pop("currentMetrics", None)
                            body["spec"]["targetCPUUtilizationPercentage"] = (
                                70 if ordinal == 0 else 90
                            )
                            body["status"]["currentCPUUtilizationPercentage"] = (
                                30 if ordinal == 0 else 60
                            )
                        body["metadata"].update(
                            name="owned-a" if ordinal == 0 else "owned-b",
                            uid=f"curated-{resource.group or 'core'}-{resource.version}-{resource.name}-{namespace or 'cluster'}-{ordinal}",
                            resourceVersion="owned/object-1",
                            creationTimestamp="2026-10-01T00:00:00Z",
                        )
                        if resource.namespaced:
                            body["metadata"]["namespace"] = namespace
                        else:
                            body["metadata"].pop("namespace", None)
                        self.put(resource, body)
        self.put(
            api_resource("v1", descriptor("pods")),
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": "owned-start",
                    "namespace": "team",
                    "uid": "owned-start",
                    "resourceVersion": "owned/object-1",
                },
                "spec": {"containers": [{"name": "app", "image": "synthetic"}]},
            },
        )

    @staticmethod
    def key(resource):
        return resource.group, resource.version, resource.name

    def put(self, resource, body):
        """Root can seed fresh declared targets without a second HTTP framework."""
        self.resources[self.key(resource)] = resource
        namespace = body["metadata"].get("namespace") if resource.namespaced else None
        path = resource.path(namespace) + "/" + body["metadata"]["name"]
        self.bodies[path] = copy.deepcopy(body)
        self.object_resources[path] = self.key(resource)
        self.collections[resource.path(namespace)] = resource
        self.collections[resource.path(None)] = resource
        if resource.namespaced:
            for known_namespace in ("team", "other", "default"):
                self.collections[resource.path(known_namespace)] = resource

    def resource(self, plural, *, group=None, version=None):
        choices = [
            resource
            for resource in self.resources.values()
            if resource.name == plural
            and (group is None or resource.group == group)
            and (version is None or resource.version == version)
        ]
        assert choices
        if len(choices) > 1 and plural == "horizontalpodautoscalers" and version is None:
            return next(
                resource for resource in choices if resource.version == self.hpa_versions[0]
            )
        assert len(choices) == 1
        return choices[0]

    def objects(self, resource, namespace="team"):
        return [
            copy.deepcopy(body)
            for path, body in self.bodies.items()
            if self.object_resources[path] == self.key(resource)
            and (
                not resource.namespaced
                or namespace is None
                or body["metadata"].get("namespace") == namespace
            )
        ]

    def hold(self, path):
        barrier = ReadBarrier()
        self.holds[path] = barrier
        return barrier

    def watch(self, path):
        return self.watches.setdefault(path, WatchBarrier())

    def emit(self, path, body, *, kind="MODIFIED"):
        resource = self.collections[path]
        self.put(resource, body)
        for queue in tuple(self.watch(path).queues):
            queue.put_nowait((kind, copy.deepcopy(body)))

    def roots(self):
        roots = legacy_roots()
        served = [
            resource
            for resource in self.resources.values()
            if (resource.group, resource.name) not in self.absent
        ]
        groups = sorted({resource.group for resource in served if resource.group})
        roots["/apis"]["groups"] = []
        for group in groups:
            versions = sorted({resource.version for resource in served if resource.group == group})
            preferred = self.hpa_versions[0] if group == "autoscaling" else versions[0]
            roots["/apis"]["groups"].append(
                {
                    "name": group,
                    "versions": [
                        {"groupVersion": f"{group}/{version}", "version": version}
                        for version in versions
                    ],
                    "preferredVersion": {
                        "groupVersion": f"{group}/{preferred}",
                        "version": preferred,
                    },
                }
            )
        for group, version in sorted({(resource.group, resource.version) for resource in served}):
            path = f"/apis/{group}/{version}" if group else "/api/v1"
            existing = roots.get(path, {}).get("resources", [])
            definitions = {item["name"]: item for item in existing}
            definitions.update(
                {
                    resource.name: descriptor(
                        resource.name, namespaced=resource.namespaced, kind=resource.kind
                    )
                    for resource in served
                    if (resource.group, resource.version) == (group, version)
                }
            )
            roots[path] = {
                "kind": "APIResourceList",
                "groupVersion": f"{group}/{version}" if group else version,
                "resources": list(definitions.values()),
            }
        return roots

    def table(self, resource, bodies, *, compact=False):
        rows = []
        for original in bodies:
            body = copy.deepcopy(original)
            if compact:
                body = {
                    "apiVersion": "meta.k8s.io/v1",
                    "kind": "PartialObjectMetadata",
                    "metadata": body["metadata"],
                }
            rows.append(
                {
                    "object": body,
                    "cells": [self.printer_values.get(self.key(resource), PRINTER_CANARY)],
                }
            )
        return {
            "apiVersion": "meta.k8s.io/v1",
            "kind": "Table",
            "metadata": {"resourceVersion": "owned/list-1"},
            "columnDefinitions": [
                {"name": "Malicious printer", "type": "string", "description": PRINTER_CANARY}
            ],
            "rows": rows,
        }

    async def handle(self, request):
        task = asyncio.current_task()
        self.active_requests.add(task)
        self.requests.append(
            RequestEntry(
                request.method, request.path, dict(request.query), request.headers.get("Accept", "")
            )
        )
        try:
            if request.method != "GET":
                return web.json_response({"message": "Fixture mutations are refused."}, status=405)
            if request.path in self.denied_paths:
                return web.json_response(
                    {"message": ERROR_CANARY}, status=self.denied_paths[request.path]
                )
            discovery = self.roots()
            if request.path in discovery:
                return web.json_response(discovery[request.path])
            if request.path == "/api/v1/namespaces" and "watch" not in request.query:
                return web.json_response(
                    {
                        "apiVersion": "v1",
                        "kind": "NamespaceList",
                        "metadata": {"resourceVersion": "owned/namespaces"},
                        "items": [
                            {
                                "metadata": {
                                    "name": name,
                                    "uid": "namespace-" + name,
                                    "resourceVersion": "owned/ns-1",
                                }
                            }
                            for name in ("team", "other", "default")
                        ],
                    }
                )
            resource = self.collections.get(request.path)
            if resource is not None and "watch" in request.query:
                response = web.StreamResponse(headers={"Content-Type": "application/json"})
                await response.prepare(request)
                barrier = self.watch(request.path)
                queue = asyncio.Queue()
                barrier.queues.add(queue)
                barrier.closed.clear()
                barrier.entered.set()
                try:
                    while True:
                        kind, body = await queue.get()
                        compact = (
                            self.key(resource) in self.metadata_only
                            and request.query.get("includeObject") == "Metadata"
                        )
                        payload = (
                            self.table(resource, [body], compact=compact)
                            if "as=Table" in request.headers.get("Accept", "")
                            else body
                        )
                        await response.write(frame({"type": kind, "object": payload}))
                finally:
                    barrier.queues.discard(queue)
                    barrier.closed.set()
            if request.path in self.holds:
                barrier = self.holds[request.path]
                barrier.entered.set()
                try:
                    await barrier.release.wait()
                except asyncio.CancelledError:
                    barrier.cancelled = True
                    raise
                finally:
                    barrier.finished.set()
            if request.path in self.bodies:
                return web.json_response(copy.deepcopy(self.bodies[request.path]))
            if resource is not None:
                namespace = (
                    request.path.split("/namespaces/")[1].split("/")[0]
                    if "/namespaces/" in request.path
                    else None
                )
                bodies = self.objects(resource, namespace)
                if self.key(resource) in self.empty:
                    bodies = []
                if self.key(resource) in self.normalized:
                    for body in bodies:
                        body.pop("apiVersion", None)
                        body.pop("kind", None)
                elif "as=Table" in request.headers.get("Accept", ""):
                    return web.json_response(
                        self.table(
                            resource,
                            bodies,
                            compact=self.key(resource) in self.metadata_only
                            and request.query.get("includeObject") == "Metadata",
                        )
                    )
                return web.json_response(
                    {
                        "apiVersion": resource.api_version,
                        "kind": resource.kind + "List",
                        "metadata": {"resourceVersion": "owned/list-1"},
                        "items": bodies,
                    }
                )
            return web.json_response({"message": ERROR_CANARY}, status=404)
        finally:
            self.active_requests.discard(task)


@asynccontextmanager
async def curated_resources_api(directory, api=None):
    api = api or CuratedResourcesApi()
    application = web.Application()
    application.router.add_route("*", "/{path:.*}", api.handle)
    runner = web.AppRunner(application, shutdown_timeout=0.1, handler_cancellation=True)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    address = runner.addresses[0]
    try:
        yield f"http://127.0.0.1:{address[1]}", api
    finally:
        for hold in api.holds.values():
            hold.release.set()
        await runner.cleanup()
        assert not api.active_requests
        assert not any(watch.queues for watch in api.watches.values())
