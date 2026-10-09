"""Owned real HTTP source/watch fixture; explicit mutable identities and stream queues."""

import asyncio
from collections import Counter, defaultdict
from copy import deepcopy

from aiohttp import web

from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.aggregate_logs import AggregateLogs
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame

PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))
REPLICAS = ApiResource("apps", "v1", "replicasets", "ReplicaSet", True, PODS.verbs)


def workload(resource=REPLICAS, name="workload", uid="workload-uid", owners=()):
    return {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "metadata": {
            "name": name,
            "namespace": "team",
            "uid": uid,
            "resourceVersion": "1",
            "ownerReferences": list(owners),
        },
        "spec": {},
    }


def reference(value):
    return {
        "apiVersion": value["apiVersion"],
        "kind": value["kind"],
        "name": value["metadata"]["name"],
        "uid": value["metadata"]["uid"],
        "controller": True,
    }


class AggregateApi:
    def __init__(self, *, resource=REPLICAS, count=2):
        self.resource = resource
        self.parent = workload(resource)
        self.pods = {}
        for i in range(count):
            value = pod(f"pod-{i:02}")
            value.update(apiVersion="v1", kind="Pod")
            value["metadata"]["ownerReferences"] = [reference(self.parent)]
            self.pods[value["metadata"]["name"]] = value
        self.collections = {"pods": self.pods, resource.name: {"workload": self.parent}}
        self.resources = {"pods": PODS, resource.name: resource}
        self.watchers = defaultdict(list)
        self.streams = defaultdict(list)
        self.requests = Counter()
        self.active = 0
        self.peak = 0
        self.watch_active = 0
        self.rv = 1
        self.eof = set()
        self.denied = set()
        self.initial = {}

    @staticmethod
    def observed(value):
        value = deepcopy(value)
        if value.get("status", {}).get("phase") == "Running":
            for declaration, field in (
                ("containers", "containerStatuses"),
                ("initContainers", "initContainerStatuses"),
                ("ephemeralContainers", "ephemeralContainerStatuses"),
            ):
                statuses = value["status"].setdefault(field, [])
                present = {entry["name"] for entry in statuses}
                for container in value.get("spec", {}).get(declaration, []):
                    if container["name"] not in present:
                        statuses.append({"name": container["name"], "state": {"running": {}}})
        return value

    def owner(self, reader, current=lambda: True):
        return AggregateLogs(
            reader.session,
            self.resource,
            ResourceTarget(
                SessionIdentity(reader.session.context.name, 1),
                self.resource.group,
                self.resource.name,
                "team",
                "workload",
                self.parent["metadata"]["uid"],
            ),
            AccessPolicy(True),
            current,
        )

    async def handler(self, request):
        parts = request.path.split("/")
        if parts[-1] == "log":
            name, container = parts[-2], request.query["container"]
            key = name, container
            self.requests[key] += 1
            if key in self.denied:
                return web.Response(status=403, text="hidden-private-server-body")
            response = web.StreamResponse()
            await response.prepare(request)
            self.active += 1
            self.peak = max(self.peak, self.active)
            queue = asyncio.Queue()
            self.streams[key].append(queue)
            try:
                await response.write(
                    self.initial.get(
                        key, f"2026-10-09T12:00:00Z {name}/{container} initial\n".encode()
                    )
                )
                if key in self.eof:
                    await response.write_eof()
                    return response
                while request.transport is not None and not request.transport.is_closing():
                    try:
                        value = await asyncio.wait_for(queue.get(), timeout=0.02)
                    except TimeoutError:
                        continue
                    await response.write(value)
            finally:
                self.streams[key].remove(queue)
                self.active -= 1
            return response
        if "watch" in request.query:
            name = parts[-1]
            response = web.StreamResponse()
            await response.prepare(request)
            queue = asyncio.Queue()
            self.watchers[name].append(queue)
            self.watch_active += 1
            try:
                while request.transport is not None and not request.transport.is_closing():
                    try:
                        value = await asyncio.wait_for(queue.get(), timeout=0.02)
                    except TimeoutError:
                        continue
                    await response.write(frame(value))
            finally:
                self.watchers[name].remove(queue)
                self.watch_active -= 1
            return response
        if parts[-1] in self.collections:
            name = parts[-1]
            resource = self.resources[name]
            value = collection(
                *(self.observed(item) for item in self.collections[name].values()), rv=str(self.rv)
            )
            value.update(apiVersion=resource.api_version, kind=resource.kind + "List")
            return web.json_response(value)
        name, resource_name = parts[-1], parts[-2]
        value = self.collections.get(resource_name, {}).get(name)
        return (
            web.json_response(self.observed(value))
            if value is not None
            else web.Response(status=404)
        )

    async def update(self, event, value, *, resource="pods"):
        self.rv += 1
        value = self.observed(value)
        value["metadata"]["resourceVersion"] = str(self.rv)
        name = value["metadata"]["name"]
        if event == "DELETED":
            self.collections[resource].pop(name, None)
        else:
            self.collections[resource][name] = value
        for queue in self.watchers[resource]:
            await queue.put({"type": event, "object": value})

    async def emit(self, name, container, data):
        for queue in self.streams[name, container]:
            await queue.put(data)
