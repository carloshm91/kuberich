"""Finish an already-owned asynchronous operation before releasing its owner."""

import asyncio


async def finish_owned[T](task: asyncio.Future[T]) -> None:
    """Drain through repeated caller cancellation and retrieve the child's result.

    Caller cancellation cannot cancel this child. Callers that caught an
    original cancellation re-raise it after their owned cleanup is finished.
    A child failure or cancellation still propagates when its result is read.
    """
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()
