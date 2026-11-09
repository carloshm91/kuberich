"""Generation ownership and explicit stale rows for finite Helm collections."""

import asyncio

import pytest

from kuberich.domain.helm import HelmList, HelmProblem
from kuberich.errors import AppError
from kuberich.services.helm_workspace import HelmWorkspace
from tests.support.helm import release, request


@pytest.mark.asyncio
async def test_initial_collection_and_refresh_failure_retain_rows_under_new_request():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)
    publications = []

    async def success(_):
        return HelmList((release(),), True)

    workspace.start(captured, success, publications.append)
    assert publications[-1].collecting
    await workspace.task
    assert not publications[-1].collecting and publications[-1].listing.releases == (release(),)
    refreshed = workspace.prepare(captured.scope)
    assert refreshed.generation > captured.generation and not workspace.current(captured)
    await workspace.stop()

    async def fail(_):
        raise HelmProblem("forbidden", "Storage access denied.")

    workspace.start(refreshed, fail, publications.append)
    await workspace.task
    assert publications[-1].problem.kind == "forbidden"
    assert publications[-1].problem.__traceback__ is None
    assert publications[-1].listing.releases == (release(),)
    await workspace.stop()
    assert not workspace.collecting


@pytest.mark.asyncio
async def test_obsolete_producer_cannot_publish_even_if_it_suppresses_cancellation():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)
    started, release_read = asyncio.Event(), asyncio.Event()
    publications = []

    async def stubborn(_):
        started.set()
        try:
            await release_read.wait()
        except asyncio.CancelledError:
            await release_read.wait()
        return HelmList((release(),), True)

    workspace.start(captured, stubborn, publications.append)
    await started.wait()
    workspace.invalidate()
    release_read.set()
    await workspace.stop()
    assert len(publications) == 1 and workspace.task is None
    await workspace.stop()


@pytest.mark.asyncio
async def test_start_requires_current_request_and_prior_producer_drain():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)

    async def collect(_):
        return HelmList((), True)

    with pytest.raises(AppError, match="stale"):
        workspace.start(request(), collect, lambda _: None)
    workspace.start(captured, collect, lambda _: None)
    with pytest.raises(AppError, match="Drain"):
        workspace.start(captured, collect, lambda _: None)
    await workspace.stop()
    assert workspace.snapshot.listing is None


@pytest.mark.asyncio
async def test_app_error_is_a_failure_not_successful_empty_listing():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)

    async def fail(_):
        raise AppError("Safe generic failure.")

    workspace.start(captured, fail, lambda _: None)
    await workspace.task
    assert workspace.snapshot.problem.kind == "unavailable" and workspace.snapshot.listing is None
    await workspace.stop()


@pytest.mark.asyncio
async def test_stop_drains_through_caller_cancellation():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)
    started, cleanup = asyncio.Event(), asyncio.Event()

    async def collect(_):
        started.set()
        try:
            await asyncio.Future()
        finally:
            await cleanup.wait()

    workspace.start(captured, collect, lambda _: None)
    await started.wait()
    stopping = asyncio.create_task(workspace.stop())
    await asyncio.sleep(0)
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done()
    cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert workspace.task is None


@pytest.mark.asyncio
async def test_concurrent_stops_share_drained_owner_and_scope_departure_drops_rows():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)
    started, cleanup = asyncio.Event(), asyncio.Event()

    async def collect(_):
        started.set()
        try:
            await asyncio.Future()
        finally:
            await cleanup.wait()

    workspace.start(captured, collect, lambda _: None)
    await started.wait()
    first = asyncio.create_task(workspace.stop())
    await asyncio.sleep(0)
    second = asyncio.create_task(workspace.stop())
    cleanup.set()
    await asyncio.gather(first, second)
    assert workspace.task is None
    other = workspace.prepare(request(namespace="other").scope)
    assert workspace.snapshot.request == other and workspace.snapshot.listing is None


@pytest.mark.asyncio
async def test_repeated_invalidate_and_stop_cannot_interrupt_producer_cleanup():
    workspace = HelmWorkspace()
    captured = workspace.prepare(request().scope)
    started, cleanup_started, release_cleanup, cleanup_finished = (
        asyncio.Event() for _ in range(4)
    )

    async def collect(_):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_finished.set()

    workspace.start(captured, collect, lambda _: None)
    await started.wait()
    workspace.invalidate()
    await cleanup_started.wait()
    workspace.invalidate()
    first = asyncio.create_task(workspace.stop())
    second = asyncio.create_task(workspace.stop())
    await asyncio.sleep(0)
    assert not first.done() and not second.done() and not cleanup_finished.is_set()
    assert workspace.task.cancelling() == 1
    release_cleanup.set()
    await asyncio.gather(first, second)
    assert cleanup_finished.is_set() and workspace.task is None
