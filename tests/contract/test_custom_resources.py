"""Actual HTTP custom-resource Table reads, fallback and owned streaming."""

import asyncio
import threading
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.tables import TableDecoder
from kuberich.domain.watches import SyncStatus
from kuberich.errors import AppError
from kuberich.services import resources as module
from kuberich.services.resources import ResourceReader, parse_owned
from kuberich.services.watches import ListWatch
from tests.support.resources import reader_fixture
from tests.support.tables import custom_collection, custom_item, custom_resource, server_table
from tests.support.watches import Clock, error_event, frame


@pytest.mark.asyncio
@pytest.mark.parametrize("namespaced", [True, False])
async def test_real_paged_table_and_selected_get_keep_full_gvr_scope_and_objects(
    tmp_path, namespaced
):
    resource = custom_resource(namespaced=namespaced)
    scope = "team" if namespaced else None
    requests = []

    async def handler(request):
        requests.append((request.path, dict(request.query)))
        assert "as=Table" in request.headers["Accept"]
        assert request.query["includeObject"] == "Object"
        if request.path.endswith("/one"):
            return web.json_response(server_table(custom_item(namespace=scope)))
        second = request.query.get("continue") == "next"
        obj = custom_item(
            "two" if second else "one", namespace=scope, uid="two" if second else "one"
        )
        return web.json_response(server_table(obj, token="" if second else "next"))

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        snapshot = await reader.list(resource, scope, page_size=1)
        assert [r.name for r in snapshot.items] == ["one", "two"]
        assert snapshot.resource_version == "collection-version"
        assert [c.name for c in snapshot.columns] == ["Name", "Level", "Enabled"]
        assert snapshot.items[0].server.cells == ("one", 3, True)
        record = await reader.get(resource, "one", scope)
        assert record.manifest["spec"] == {"level": 3, "enabled": True}
        assert record.namespace == scope and record.server.columns == snapshot.columns
    assert [path for path, _ in requests] == [resource.path(scope)] * 2 + [
        resource.path(scope) + "/one"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "get"])
@pytest.mark.parametrize(
    "failure", [406, 415, "partial", "headers", "cells", "raw", "changed-page"]
)
async def test_table_refusal_restarts_once_in_json_without_losing_objects(
    tmp_path, method, failure
):
    resource = custom_resource()
    requests = []

    async def handler(request):
        table = "as=Table" in request.headers["Accept"]
        requests.append((table, request.query.get("continue", "")))
        if table:
            if isinstance(failure, int):
                return web.Response(status=failure)
            if failure == "raw":
                return web.json_response(
                    custom_item() if method == "get" else custom_collection(custom_item())
                )
            payload = server_table(custom_item())
            if failure == "partial":
                payload["rows"][0]["object"]["kind"] = "PartialObjectMetadata"
            elif failure == "headers":
                payload["columnDefinitions"] = [{"name": "Name", "type": []}]
            elif failure == "cells":
                payload["rows"][0]["cells"][1] = "not an integer"
            elif request.query.get("continue"):
                payload["columnDefinitions"][1]["name"] = "Changed"
            elif method == "list":
                payload["metadata"]["continue"] = "next"
            else:
                payload["columnDefinitions"][1]["type"] = "unsupported"
            return web.json_response(payload)
        assert "includeObject" not in request.query
        return web.json_response(
            custom_item() if method == "get" else custom_collection(custom_item())
        )

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        result = (
            await reader.get(resource, "one", "team")
            if method == "get"
            else await reader.list(resource, "team")
        )
        record = result if method == "get" else result.items[0]
        assert record.name == "one" and record.server is None
        assert record.manifest["spec"]["level"] == 3
        assert not reader.uses_tables(resource)
        assert reader.uses_tables(custom_resource(version="v1beta1"))
        assert len(requests) == (
            1 if failure == "raw" else 3 if failure == "changed-page" and method == "list" else 2
        )
        assert requests[-1][1] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "list"])
@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_auth_rbac_and_resource_errors_are_not_formatter_fallback(tmp_path, method, status):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return web.Response(status=status, text="opaque-sensitive-error")

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        resource = custom_resource()
        with pytest.raises(HttpProblem) as error:
            if method == "get":
                await reader.get(resource, "one", "team")
            else:
                await reader.list(resource, "team")
        assert error.value.status == status
        assert "opaque-sensitive" not in str(error.value)
        assert len(requests) == 1 and reader.uses_tables(resource)


@pytest.mark.asyncio
async def test_get_validates_advertised_verb_name_identity_and_memory(tmp_path, monkeypatch):
    requested = []

    async def handler(request):
        requested.append(request.path)
        return web.json_response(custom_item())

    async with reader_fixture(tmp_path, handler) as base:
        resource = custom_resource()
        with pytest.raises(AppError):
            await base.get(replace(resource, verbs=frozenset({"list"})), "one", "team")
        for name in ("../one", "one%2fother", ".", ""):
            with pytest.raises(AppError):
                await base.get(resource, name, "team")
        assert not requested
        with pytest.raises(ConnectionProblem) as error:
            await base.get(resource, "two", "team")
        assert error.value.state is ConnectionState.API_ERROR
        monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 1)
        with pytest.raises(ConnectionProblem):
            await base.get(resource, "one", "team")
        with pytest.raises(AppError):
            ResourceReader(base.session, tables="yes")


@pytest.mark.asyncio
async def test_get_timeout_does_not_wait_for_unbounded_server_body(tmp_path):
    ended = asyncio.Event()

    async def handler(request):
        try:
            await asyncio.sleep(0.2)
            return web.json_response(custom_item())
        finally:
            ended.set()

    async with reader_fixture(tmp_path, handler, timeout=0.05) as reader:
        with pytest.raises(ConnectionProblem) as error:
            await reader.get(custom_resource(), "one", "team")
        assert error.value.state is ConnectionState.TIMEOUT
    await asyncio.wait_for(ended.wait(), 1)


@pytest.mark.asyncio
async def test_table_watch_decodes_headers_once_and_preserves_full_changed_objects(tmp_path):
    resource = custom_resource()
    ready = asyncio.Event()
    observations = []

    async def handler(request):
        assert "as=Table" in request.headers["Accept"]
        assert request.query["includeObject"] == "Object"
        if "watch" not in request.query:
            return web.json_response(server_table(custom_item()))
        changed = custom_item(rv="modified")
        changed["spec"]["level"] = 8
        first = server_table(changed)
        first["rows"][0]["cells"][1] = 8
        second = server_table(custom_item("two", uid="owned-two", rv="added"), headers=False)
        return web.Response(
            body=frame({"type": "MODIFIED", "object": first})
            + frame({"type": "ADDED", "object": second})
        )

    async def sink(update):
        observations.append(update)
        if update.snapshot and len(update.snapshot.items) == 2:
            ready.set()

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        task = asyncio.create_task(ListWatch(reader).run(resource, "team", sink))
        try:
            await asyncio.wait_for(ready.wait(), 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        final = next(
            update.snapshot
            for update in reversed(observations)
            if update.snapshot and len(update.snapshot.items) == 2
        )
        assert final.resource_version == "added"
        assert final.items[0].manifest["spec"]["level"] == 8
        assert final.items[0].server.cells[1] == 8
        assert final.columns[1].type == "integer"
        assert reader.uses_tables(resource)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [406, 415, "missing-headers", "partial"])
async def test_unsupported_table_watch_reopens_after_plain_json_relist(tmp_path, failure):
    ready = asyncio.Event()
    requests = []
    observations = []

    async def handler(request):
        table = "as=Table" in request.headers["Accept"]
        watch = "watch" in request.query
        requests.append((table, watch))
        if not watch:
            return web.json_response(
                server_table(custom_item())
                if table
                else custom_collection(custom_item(), rv="raw-list")
            )
        if table:
            if isinstance(failure, int):
                return web.Response(status=failure)
            body = server_table(custom_item(rv="unsupported"), headers=failure != "missing-headers")
            if failure == "partial":
                body["rows"][0]["object"]["kind"] = "PartialObjectMetadata"
            return web.Response(body=frame({"type": "MODIFIED", "object": body}))
        assert request.query["resourceVersion"] == "raw-list"
        return web.Response(
            body=frame({"type": "MODIFIED", "object": custom_item(rv="raw-change")})
        )

    async def sink(update):
        observations.append(update)
        if update.snapshot and update.snapshot.resource_version == "raw-change":
            ready.set()

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        task = asyncio.create_task(ListWatch(reader).run(custom_resource(), "team", sink))
        try:
            await asyncio.wait_for(ready.wait(), 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert requests[:4] == [(True, False), (True, True), (False, False), (False, True)]
        final = next(
            u.snapshot
            for u in reversed(observations)
            if u.snapshot and u.snapshot.resource_version == "raw-change"
        )
        assert final.columns == () and final.items[0].server is None
        assert not reader.uses_tables(custom_resource())
        assert any(u.status is SyncStatus.LOADING and u.snapshot for u in observations)


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_actual_table_parser_thread(tmp_path, monkeypatch):
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    original = TableDecoder.records

    def held(self, *args, **kwargs):
        started.set()
        try:
            assert release.wait(3)
            return original(self, *args, **kwargs)
        finally:
            ended.set()

    monkeypatch.setattr(TableDecoder, "records", held)

    async def handler(request):
        return web.json_response(server_table(custom_item()))

    async with reader_fixture(tmp_path, handler, timeout=3) as base:
        reader = ResourceReader(base.session, tables=True)
        task = asyncio.create_task(reader.list(custom_resource(), "team"))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not ended.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert ended.is_set()


@pytest.mark.asyncio
async def test_owned_parser_returns_and_retrieves_a_late_failure_after_cancellation():
    assert await parse_owned(lambda: "owned") == "owned"
    started, release = threading.Event(), threading.Event()

    def failure():
        started.set()
        assert release.wait(3)
        raise AppError("owned parser failure")

    task = asyncio.create_task(parse_owned(failure))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0.01)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_mid_collection_plain_response_discards_table_pages_and_restarts(tmp_path):
    requests = []

    async def handler(request):
        table = "as=Table" in request.headers["Accept"]
        token = request.query.get("continue", "")
        requests.append((table, token))
        if table and not token:
            return web.json_response(server_table(custom_item("discarded"), token="next"))
        if table:
            return web.json_response(custom_collection(custom_item("also-discarded")))
        return web.json_response(custom_collection(custom_item("replacement"), rv="new-version"))

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        result = await reader.list(custom_resource(), "team", page_size=1)
        assert requests == [(True, ""), (True, "next"), (False, "")]
        assert [record.name for record in result.items] == ["replacement"]
        assert result.resource_version == "new-version" and not result.columns
        assert result.items[0].server is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["expired", "repeat", "changed-version", "wrong-scope", "wrong-type", "memory"]
)
async def test_table_pagination_retains_atomicity_identity_and_metadata_bounds(
    tmp_path, monkeypatch, fault
):
    requests = []

    async def handler(request):
        token = request.query.get("continue", "")
        requests.append(token)
        if fault == "expired" and token and len(requests) == 2:
            return web.Response(status=410)
        if fault == "expired" and len(requests) > 2:
            return web.json_response(server_table(custom_item("replacement"), rv="new"))
        obj = custom_item("two" if token else "one", uid="two" if token else "one")
        if fault == "wrong-scope":
            obj["metadata"]["namespace"] = "elsewhere"
        if fault == "wrong-type":
            obj["kind"] = "Different"
        rv = "different" if token and fault == "changed-version" else "original"
        return web.json_response(
            server_table(obj, rv=rv, token="next" if not token or fault == "repeat" else "")
        )

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        if fault == "memory":
            monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 400)
        if fault == "expired":
            result = await reader.list(custom_resource(), "team")
            assert requests == ["", "next", ""]
            assert result.resource_version == "new"
            assert [record.name for record in result.items] == ["replacement"]
        else:
            with pytest.raises(ConnectionProblem) as error:
                await reader.list(custom_resource(), "team")
            assert error.value.state is ConnectionState.API_ERROR
        # Invalid full-object identity and memory are API errors, never fallback.
        assert reader.uses_tables(custom_resource())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "get"])
async def test_repeated_cancellation_drains_table_parsing_for_each_read(
    tmp_path, monkeypatch, method
):
    started, release, ended = threading.Event(), threading.Event(), threading.Event()
    original = TableDecoder.records

    def held(self, *args, **kwargs):
        started.set()
        try:
            assert release.wait(3)
            return original(self, *args, **kwargs)
        finally:
            ended.set()

    monkeypatch.setattr(TableDecoder, "records", held)

    async def handler(request):
        return web.json_response(server_table(custom_item()))

    async with reader_fixture(tmp_path, handler, timeout=3) as base:
        reader = ResourceReader(base.session, tables=True)
        read = (
            reader.get(custom_resource(), "one", "team")
            if method == "get"
            else reader.list(custom_resource(), "team")
        )
        task = asyncio.create_task(read)
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done() and not ended.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert ended.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["renew", "plain-event", "permission"])
async def test_table_watch_renews_headers_and_preserves_original_errors(tmp_path, mode):
    ready = asyncio.Event()
    requests, observations = [], []
    clock = Clock()

    async def handler(request):
        watch = "watch" in request.query
        assert "as=Table" in request.headers["Accept"]
        requests.append(watch)
        if not watch:
            return web.json_response(server_table(custom_item()))
        if mode == "permission":
            return web.Response(body=frame(error_event(403)))
        number = requests.count(True)
        obj = custom_item(rv=f"event-{number}")
        if mode == "plain-event":
            return web.Response(body=frame({"type": "MODIFIED", "object": obj}))
        # Every opened stream starts with headers; the next stream may change
        # the printer definition while still describing the same full object.
        table = server_table(obj)
        if number > 1:
            table["columnDefinitions"][1]["name"] = "Changed on renewal"
        return web.Response(body=frame({"type": "MODIFIED", "object": table}))

    async def sink(update):
        observations.append(update)
        if update.event and (mode != "renew" or update.snapshot.resource_version == "event-2"):
            ready.set()

    async with reader_fixture(tmp_path, handler) as base:
        reader = ResourceReader(base.session, tables=True)
        task = asyncio.create_task(
            ListWatch(reader, sleep=clock.sleep, jitter=lambda: 0, monotonic=clock.monotonic).run(
                custom_resource(), "team", sink
            )
        )
        try:
            if mode == "permission":
                with pytest.raises(HttpProblem) as error:
                    await asyncio.wait_for(task, 2)
                assert error.value.status == 403
                assert requests == [False, True]
                assert observations[-1].status is SyncStatus.FAILED
            else:
                await asyncio.wait_for(ready.wait(), 2)
                final = next(
                    update.snapshot
                    for update in reversed(observations)
                    if update.event
                    and (mode != "renew" or update.snapshot.resource_version == "event-2")
                )
                if mode == "renew":
                    assert final.columns[1].name == "Changed on renewal"
                    assert requests.count(False) == 1
                else:
                    assert not final.columns and final.items[0].server is None
            assert reader.uses_tables(custom_resource())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
