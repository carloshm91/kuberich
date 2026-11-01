"""Own an event-driven foreground boundary without polling or framework internals."""

import asyncio
from collections.abc import Callable


class ForegroundGate:
    def __init__(self, request_render: Callable[[], None]) -> None:
        self.request_render = request_render
        self._ready = asyncio.Event()
        self._closed = False

    @property
    def active(self) -> bool:
        return not self._closed and self._ready.is_set()

    @property
    def closed(self) -> bool:
        return self._closed

    def resume(self) -> None:
        if not self._closed:
            self._ready.set()
            self.request_render()

    def suspend(self) -> None:
        if not self._closed:
            self._ready.clear()

    async def wait(self) -> bool:
        await self._ready.wait()
        return not self._closed

    def close(self) -> None:
        self._closed = True
        self._ready.set()
