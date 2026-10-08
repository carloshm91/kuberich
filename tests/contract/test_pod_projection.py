"""Owned decoding jobs are incremental, responsive and drained on cancellation."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.services.pods import PodProjection
from tests.support.pods import pod, snapshot
from tests.support.workspace import wait_for


@pytest.mark.asyncio
async def test_projection_reuses_unchanged_records_and_prunes_removed_uids():
    projection = PodProjection()
    original = snapshot(pod("first"), pod("second"))
    rows = await projection.project(original)
    changed = snapshot(pod("first", restarts=12), pod("second", uid="replacement"))
    newer = replace(changed, items=(changed.items[0], original.items[1], changed.items[1]))
    updates = await projection.project(newer)
    assert updates[0].restarts == 12 and updates[1] is rows[1]
    assert updates[2].uid == "replacement" and updates[2] is not rows[1]
    final = await projection.project(replace(newer, items=(newer.items[2],)))
    assert final == (updates[2],) and len(projection._cache) == 1
    assert await projection.project(None) == () and not projection._cache
    assert await projection.project(original)
    assert (
        await projection.project(
            replace(original, resource=replace(original.resource, name="namespaces"))
        )
        == ()
    )
    assert (
        await projection.project(
            replace(original, resource=replace(original.resource, group="other"))
        )
        == ()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancellation_waits_for_owned_decode_thread(tmp_path, monkeypatch, fail):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    projection = PodProjection()

    def blocked(value):
        started.set()
        try:
            assert release.wait(5)
            if fail:
                raise RuntimeError("owned-decoding-failure")
            return ()
        finally:
            finished.set()

    monkeypatch.setattr(projection, "_project", blocked)
    task = asyncio.create_task(projection.project(snapshot(pod())))
    try:
        await wait_for(started.is_set)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and not finished.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_projection_failure_is_owned_and_visible(monkeypatch):
    projection = PodProjection()

    def broken(value):
        raise RuntimeError("owned-projection-error")

    monkeypatch.setattr(projection, "_project", broken)
    with pytest.raises(RuntimeError, match="owned-projection-error"):
        await projection.project(snapshot(pod()))
