"""Owned HTTP proves bounded partial lists, progress and LIST/WATCH selectors."""

import asyncio
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.logs import LogOptions
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import api_resource
from kuberich.domain.watches import EventType, SyncStatus, WatchState, watch_event
from kuberich.errors import AppError
from kuberich.services import resources
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.watches import ListWatch
from kuberich.services.workspace import WorkspaceService
from tests.contract.test_aggregate_logs import finish
from tests.contract.test_inspection import make_service
from tests.support.aggregate_logs import AggregateApi
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection, descriptor, item, pod_resource, reader_fixture
from tests.support.tables import custom_item, custom_resource, server_table
from tests.support.watches import event
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.unit.test_inspection import event as inspection_event


class ObservationComplete(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("name,kind", [("pods", "Pod"), ("services", "Service")])
async def test_native_payload_and_unvalidated_query_refusals_happen_before_http(
    tmp_path, name, kind
):
    async def handler(request):
        pytest.fail("Invalid query reached HTTP")

    async def sink(update):
        pytest.fail("Invalid query reached the view")

    resource = api_resource("v1", descriptor(name, kind=kind))
    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(AppError, match="validated"):
            await reader.list(resource, "team", query={})
        with pytest.raises(AppError, match="full objects"):
            await reader.list(resource, "team", query=ResourceQuery(compact=True))
        with pytest.raises(AppError, match="full objects"):
            await ListWatch(reader, query=ResourceQuery(compact=True)).run(resource, "team", sink)
        with pytest.raises(AppError, match="validated"):
            async for _ in reader.session.watch_bytes(resource.path("team"), "rv", query={}):
                pytest.fail("Invalid watch query opened a stream")
        for kwargs in ({"query": {}}, {"progress": "yes"}):
            with pytest.raises(AppError, match="validated"):
                ListWatch(reader, **kwargs)


@pytest.mark.asyncio
async def test_incomplete_inspection_events_remain_explicit_beside_full_object_documents(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 1)

    async def handler(request):
        return web.json_response(
            pod("api")
            if request.path.endswith("/api")
            else collection(inspection_event().manifest, token="more")
        )

    async with reader_fixture(tmp_path, handler) as reader:
        result = await make_service(reader).load()
    assert "spec:" in result.documents.yaml and "BackOff" in result.documents.events
    assert result.events_error == "Events are INCOMPLETE; only retained events are shown."


@pytest.mark.asyncio
async def test_aggregate_membership_warning_survives_reader_and_source_notices(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 1)
    api = AggregateApi(count=2)
    notices = []
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner = api.owner(reader)

        async def retain(source, number, line):
            owner.require_source(source, number)

        task = asyncio.create_task(owner.run(LogOptions(), retain, notices.append))
        try:
            await wait_for(lambda: api.active == 1)
            await wait_for(lambda: any("Reader opened" in message for message in notices))
            assert all(
                "INCOMPLETE pods membership" in message
                for message in notices
                if "Reader opened" in message or "Sources updated" in message
            )
            assert len(owner.states) == 1
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_fifty_thousand_available_objects_retain_only_the_production_prefix_and_live_state(
    tmp_path,
):
    requests = []

    async def handler(request):
        size = int(request.query["limit"])
        offset = int(request.query["continue"] or 0)
        requests.append(offset)
        following = min(offset + size, 50_000)
        payload = collection(
            *(item(f"pod-{index:05}") for index in range(offset, following)),
            token=str(following) if following < 50_000 else "",
        )
        payload["metadata"]["remainingItemCount"] = 50_000 - following
        return web.json_response(payload)

    async with reader_fixture(tmp_path, handler) as reader:
        snapshot = await reader.list(pod_resource(), "team", page_size=500)
    assert requests == list(range(0, 10_000, 500))
    assert len(snapshot.items) == 10_000 and snapshot.collection.limited
    assert snapshot.collection.retained_bytes <= 64 * 1024 * 1024
    state = WatchState(snapshot)
    for index in range(100):
        update = event(
            "MODIFIED" if index % 2 == 0 else "ADDED",
            "pod-00000" if index % 2 == 0 else f"unretained-{index}",
            f"rv-{index}",
        )
        state.apply(watch_event(pod_resource(), update, "team"))
        assert len(state.snapshot.items) == 10_000
        assert state.snapshot.collection.retained_bytes <= 64 * 1024 * 1024
    assert state.resource_version == "rv-99" and not state.snapshot.collection.complete
    assert max(state.replay_sizes) <= 1024


@pytest.mark.asyncio
async def test_page_progress_preserves_first_rv_and_stops_at_the_retained_cap(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 3)
    calls, progress = [], []
    query = ResourceQuery("app in (api,worker)", "metadata.name!=retired")

    async def handler(request):
        calls.append(dict(request.query))
        number = len(calls)
        return web.json_response(
            collection(item(str(number)), rv="opaque/first", token=f"page-{number}")
        )

    async def observe(snapshot):
        progress.append(snapshot)

    async with reader_fixture(tmp_path, handler) as reader:
        snapshot = await reader.list(
            pod_resource(), "team", page_size=1, query=query, progress=observe
        )
    assert [value["continue"] for value in calls] == ["", "page-1", "page-2"]
    assert all(
        value["labelSelector"] == query.label_selector
        and value["fieldSelector"] == query.field_selector
        for value in calls
    )
    assert len(snapshot.items) == 3 and snapshot.resource_version == "opaque/first"
    assert snapshot.collection.limited and not snapshot.collection.complete
    assert [len(value.items) for value in progress] == [1, 2]
    assert all(not value.collection.complete and not value.collection.limited for value in progress)
    assert progress[0].items == snapshot.items[:1]


@pytest.mark.asyncio
async def test_server_ignoring_page_limit_does_not_materialize_rows_beyond_the_prefix(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 2)

    async def handler(request):
        # The unread suffix is intentionally not a valid ResourceRecord. A
        # retained prefix is explicit, never advertised as a complete list.
        return web.json_response(collection(item("one"), item("two"), {"unread": True}))

    async with reader_fixture(tmp_path, handler) as reader:
        snapshot = await reader.list(pod_resource(), "team", page_size=1)
    assert [record.name for record in snapshot.items] == ["one", "two"]
    assert snapshot.collection.limited and not snapshot.collection.complete


@pytest.mark.asyncio
async def test_capped_list_watch_uses_same_selectors_and_collection_rv_then_updates_retained_uid(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 1)
    requests, updates = [], []
    query = ResourceQuery("app=api", "metadata.namespace=team")

    async def handler(request):
        requests.append(dict(request.query))
        if "watch" in request.query:
            return await stable_watch(request, event("MODIFIED", version="retained-update"))
        return web.json_response(collection(item(), rv="opaque/list", token="unread-page"))

    async def observe(update):
        updates.append(update)
        if update.event is not None:
            raise ObservationComplete

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(ObservationComplete):
            await ListWatch(reader, query=query, progress=True).run(pod_resource(), "team", observe)
    assert len(requests) == 2 and requests[1]["resourceVersion"] == "opaque/list"
    assert all(
        value["labelSelector"] == "app=api" and value["fieldSelector"] == "metadata.namespace=team"
        for value in requests
    )
    assert updates[-1].status is SyncStatus.LIVE and updates[-1].problem is None
    assert updates[-1].snapshot.items[0].resource_version == "retained-update"
    assert not updates[-1].snapshot.collection.complete


@pytest.mark.asyncio
async def test_compact_table_negotiation_is_opt_in_and_plain_json_fallback_remains_full(tmp_path):
    queries = []
    use_json = False

    async def handler(request):
        queries.append(dict(request.query))
        obj = custom_item()
        if use_json:
            return web.json_response(
                {
                    "apiVersion": "owned.example.test/v1",
                    "metadata": {"resourceVersion": "full"},
                    "items": [obj],
                }
            )
        if request.query.get("includeObject") == "Metadata":
            obj = {
                "apiVersion": "meta.k8s.io/v1",
                "kind": "PartialObjectMetadata",
                "metadata": obj["metadata"],
            }
        return web.json_response(server_table(obj))

    async with reader_fixture(tmp_path, handler) as owner:
        reader = ResourceReader(owner.session, tables=True)
        full = await reader.list(custom_resource(), "team")
        compact = await reader.list(custom_resource(), "team", query=ResourceQuery(compact=True))
        assert not full.items[0].metadata_only and full.items[0].manifest["spec"]
        assert compact.items[0].metadata_only and "spec" not in compact.items[0].manifest
        assert compact.items[0].server == full.items[0].server
        assert compact.items[0].size_bytes < full.items[0].size_bytes
        use_json = True
        fallback = await reader.list(custom_resource(), "team", query=ResourceQuery(compact=True))
        assert not fallback.items[0].metadata_only and fallback.items[0].manifest["spec"]
    assert [value.get("includeObject") for value in queries] == ["Object", "Metadata", "Metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("compact", [False, True])
async def test_filtered_table_collection_exhausts_an_empty_terminal_page(tmp_path, compact):
    calls, progress = [], []
    query = ResourceQuery("role=selected", "metadata.name!=omitted", compact)

    async def handler(request):
        calls.append(dict(request.query))
        page = len(calls)
        values = []
        if page < 3:
            value = custom_item(str(page), uid=f"uid-{page}")
            if compact:
                value = {
                    "apiVersion": "meta.k8s.io/v1",
                    "kind": "PartialObjectMetadata",
                    "metadata": value["metadata"],
                }
            values.append(value)
        return web.json_response(
            server_table(*values, rv="filtered/first", token=f"next-{page}" if page < 3 else "")
        )

    async def observe(snapshot):
        progress.append(snapshot)

    async with reader_fixture(tmp_path, handler) as owner:
        reader = ResourceReader(owner.session, tables=True)
        snapshot = await reader.list(
            custom_resource(), "team", page_size=1, query=query, progress=observe
        )
    assert [call["continue"] for call in calls] == ["", "next-1", "next-2"]
    assert all(
        call["labelSelector"] == "role=selected"
        and call["fieldSelector"] == "metadata.name!=omitted"
        and call["includeObject"] == ("Metadata" if compact else "Object")
        for call in calls
    )
    assert [row.uid for row in snapshot.items] == ["uid-1", "uid-2"]
    assert all(row.namespace == "team" and row.metadata_only == compact for row in snapshot.items)
    assert snapshot.collection.complete and not snapshot.collection.limited
    assert snapshot.collection.pages == 3 and snapshot.resource_version == "filtered/first"
    assert [len(update.items) for update in progress] == [1, 2]
    assert [update.collection.pages for update in progress] == [1, 2]
    assert all(
        not update.collection.complete
        and not update.collection.limited
        and update.resource_version == snapshot.resource_version
        and update.collection.retained_bytes == sum(row.size_bytes for row in update.items)
        for update in progress
    )
    assert snapshot.collection.retained_bytes == sum(row.size_bytes for row in snapshot.items)


@pytest.mark.asyncio
async def test_compact_table_watch_preserves_metadata_negotiation_query_and_real_uid(tmp_path):
    requests, updates = [], []
    stopped = asyncio.Event()
    query = ResourceQuery("app=api", "metadata.name=one", compact=True)

    async def handler(request):
        requests.append(dict(request.query))
        obj = custom_item(rv="watched" if "watch" in request.query else "listed")
        obj = {
            "apiVersion": "meta.k8s.io/v1",
            "kind": "PartialObjectMetadata",
            "metadata": obj["metadata"],
        }
        if "watch" in request.query:
            bookmark = server_table(obj)
            bookmark["rows"][0]["object"] = {"metadata": {"resourceVersion": "checkpoint"}}
            try:
                return await stable_watch(
                    request,
                    {"type": "BOOKMARK", "object": bookmark},
                    {"type": "MODIFIED", "object": server_table(obj)},
                )
            finally:
                stopped.set()
        return web.json_response(server_table(obj, rv="original-rv"))

    async def observe(update):
        updates.append(update)
        if update.event is not None and update.event.type is EventType.MODIFIED:
            raise ObservationComplete

    async with reader_fixture(tmp_path, handler) as owner:
        reader = ResourceReader(owner.session, tables=True)
        with pytest.raises(ObservationComplete):
            await ListWatch(reader, query=query).run(custom_resource(), "team", observe)
        await wait_for(stopped.is_set)
        assert not owner.session.api.rest_client.pool_manager.closed
    assert len(requests) == 2
    assert all(
        value["includeObject"] == "Metadata"
        and value["labelSelector"] == "app=api"
        and value["fieldSelector"] == "metadata.name=one"
        for value in requests
    )
    assert requests[1]["resourceVersion"] == "original-rv"
    assert [update.event.type for update in updates if update.event is not None] == [
        EventType.BOOKMARK,
        EventType.MODIFIED,
    ]
    assert updates[-1].snapshot.items[0].uid == "owned-one"
    assert updates[-1].snapshot.items[0].metadata_only
    assert updates[-1].snapshot.items[0].resource_version == "watched"


@pytest.mark.asyncio
async def test_query_replacement_invalidates_old_scope_and_recovers_a_complete_narrowed_list(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 1)
    reads = []

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        reads.append(dict(request.query))
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            collection(
                item(),
                rv="query-snapshot",
                token="" if "labelSelector" in request.query else "more",
            )
        )

    async with workspace_api(ns, handler) as url:
        workspace = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await workspace.connect("kuberich-test-one")
            await wait_for(lambda: workspace.store.observation.status.name == "LIVE")
            old = workspace.store.observation
            assert old.snapshot.collection.limited
            task = workspace.set_query(ResourceQuery("app=api"))
            assert workspace.store.observation.revision > old.revision
            assert workspace.store.observation.snapshot is None
            await task
            await wait_for(lambda: workspace.store.observation.status.name == "LIVE")
            current = workspace.store.observation
            assert current.scope.query == ResourceQuery("app=api")
            assert current.scope != old.scope and current.snapshot.collection.complete
            assert not workspace.store.apply(old.revision, old.scope, replace_update(old))
        finally:
            await workspace.close()
        assert workspace.ownership.close_complete and workspace.ownership.watch_count == 0
        assert workspace.sessions.client is None
    assert any(value.get("labelSelector") == "app=api" for value in reads)


def replace_update(view):
    from kuberich.domain.watches import SyncUpdate

    return SyncUpdate(SyncStatus.LIVE, replace(view.snapshot, resource_version="late-old-query"))


@pytest.mark.asyncio
async def test_progress_cancellation_closes_the_owned_list_without_reading_more_pages(tmp_path):
    entered, stopped = asyncio.Event(), asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(dict(request.query))
        return web.json_response(collection(item(), token="next"))

    async def progress(snapshot):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async with reader_fixture(tmp_path, handler) as reader:
        task = asyncio.create_task(reader.list(pod_resource(), "team", progress=progress))
        async with asyncio.timeout(3):
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stopped.is_set() and len(calls) == 1
