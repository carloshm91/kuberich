"""Synthetic configuration API with conditional writes and held disclosure reads."""

import asyncio
import base64
import copy
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from aiohttp import web

from tests.support.connections import namespaces
from tests.support.editing import apply_patch
from tests.support.standard import roots
from tests.support.workspace import stable_watch

TEXT = "owned-private-value\npassword=explicit-value\n[red]\x1b[2J"


@dataclass(repr=False)
class DataApi:
    kind: str
    value: dict
    requests: list = field(default_factory=list)
    hold: bool = False
    read_status: int | None = None
    patch_status: int | None = None
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def resource(self):
        return "secrets" if self.kind == "Secret" else "configmaps"

    @property
    def path(self):
        return f"/api/v1/namespaces/team/{self.resource}/owned-one"

    async def handle(self, request):
        self.requests.append((request.method, request.path, dict(request.query)))
        if request.path == self.path:
            if request.method == "PATCH":
                assert request.query.get("fieldValidation") == "Strict"
                if self.patch_status:
                    return web.Response(status=self.patch_status, text="owned-private-server-value")
                candidate = apply_patch(self.value, await request.json())
                if candidate is None:
                    return web.Response(status=422, text="owned-private-conflict")
                if request.query.get("dryRun") != "All":
                    candidate["metadata"]["resourceVersion"] = "version/2"
                    self.value = candidate
                return web.json_response(candidate)
            self.started.set()
            if self.hold:
                await self.release.wait()
            if self.read_status:
                return web.Response(status=self.read_status, text="owned-private-server-value")
            return web.json_response(self.value)
        if request.path == "/api/v1/namespaces" and "watch" not in request.query:
            return namespaces("team", "default")
        discovery = roots()
        for resource in discovery["/api/v1"]["resources"]:
            if resource["name"] in {"configmaps", "secrets"}:
                resource["verbs"] = [*resource["verbs"], "patch"]
        if request.path in discovery:
            return web.json_response(discovery[request.path])
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            {
                "apiVersion": "v1",
                "kind": self.kind + "List",
                "metadata": {"resourceVersion": "version/list"},
                "items": [self.value] if request.path.endswith("/" + self.resource) else [],
            }
        )


@asynccontextmanager
async def data_api(kind="Secret"):
    value = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {
            "name": "owned-one",
            "namespace": "team",
            "uid": "owned-data-uid",
            "resourceVersion": "version/1",
        },
        "data": {"chosen": base64.b64encode(TEXT.encode()).decode() if kind == "Secret" else TEXT},
    }
    value.setdefault("data" if kind == "Secret" else "binaryData", {})["z-binary"] = (
        base64.b64encode(b"\xff\x00").decode()
    )
    fixture = DataApi(kind, copy.deepcopy(value))
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
