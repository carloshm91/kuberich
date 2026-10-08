"""Owned batch API with UID/version preconditions, partial writes and ambiguous responses."""

import asyncio
import copy
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from tests.support.standard import manifest, roots
from tests.support.workspace import stable_watch


def selection(alias="cm", name="owned-one"):
    definition = RESOURCE_ALIASES[alias]
    value = manifest(definition, name=name)
    value["metadata"]["resourceVersion"] = "opaque-7"
    if alias in {"cj", "job"}:
        value["spec"]["suspend"] = False
    if alias == "cj":
        value["spec"]["jobTemplate"] = {
            "metadata": {"labels": {"owned": "yes"}, "annotations": {"keep": "value"}},
            "spec": {
                "template": {
                    "spec": {
                        "restartPolicy": "Never",
                        "containers": [
                            {
                                "name": "app",
                                "image": "owned-image",
                                "env": [{"name": "TOKEN", "value": "private-template-value"}],
                            }
                        ],
                    }
                }
            },
        }
    resource = ApiResource(
        definition.group,
        "v1",
        definition.name,
        value["kind"],
        definition.namespaced,
        frozenset({"get", "list", "watch", "patch", "delete", "create"}),
    )
    target = ResourceTarget(
        SessionIdentity("kuberich-test-one", 1),
        resource.group,
        resource.name,
        "team" if resource.namespaced else None,
        name,
        value["metadata"]["uid"],
    )
    return resource, target, value


class OperationApi:
    def __init__(self, alias="cm", count=1):
        self.resource, self.target, self.value = selection(alias)
        self.values = {"owned-one": self.value}
        for i in range(1, count):
            name = f"owned-{i + 1}"
            self.values[name] = selection(alias, name)[2]
        self.jobs = {}
        self.requests = []
        self.read_status = {}
        self.write_status = {}
        self.before_write = None
        self.mode = "normal"
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.read_delay = 0

    async def handle(self, request):
        root = self.resource.path(self.target.namespace)
        name = request.path.rsplit("/", 1)[-1]
        if request.method in {"DELETE", "POST", "PATCH"}:
            body = await request.json()
            self.requests.append(
                (request.method, request.path, dict(request.headers), dict(request.query), body)
            )
            self.entered.set()
            if self.before_write:
                self.before_write(self.values)
            if name in self.write_status:
                return web.Response(status=self.write_status[name], text="private-server-error")
            if request.method == "POST":
                assert request.path == "/apis/batch/v1/namespaces/team/jobs"
                jobname = body["metadata"]["name"]
                if jobname in self.jobs:
                    return web.Response(status=409)
                value = copy.deepcopy(body)
                value["metadata"].update(uid="created-job-uid", resourceVersion="job-version")
                self.jobs[jobname] = value
                status = 201
            else:
                if name not in self.values:
                    return web.Response(status=404)
                value = self.values[name]
                metadata = value["metadata"]
                if request.method == "DELETE":
                    if body["preconditions"] != {
                        "uid": metadata["uid"],
                        "resourceVersion": metadata["resourceVersion"],
                    }:
                        return web.Response(status=409)
                    if metadata.get("finalizers"):
                        metadata["deletionTimestamp"] = "2026-10-08T00:00:00Z"
                    else:
                        del self.values[name]
                    status = 200
                else:
                    for test in body[:2]:
                        if metadata[test["path"].split("/")[-1]] != test["value"]:
                            return web.Response(status=422)
                    value["spec"]["suspend"] = body[-1]["value"]
                    metadata["resourceVersion"] = "opaque-8"
                    status = 200
            if self.mode == "drop":
                request.transport.abort()
                return web.Response()
            if self.mode == "stall":
                await self.release.wait()
            if self.mode == "bad-json":
                return web.Response(status=status, text="private-invalid-json")
            if self.mode == "oversized":
                return web.Response(status=status, body=b"x" * (8 * 1024 * 1024 + 1))
            value = copy.deepcopy(value)
            if self.mode == "wrong-uid":
                value["metadata"]["uid"] = "wrong-uid"
            if self.mode == "wrong-name":
                value["metadata"]["name"] = "wrong-name"
            if self.mode == "no-uid":
                value["metadata"].pop("uid")
            if self.mode == "status":
                value = {
                    "apiVersion": "v1",
                    "kind": "Status",
                    "status": "Success",
                    "details": {"uid": self.target.uid, "name": self.target.name},
                }
            return web.json_response(value, status=status)
        if request.path.startswith(root + "/"):
            if self.read_delay:
                await asyncio.sleep(self.read_delay)
            if name in self.read_status:
                return web.Response(status=self.read_status[name], text="private-read-error")
            return (
                web.json_response(self.values[name])
                if name in self.values
                else web.Response(status=404)
            )
        if request.path == "/api/v1/namespaces":
            from tests.support.connections import namespaces

            return namespaces("team", "other")
        discovered = roots().get(request.path)
        if discovered:
            if "resources" in discovered:
                for item in discovered["resources"]:
                    item["verbs"] = ["get", "list", "watch", "patch", "delete", "create"]
            return web.json_response(discovered)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            {
                "apiVersion": self.resource.api_version,
                "kind": self.resource.kind + "List",
                "metadata": {"resourceVersion": "opaque/list"},
                "items": list(self.values.values()) if request.path == root else [],
            }
        )


@asynccontextmanager
async def operation_api(alias="cm", count=1, *, tls=None):
    fixture = OperationApi(alias, count)
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
