"""Public cleanup drainage cannot abandon a child or hide its terminal result."""

import asyncio

import pytest

from kuberich.services.ownership import finish_owned


@pytest.mark.asyncio
async def test_repeated_caller_cancellation_cannot_cancel_or_abandon_the_owned_child():
    started, release, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def child():
        started.set()
        try:
            await release.wait()
            return "owned-result"
        finally:
            ended.set()

    operation = asyncio.create_task(child())
    await started.wait()
    closing = asyncio.create_task(finish_owned(operation))
    await asyncio.sleep(0)
    for _ in range(3):
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done() and not operation.done() and not ended.is_set()
    release.set()
    assert await closing is None
    assert ended.is_set() and operation.result() == "owned-result"


@pytest.mark.asyncio
async def test_a_completed_child_result_is_retrieved_without_replacing_the_owner_contract():
    future = asyncio.get_running_loop().create_future()
    future.set_result(42)
    assert await finish_owned(future) is None
    assert future.result() == 42


@pytest.mark.asyncio
async def test_owned_child_failure_and_cancellation_are_propagated():
    future = asyncio.get_running_loop().create_future()
    future.set_exception(RuntimeError("owned-failure"))
    with pytest.raises(RuntimeError, match="owned-failure"):
        await finish_owned(future)
    waiting = asyncio.get_running_loop().create_future()
    closing = asyncio.create_task(finish_owned(waiting))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing


@pytest.mark.asyncio
async def test_an_owner_can_reraise_its_original_cancellation_after_drainage():
    entered, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def cleanup():
        await release.wait()
        drained.set()

    async def owner():
        owned = asyncio.create_task(cleanup())
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await finish_owned(owned)
            raise

    task = asyncio.create_task(owner())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not task.done() and not drained.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert drained.is_set()
