"""Drain fixture relays before cancellation can release their owned sockets."""

import asyncio
from collections.abc import Sequence
from contextlib import suppress


async def close_relays(
    tasks: Sequence[asyncio.Task[None]], streams: Sequence[asyncio.StreamWriter | None]
) -> None:
    async def cleanup() -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for stream in streams:
            if stream is not None:
                stream.close()
                with suppress(ConnectionError):
                    await stream.wait_closed()

    finishing = asyncio.create_task(cleanup())
    try:
        await asyncio.shield(finishing)
    except asyncio.CancelledError:
        while not finishing.done():
            try:
                await asyncio.shield(finishing)
            except asyncio.CancelledError:
                continue
        await finishing
        raise
