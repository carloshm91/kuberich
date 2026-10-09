"""Generic projection remains bound to its version and owns cancellation cleanup."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.domain.custom import CustomLayout
from kuberich.domain.resources import ResourceSnapshot
from kuberich.services.pods import CustomProjection
from tests.support.tables import custom_resource
from tests.unit.test_custom_layout import captured


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
