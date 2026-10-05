"""Real loopback HTTP discovery, consistent pagination and owned cancellation."""

import asyncio
import threading
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.adapters import kubernetes
from kubetrol.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kubetrol.domain.resources import api_resource
from kubetrol.errors import AppError
from kubetrol.services import resources
from tests.support.resources import (
    aggregated,
    aggregated_group,
    aggregated_resource,
    collection,
    descriptor,
    item,
    legacy_roots,
    pod_resource,
    reader_fixture,
)


def named_group(name: str = "apps") -> dict:
    return {
        "name": name,
        "versions": [{"groupVersion": f"{name}/v1", "version": "v1"}],
        "preferredVersion": {"groupVersion": f"{name}/v1", "version": "v1"},
    }


@pytest.mark.asyncio
async def test_legacy_discovery_prefers_served_version_and_reads_both_scopes(
    tmp_path: Path,
) -> None:
    bodies = legacy_roots()
    group = named_group()
    group["versions"].insert(0, {"groupVersion": "apps/v1beta1", "version": "v1beta1"})
    bodies["/apis"]["groups"] = [group]
    for version in ("v1", "v1beta1"):
        bodies[f"/apis/apps/{version}"] = {
            "groupVersion": f"apps/{version}",
            "resources": [descriptor("deployments", kind="Deployment")],
        }
    bodies["/api/v1/namespaces"] = {
        **collection(item("team", namespace=None)),
        "kind": "NamespaceList",
    }
    bodies["/api/v1/namespaces/team/pods"] = collection(item())
    bodies["/api/v1/pods"] = collection(
        item("one", namespace="team"), item("one", namespace="other", uid="other-uid")
    )
    paths = []

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer synthetic"
        assert request.headers["Accept-Encoding"] == "identity"
        paths.append(request.path)
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        before = (tmp_path / "fixture-config").read_bytes()
        discovery = await reader.discover()
        assert not discovery.partial
        assert {resource.name for resource in discovery.resources} == {
            "pods",
            "namespaces",
            "deployments",
        }
        assert discovery.find("deployments", group="apps").version == "v1"
        assert discovery.find("deployments", group="apps", version="v1beta1").version == "v1beta1"
        pods = discovery.find("po")
        scoped = await reader.list(pods, "team")
        assert scoped.namespace == "team" and scoped.resource_version == "opaque/snapshot"
        assert scoped.items[0].namespace == "team"
        all_namespaces = await reader.list(pods)
        assert {record.namespace for record in all_namespaces.items} == {"team", "other"}
        namespaces = await reader.list(discovery.find("namespaces"))
        assert namespaces.items[0].namespace is None
        assert (tmp_path / "fixture-config").read_bytes() == before
    assert "/api/v1/pods/log" not in paths


@pytest.mark.asyncio
async def test_group_without_preferred_version_preserves_directory_order(tmp_path: Path) -> None:
    bodies = legacy_roots()
    group = named_group()
    del group["preferredVersion"]
    bodies["/apis"]["groups"] = [group]
    bodies["/apis/apps/v1"] = {
        "groupVersion": "apps/v1",
        "resources": [descriptor("deployments", kind="Deployment")],
    }

    async def handler(request):
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        catalog = await reader.discover()
        assert not catalog.partial
        assert catalog.find("deployments", group="apps").version == "v1"


@pytest.mark.asyncio
async def test_aggregated_discovery_uses_two_reads_and_refreshes_stale_preferred_version(
    tmp_path: Path,
) -> None:
    modern_group = aggregated_group("apps", "v1", freshness="Stale")
    modern_group["versions"].append(
        {"version": "v1beta1", "freshness": "Current", "resources": [aggregated_resource()]}
    )
    paths = []

    async def handler(request):
        paths.append(request.path)
        if request.path == "/api":
            assert "apidiscovery.k8s.io" in request.headers["Accept"]
            return web.json_response(aggregated(aggregated_group()))
        if request.path == "/apis":
            return web.json_response(aggregated(modern_group))
        assert request.path == "/apis/apps/v1"
        assert request.headers["Accept"] == "application/json"
        return web.json_response({"groupVersion": "apps/v1", "resources": [descriptor()]})

    async with reader_fixture(tmp_path, handler) as reader:
        discovery = await reader.discover()
        assert not discovery.partial
        assert discovery.find("pods", group="apps").version == "v1"
        assert len(discovery.resources) == 3
    assert set(paths) == {"/api", "/apis", "/apis/apps/v1"}


@pytest.mark.asyncio
async def test_current_aggregated_discovery_needs_only_root_requests(tmp_path: Path) -> None:
    paths = []
    core = aggregated_group()
    core["metadata"] = {}  # The real API omits the empty core group name.
    core["versions"][0]["resources"].append({**aggregated_resource(), "resource": "pods/log"})

    async def handler(request):
        paths.append(request.path)
        return web.json_response(aggregated(core) if request.path == "/api" else aggregated())

    async with reader_fixture(tmp_path, handler) as reader:
        catalog = await reader.discover()
        assert catalog.find("pods").kind == "Pod"
    assert set(paths) == {"/api", "/apis"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path,status", [("/apis", 403), ("/apis", 503), ("/api/v1", 403)])
async def test_partial_discovery_is_explicit_and_never_assumes_access(
    tmp_path: Path, path: str, status: int
) -> None:
    bodies = legacy_roots()

    async def handler(request):
        if request.path == path:
            return web.Response(status=status, text="opaque-sensitive-body")
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        catalog = await reader.discover()
        assert catalog.partial and catalog.issues[0].status == status
        assert catalog.issues[0].reason == ("forbidden" if status == 403 else "unavailable")
        assert "opaque-sensitive" not in repr(catalog)
        if path == "/api/v1":
            with pytest.raises(AppError, match="not discovered"):
                catalog.find("pods")
        else:
            assert catalog.find("pods").kind == "Pod"


def malformed_discovery() -> list[tuple[str, dict]]:
    modern_bad = aggregated(aggregated_group())
    modern_bad["apiVersion"] = "apidiscovery.k8s.io/v2beta1"
    named_core = aggregated(aggregated_group("named"))
    freshness = aggregated(aggregated_group(freshness="Invalid"))
    group_version = named_group()
    group_version["versions"][0]["groupVersion"] = "wrong/v1"
    preferred = named_group()
    preferred["preferredVersion"]["groupVersion"] = "apps/v9"
    return [
        ("/api", {"kind": "Wrong"}),
        ("/apis", {"kind": "Wrong"}),
        ("/api", modern_bad),
        ("/api", named_core),
        ("/api", freshness),
        ("/api", {"kind": "APIVersions", "versions": ["v1", "v1"]}),
        ("/api", {"kind": "APIVersions", "versions": False}),
        ("/apis", aggregated(aggregated_group(""))),
        ("/apis", {"kind": "APIGroupList", "groups": [named_group(), named_group()]}),
        ("/apis", {"kind": "APIGroupList", "groups": [group_version]}),
        ("/apis", {"kind": "APIGroupList", "groups": [preferred]}),
        ("/api/v1", {"groupVersion": "wrong", "resources": []}),
        ("/api/v1", {"groupVersion": "v1", "resources": [descriptor(), descriptor()]}),
        ("/api/v1", {"groupVersion": "v1", "resources": [{**descriptor(), "name": "pods/a/b"}]}),
        ("/api/v1", {"groupVersion": "v1", "resources": [{**descriptor(), "name": "pods/.."}]}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,payload", malformed_discovery())
async def test_invalid_discovery_is_visible_without_losing_other_roots(
    tmp_path: Path, path: str, payload: dict
) -> None:
    bodies = legacy_roots()
    bodies[path] = payload

    async def handler(request):
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        catalog = await reader.discover()
        assert catalog.partial and catalog.issues[0].reason == "invalid"
        assert catalog.issues[0].source == (path if path in {"/api", "/apis"} else "v1")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api", "/api/v1"])
async def test_auth_failure_is_fatal_instead_of_partial_empty_discovery(
    tmp_path: Path, path: str
) -> None:
    bodies = legacy_roots()

    async def handler(request):
        if request.path == path:
            return web.Response(status=401, text="opaque-sensitive-body")
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem) as error:
            await reader.discover()
        assert error.value.state is ConnectionState.AUTH_ERROR
        assert error.value.status == 401 and "opaque-sensitive" not in str(error.value)


@pytest.mark.asyncio
async def test_empty_nil_discovery_lists_are_not_invented_resource_types(tmp_path: Path) -> None:
    bodies = {
        "/api": {"kind": "APIVersions", "versions": None},
        "/apis": {"kind": "APIGroupList", "groups": None},
    }

    async def handler(request):
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        assert (await reader.discover()).resources == ()
        bodies["/api"]["versions"] = ["v1"]
        bodies["/api/v1"] = {"groupVersion": "v1", "resources": None}
        assert (await reader.discover()).resources == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("aggregated_mode", [False, True])
async def test_combined_resource_limit_fails_instead_of_reporting_a_truncated_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aggregated_mode: bool
) -> None:
    monkeypatch.setattr(resources, "MAX_RESOURCES", 1)
    bodies = legacy_roots()
    bodies["/api/v1"]["resources"] = [descriptor()]
    bodies["/apis"]["groups"] = [named_group()]
    bodies["/apis/apps/v1"] = {"groupVersion": "apps/v1", "resources": [descriptor()]}
    if aggregated_mode:
        bodies["/api"] = aggregated(aggregated_group())
        bodies["/apis"] = aggregated(aggregated_group("apps"))

    async def handler(request):
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as error:
            await reader.discover()
        assert error.value.state is ConnectionState.API_ERROR


@pytest.mark.asyncio
async def test_discovery_version_and_per_root_resource_limits_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources, "MAX_VERSIONS", 1)
    bodies = legacy_roots()
    bodies["/api/v1"]["resources"] = [descriptor()]
    bodies["/apis"]["groups"] = [named_group()]
    bodies["/apis/apps/v1"] = {"groupVersion": "apps/v1", "resources": [descriptor()]}

    async def handler(request):
        return web.json_response(bodies[request.path])

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem, match="combined"):
            await reader.discover()
        monkeypatch.setattr(resources, "MAX_RESOURCES", 1)
        core = aggregated_group()
        core["versions"].append(
            {"version": "v2", "freshness": "Current", "resources": [aggregated_resource()]}
        )
        bodies["/api"] = aggregated(core)
        bodies["/apis"] = aggregated()
        catalog = await reader.discover()
        assert catalog.partial
        monkeypatch.setattr(resources, "MAX_VERSIONS", 4)
        catalog = await reader.discover()
        assert catalog.partial and catalog.issues[0].reason == "invalid"


@pytest.mark.asyncio
async def test_multiple_pages_preserve_opaque_version_and_return_independent_manifests(
    tmp_path: Path,
) -> None:
    tokens = []

    async def handler(request):
        assert request.path == "/api/v1/namespaces/team/pods"
        assert request.query["limit"] == "100"
        token = request.query["continue"]
        tokens.append(token)
        return web.json_response(
            collection(item("one"), token="opaque/page-2") if not token else collection(item("two"))
        )

    async with reader_fixture(tmp_path, handler) as reader:
        snapshot = await reader.list(pod_resource(), "team")
        assert snapshot.resource_version == "opaque/snapshot"
        assert [record.name for record in snapshot.items] == ["one", "two"]
        assert tokens == ["", "opaque/page-2"]
        manifest = snapshot.items[0].manifest
        manifest["spec"]["containers"][0]["image"] = "changed"
        assert snapshot.items[0].manifest["spec"]["containers"][0]["image"] == "synthetic"


@pytest.mark.asyncio
async def test_empty_and_unversioned_nonwatch_collections_remain_distinct(tmp_path: Path) -> None:
    body = collection()

    async def handler(request):
        return web.json_response(body)

    async with reader_fixture(tmp_path, handler) as reader:
        empty = await reader.list(pod_resource())
        assert empty.items == () and empty.resource_version == "opaque/snapshot"
        body["metadata"].pop("resourceVersion")
        value = item()
        value["metadata"].pop("uid")
        value["metadata"].pop("resourceVersion")
        body["items"] = [value]
        resource = api_resource("v1", {**descriptor(), "verbs": ["list"]})
        snapshot = await reader.list(resource)
        assert snapshot.resource_version is None and snapshot.items[0].uid is None


@pytest.mark.asyncio
async def test_expired_page_restarts_atomically_without_using_replacement_token(
    tmp_path: Path,
) -> None:
    tokens = []

    async def handler(request):
        tokens.append(request.query["continue"])
        if len(tokens) == 1:
            return web.json_response(collection(item("old"), rv="old-version", token="expired"))
        if len(tokens) == 2:
            return web.json_response(
                {"metadata": {"continue": "untrusted-replacement"}}, status=410
            )
        return web.json_response(collection(item("new"), rv="new-version"))

    async with reader_fixture(tmp_path, handler) as reader:
        snapshot = await reader.list(pod_resource(), "team")
        assert snapshot.resource_version == "new-version"
        assert [record.name for record in snapshot.items] == ["new"]
    assert tokens == ["", "expired", ""]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,attempts", [(410, 2), (403, 1), (500, 1), (401, 1)])
async def test_repeated_expiry_and_permission_errors_do_not_become_empty_lists(
    tmp_path: Path, status: int, attempts: int
) -> None:
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.Response(status=status, text="opaque-sensitive-response")

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(HttpProblem) as error:
            await reader.list(pod_resource(), "team")
        assert error.value.status == status
        assert "opaque-sensitive" not in str(error.value) and len(calls) == attempts


def malformed_collections() -> list[dict]:
    duplicate_name = item("one", uid="different-uid")
    return [
        {**collection(), "apiVersion": "wrong/v1"},
        {**collection(), "metadata": None},
        collection(rv=None),
        collection(rv=""),
        {**collection(), "items": None},
        {**collection(), "items": [None]},
        collection(item(), item()),
        collection(item("one"), item("two", uid="owned-one")),
        collection(item(), duplicate_name),
        collection(item(namespace="other")),
        {**collection(), "metadata": {"resourceVersion": "opaque", "continue": 3}},
        collection(token="a" * 8193),
        collection(token="opaque\ncontrol"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", malformed_collections())
async def test_malformed_collection_never_returns_partial_success(
    tmp_path: Path, body: dict
) -> None:
    async def handler(request):
        return web.json_response(body)

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as error:
            await reader.list(pod_resource(), "team")
        assert error.value.state is ConnectionState.API_ERROR


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["version", "token"])
async def test_changed_snapshot_version_and_repeated_tokens_are_rejected(
    tmp_path: Path, mutation: str
) -> None:
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        return web.json_response(
            collection(rv=f"version-{count}" if mutation == "version" else "opaque", token="repeat")
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as error:
            await reader.list(pod_resource())
        assert error.value.state is ConnectionState.API_ERROR and count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["items", "per_page_items", "bytes", "pages"])
async def test_collection_limits_are_explicit_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    count = 0
    if limit in {"items", "per_page_items"}:
        monkeypatch.setattr(resources, "MAX_ITEMS", 1)
    if limit == "bytes":
        monkeypatch.setattr(resources, "MAX_SNAPSHOT_BYTES", 1)
    if limit == "pages":
        monkeypatch.setattr(resources, "MAX_PAGES", 2)

    async def handler(request):
        nonlocal count
        count += 1
        values = [item(str(count))]
        if limit == "per_page_items":
            values.append(item("extra"))
        return web.json_response(
            collection(*values, token=str(count) if limit in {"items", "pages"} else "")
        )

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ConnectionProblem) as error:
            await reader.list(pod_resource())
        assert error.value.state is ConnectionState.API_ERROR


@pytest.mark.asyncio
async def test_unadvertised_verb_and_invalid_namespace_fail_before_requests(tmp_path: Path) -> None:
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(collection())

    async with reader_fixture(tmp_path, handler) as reader:
        get_only = api_resource("v1", {**descriptor(), "verbs": ["get"]})
        with pytest.raises(AppError, match="list support"):
            await reader.list(get_only)
        with pytest.raises(AppError, match="Namespace"):
            await reader.list(pod_resource(), "../escape")
        for page_size in (False, 0, 501, 1.5):
            with pytest.raises(AppError, match="page size"):
                await reader.list(pod_resource(), page_size=page_size)
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["discover", "list", "json"])
async def test_owned_deadlines_cancel_requests(tmp_path: Path, operation: str) -> None:
    async def handler(request):
        await asyncio.sleep(2)
        return web.json_response(legacy_roots()["/api"])

    async with reader_fixture(tmp_path, handler, timeout=0.1) as reader:
        with pytest.raises(ConnectionProblem) as error:
            if operation == "discover":
                await reader.discover()
            elif operation == "list":
                await reader.list(pod_resource())
            else:
                await reader.session.get_json("/api")
        assert error.value.state is ConnectionState.TIMEOUT


@pytest.mark.asyncio
async def test_discovery_cancellation_awaits_every_owned_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    children = []

    async def handler(request):
        started.set()
        await asyncio.sleep(5)
        return web.json_response({})

    async with reader_fixture(tmp_path, handler) as reader:
        original = reader.session.get_json

        async def observed(*args, **kwargs):
            children.append(asyncio.current_task())
            return await original(*args, **kwargs)

        monkeypatch.setattr(reader.session, "get_json", observed)
        task = asyncio.create_task(reader.discover())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(children) == 2 and all(child.done() for child in children)


@pytest.mark.asyncio
async def test_closed_session_discovery_cannot_fall_back_to_another_client(tmp_path: Path) -> None:
    async def handler(request):
        return web.json_response({})

    async with reader_fixture(tmp_path, handler) as reader:
        await reader.session.close()
        with pytest.raises(ConnectionProblem) as error:
            await reader.discover()
        assert error.value.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_cancellation_waits_for_owned_json_decoding_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    original = kubernetes._decode

    def delayed(data):
        entered.set()
        assert released.wait(timeout=3)
        try:
            return original(data)
        finally:
            finished.set()

    async def handler(request):
        return web.json_response(collection())

    monkeypatch.setattr(kubernetes, "_decode", delayed)
    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(reader.session.get_json("/api"))
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{"value":NaN}', b"\xff"])
async def test_invalid_json_is_an_explicit_discovery_issue(tmp_path: Path, body: bytes) -> None:
    async def handler(request):
        if request.path == "/api":
            return web.Response(body=body)
        return web.json_response(legacy_roots()["/apis"])

    async with reader_fixture(tmp_path, handler) as reader:
        catalog = await reader.discover()
        assert catalog.partial and catalog.issues[0].reason == "invalid"
