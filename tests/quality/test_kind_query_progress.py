"""Owned HTTP preserves optional query and progress through the waiting reader."""

import pytest
from aiohttp import web

from kuberich.domain.resource_queries import ResourceQuery
from scripts.verify_aggregate_logs_kind import CrashWaitingReader
from tests.quality.test_aggregate_kind import UID, pod
from tests.support.resources import collection, pod_resource, reader_fixture


@pytest.mark.asyncio
async def test_waiting_reader_forwards_query_and_progress_before_and_after_capture(tmp_path):
    calls, updates = [], []
    waiting = pod()
    other = pod(uid="other", name="other")
    for value in (waiting, other):
        value["metadata"]["labels"] = {"app": "api"}

    async def handler(request):
        calls.append(dict(request.query))
        return web.json_response(
            collection(other, rv="snapshot/1")
            if request.query.get("continue")
            else collection(waiting, rv="snapshot/1", token="next")
        )

    async def progress(snapshot):
        updates.append(snapshot)

    query = ResourceQuery(label_selector="app=api", field_selector="metadata.namespace=team")
    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = CrashWaitingReader(reader.session, "team", UID, evidence)
        first = await selected.list(
            pod_resource(), "team", page_size=7, query=query, progress=progress
        )
        assert not selected.pending and first.items[0].manifest == waiting
        second = await selected.list(
            pod_resource(), "team", page_size=7, query=query, progress=progress
        )
        assert len(calls) == 4 and len(updates) == 2
        assert all(
            call["limit"] == "7"
            and call["labelSelector"] == "app=api"
            and call["fieldSelector"] == "metadata.namespace=team"
            for call in calls
        )
        assert all(
            update.resource_version == first.resource_version == second.resource_version
            for update in updates
        )
        assert all(
            not update.collection.complete and update.collection.pages == 1 for update in updates
        )
        assert first.collection.complete and second.collection.complete
        assert first.collection.pages == second.collection.pages == 2
        assert first.items[0].uid == second.items[0].uid == UID
