"""An owned writable API that records requests, enforces tests and injects real faults."""

import asyncio
import copy
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.domain.registry import RESOURCE_ALIASES
from tests.support.standard import manifest, roots
from tests.support.workspace import stable_watch


class MutationApi:
    def __init__(self):
        self.value = manifest(RESOURCE_ALIASES["cm"])
        self.value["metadata"]["resourceVersion"] = "opaque/version-7"
        self.value["metadata"]["annotations"] = {"preserved": "private-existing"}
        self.read_status = None
        self.read_delay = 0
        self.patch_status = None
        self.mode = "normal"
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.before_patch = None

    async def handle(self, request):
        from tests.support.connections import namespaces

        path = "/api/v1/namespaces/team/configmaps/owned-one"
        if request.method == "PATCH":
            assert request.path == path
            body = await request.json()
            self.requests.append((request.path, list(request.headers.items()), body))
            self.entered.set()
            if self.before_patch is not None:
                self.before_patch(self.value)
            if self.patch_status is not None:
                return web.Response(status=self.patch_status, text="private-error-payload\x1b[31m")
            for operation in body[:2]:
                field = operation["path"].split("/")[-1]
                if operation["value"] != self.value["metadata"][field]:
                    return web.json_response({"message": "precondition failed"}, status=422)
            self.value["metadata"]["annotations"] = body[2]["value"]
            self.value["metadata"]["resourceVersion"] = "opaque/version-8"
            if self.mode == "drop":
                request.transport.abort()
                return web.Response()
            if self.mode == "stall":
                await self.release.wait()
            if self.mode == "bad-json":
                return web.Response(text="private-invalid-json", content_type="application/json")
            if self.mode == "oversized":
                return web.Response(body=b"x" * (8 * 1024 * 1024 + 1))
            value = copy.deepcopy(self.value)
            if self.mode == "wrong-uid":
                value["metadata"]["uid"] = "wrong-receipt-uid"
            if self.mode == "wrong-name":
                value["metadata"]["name"] = "wrong-receipt-name"
            if self.mode == "no-version":
                value["metadata"].pop("resourceVersion")
            return web.json_response(value)
        if request.path == path:
            if self.read_delay:
                await asyncio.sleep(self.read_delay)
            if self.read_status is not None:
                return web.Response(status=self.read_status, text="private-read-error")
            return web.json_response(self.value)
        if request.path == "/api/v1/namespaces":
            return namespaces("team", "other")
        root = roots().get(request.path)
        if root is not None:
            if "resources" in root:
                for resource in root["resources"]:
                    if resource["name"] == "configmaps":
                        resource["verbs"].append("patch")
            return web.json_response(root)
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path == "/api/v1/namespaces/team/configmaps":
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMapList",
                    "metadata": {"resourceVersion": "opaque/list"},
                    "items": [self.value],
                }
            )
        return web.json_response(
            {
                "apiVersion": "v1",
                "kind": "PodList",
                "metadata": {"resourceVersion": "opaque/list"},
                "items": [],
            }
        )


@asynccontextmanager
async def mutation_api(*, tls=None):
    fixture = MutationApi()
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
