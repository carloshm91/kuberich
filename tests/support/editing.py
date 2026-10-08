"""Owned conditional JSON-Patch/dry-run API with explicit non-persistence evidence."""

import copy
from contextlib import asynccontextmanager

from aiohttp import web

from tests.support.mutations import MutationApi


def apply_patch(value, operations):
    candidate = copy.deepcopy(value)
    for item in operations:
        parts = [part.replace("~1", "/").replace("~0", "~") for part in item["path"][1:].split("/")]
        parent = candidate
        for part in parts[:-1]:
            parent = parent[part]
        key = parts[-1]
        if item["op"] == "test":
            if parent.get(key) != item["value"]:
                return None
        elif item["op"] == "remove":
            del parent[key]
        else:
            parent[key] = item["value"]
    return candidate


class EditingApi(MutationApi):
    def __init__(self):
        super().__init__()
        self.validation_status = None
        self.validation_entered = None

    async def handle(self, request):
        if request.method != "PATCH":
            return await super().handle(request)
        body = await request.json()
        query = dict(request.query)
        assert query.get("fieldValidation") == "Strict"
        assert request.path == "/api/v1/namespaces/team/configmaps/owned-one"
        self.requests.append((request.path, list(request.headers.items()), body, query))
        dry = query.get("dryRun") == "All"
        self.entered.set()
        if self.before_patch is not None:
            self.before_patch(self.value)
        status = self.validation_status if dry else self.patch_status
        if status is not None:
            return web.Response(status=status, text="sensitive-server-error\x1b[31m")
        candidate = apply_patch(self.value, body)
        if candidate is None:
            return web.json_response({"message": "precondition"}, status=422)
        if "notARealField" in candidate:
            return web.Response(status=400, text="sensitive-validation-content")
        if not dry:
            candidate["metadata"]["resourceVersion"] = "opaque/version-8"
            self.value = candidate
        if self.mode == "drop":
            request.transport.abort()
            return web.Response()
        if self.mode == "stall":
            await self.release.wait()
        if self.mode == "bad-json":
            return web.Response(text="sensitive-error", content_type="application/json")
        if self.mode == "wrong-uid":
            candidate["metadata"]["uid"] = "wrong"
        return web.json_response(candidate)


@asynccontextmanager
async def editing_api(*, tls=None):
    fixture = EditingApi()
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
