"""Generic projection remains bound to its version and owns cancellation cleanup."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.domain.custom import CustomLayout
from kuberich.domain.registry import order_resources
from kuberich.domain.resources import ResourceSnapshot, ServerColumn, resource_record
from kuberich.services.pods import CustomProjection
from tests.support.tables import custom_resource
from tests.unit.test_custom_layout import captured, observed_clock


@pytest.mark.asyncio
async def test_generic_projection_rejects_wrong_version_and_prunes_replaced_uids():
    resource = custom_resource()
    projection = CustomProjection(CustomLayout.build(resource, ()))
    record = captured((), ())
    snapshot = ResourceSnapshot(resource, "team", "owned/list", (record,))
    rows = await projection.project(snapshot)
    assert rows[0].uid == record.uid and (await projection.project(snapshot))[0] is rows[0]
    changed = replace(record, uid="replacement")
    assert (await projection.project(replace(snapshot, items=(changed,))))[0].uid == "replacement"
    assert record.uid not in projection._cache
    assert (
        await projection.project(replace(snapshot, resource=replace(resource, version="v1beta1")))
        == ()
    )
    assert not projection._cache
    assert await projection.project(None) == ()


@pytest.mark.asyncio
async def test_generic_projection_repeated_cancellation_drains_owned_worker(monkeypatch):
    resource = custom_resource()
    projection = CustomProjection(CustomLayout.build(resource, ()))
    entered, release = threading.Event(), threading.Event()
    original = projection._project

    def held(snapshot):
        entered.set()
        assert release.wait(5)
        return original(snapshot)

    monkeypatch.setattr(projection, "_project", held)
    task = asyncio.create_task(
        projection.project(ResourceSnapshot(resource, "team", "owned/list", (captured((), ()),)))
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await projection.project(None) == ()


@pytest.mark.asyncio
async def test_equal_dates_and_cached_order_survive_unrelated_object_updates(monkeypatch):
    advance = observed_clock(monkeypatch)
    resource = custom_resource()
    headers = (ServerColumn("Observed", "date"),)
    projection = CustomProjection(CustomLayout.build(resource, headers))
    records = tuple(captured(headers, ("2026-10-09T00:00:00Z",), name=name) for name in ("a", "b"))
    snapshot = ResourceSnapshot(resource, "team", "owned/list", records)
    before = await projection.project(snapshot)
    item = records[0].manifest
    item["metadata"]["annotations"] = {"owned.example.test/unrelated": "changed"}
    item["metadata"]["resourceVersion"] = "updated-version"
    updated = replace(resource_record(resource, item, "team"), server=records[0].server)
    advance()
    after = await projection.project(replace(snapshot, items=(updated, records[1])))
    assert after[1] is before[1] and after[0] is not before[0]
    assert after[0].values[2].sort == after[1].values[2].sort
    for descending in (False, True):
        assert [r.name for r in order_resources(before, 2, descending)] == ["a", "b"]
        assert [r.name for r in order_resources(after, 2, descending)] == ["a", "b"]
