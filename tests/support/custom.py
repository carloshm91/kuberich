"""Owned CRD HTTP fixture for the generic UI, including live schema replacement."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from aiohttp import web

from tests.support.connections import namespaces
from tests.support.resources import collection, descriptor, item, legacy_roots
from tests.support.tables import custom_item, server_table
from tests.support.watches import frame
from tests.support.workspace import stable_watch, workspace_api

GROUP = "owned.example.test"
OTHER_GROUP = "other.example.test"


def roots(installed=True, preferred="v1", ambiguous=False, recreated=False):
    values = legacy_roots()
    groups = ([GROUP] if installed else []) + ([OTHER_GROUP] if ambiguous else [])
    values["/apis"]["groups"] = [
        {
            "name": group,
            "versions": [
                {"groupVersion": group + "/" + version, "version": version}
                for version in ("v1beta1", "v1")
            ],
            "preferredVersion": {"groupVersion": group + "/" + preferred, "version": preferred},
        }
        for group in groups
    ]
    for group in groups:
        for version in ("v1beta1", "v1"):
            values["/apis/" + group + "/" + version] = {
                "groupVersion": group + "/" + version,
                "resources": [
                    {
                        **descriptor(
                            "widgets",
                            kind="Secret" if recreated else "Widget",
                            namespaced=not recreated,
                        ),
                        "singularName": "widget",
                        "shortNames": ["wdg"],
                    },
                    {
                        **descriptor("gadgets", kind="Gadget", namespaced=False),
                        "singularName": "gadget",
                        "shortNames": ["gdt"],
                    },
                ],
            }
    return values


def objects(group=GROUP, version="v1", name="widgets", namespace="team", recreated=False):
    result = []
    opaque = recreated and name == "widgets"
    for title, number in (("ten", 10), ("two", 2), ("missing", None)):
        obj = custom_item(
            title,
            namespace if name == "widgets" and not opaque else None,
            ("replacement-" if opaque else "owned-") + title,
            version=version,
        )
        obj["apiVersion"] = group + "/" + version
        obj["kind"] = "Secret" if opaque else "Widget" if name == "widgets" else "Gadget"
        if opaque:
            obj["data"] = {"payload": "synthetic-private-replacement"}
        obj["metadata"]["creationTimestamp"] = "2026-10-01T00:00:00Z"
        obj["spec"].update(level=number, unknown={"preserved": "raw-field"})
        result.append(obj)
    return result


def table(items, *, changed=False, sensitive=False, dates=None):
    value = server_table(*items)
    if changed:
        value["columnDefinitions"][1] = {"name": "[bold]Ready", "type": "boolean"}
    if dates is not None:
        value["columnDefinitions"][1] = {"name": "Observed", "type": "date"}
    for row, obj in zip(value["rows"], items, strict=True):
        row["cells"][1] = obj["spec"]["enabled"] if changed else obj["spec"]["level"]
        if dates is not None:
            row["cells"][1] = dates[obj["metadata"]["name"]]
        if sensitive:
            row["cells"].append("Bearer synthetic-column-secret")
    if sensitive:
        value["columnDefinitions"].append({"name": "[bold]apiToken", "type": "string"})
    return value


@dataclass
class CustomAPI:
    installed: bool = True
    preferred: str = "v1"
    ambiguous: bool = False
    fallback: bool = False
    malformed: bool = False
    denied: bool = False
    changed: bool = False
    sensitive: bool = False
    recreated: bool = False
    core_pods: bool = False
    dates: dict | None = None
    reads: list = field(default_factory=list)
    streams: dict = field(default_factory=dict)

    def roots(self):
        return roots(self.installed, self.preferred, self.ambiguous, self.recreated)

    async def handler(self, request):
        self.reads.append((request.path, dict(request.query), request.headers.get("Accept")))
        if request.path.endswith("/events"):
            return web.json_response({"apiVersion": "v1", "kind": "EventList", "items": []})
        if request.path == "/api/v1/namespaces":
            return await stable_watch(request)
        if request.path.startswith("/api/v1/namespaces/") and request.path.count("/") == 4:
            name = request.path.rsplit("/", 1)[1]
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": name,
                        "uid": "namespace-" + name,
                        "resourceVersion": "owned-namespace-object",
                    },
                }
            )
        if self.core_pods and "/pods" in request.path:
            pod = {"apiVersion": "v1", "kind": "Pod", **item("core", uid="owned-core")}
            if "watch" in request.query:
                return await stable_watch(request)
            return web.json_response(pod if request.path.endswith("/core") else collection(pod))
        if not request.path.startswith("/apis/"):
            return (
                await stable_watch(request)
                if "watch" in request.query
                else web.json_response(collection())
            )
        parts = request.path.split("/")
        group, version = parts[2:4]
        namespaced = parts[4] == "namespaces"
        namespace = parts[5] if namespaced else None
        name = parts[6] if namespaced else parts[4]
        prefix = 7 if namespaced else 5
        if not self.installed or self.denied:
            return web.Response(status=403 if self.denied else 404)
        if self.recreated and name == "widgets" and namespaced:
            return web.Response(status=404)
        values = objects(group, version, name, namespace or "team", self.recreated)
        if len(parts) > prefix:
            return web.json_response(
                next(value for value in values if value["metadata"]["name"] == parts[-1])
            )
        if self.fallback and "as=Table" in request.headers.get("Accept", ""):
            return web.Response(status=406)
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            self.streams[request.path] = response
            try:
                while request.transport is not None and not request.transport.is_closing():
                    import asyncio

                    await asyncio.sleep(0.005)
            finally:
                if self.streams.get(request.path) is response:
                    del self.streams[request.path]
            return response
        if self.fallback or "as=Table" not in request.headers.get("Accept", ""):
            return web.json_response(
                {
                    "apiVersion": group + "/" + version,
                    "kind": values[0]["kind"] + "List",
                    "metadata": {"resourceVersion": "owned/list"},
                    "items": values,
                }
            )
        result = table(values, changed=self.changed, sensitive=self.sensitive, dates=self.dates)
        if self.malformed:
            result["rows"][0]["cells"][1] = "malformed"
        return web.json_response(result)

    async def update(self, path, *, changed=False):
        parts = path.split("/")
        items = objects(
            parts[2], parts[3], parts[-1], parts[5] if "namespaces" in parts else "team"
        )
        items[0]["metadata"]["resourceVersion"] = "schema-change"
        items[0]["metadata"]["annotations"] = {"owned.example.test/unrelated": "changed"}
        await self.streams[path].write(
            frame(
                {"type": "MODIFIED", "object": table(items[:1], changed=changed, dates=self.dates)}
            )
        )


@asynccontextmanager
async def custom_api(state=None):
    owner = state or CustomAPI()

    async def ns(request):
        return namespaces("team", "other", "default")

    async with workspace_api(ns, owner.handler, discovery_roots=owner.roots) as url:
        yield url, owner
