"""Coalesce observations through one owned render task and actual resume events."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from kuberich.ui.controllers.base import RenderOutcome, RenderRequest
from kuberich.ui.controllers.registry import ViewRegistry
from kuberich.ui.foreground import ForegroundGate


class RenderCoordinator:
    def __init__(
        self,
        foreground: ForegroundGate,
        views: ViewRegistry,
        capture: Callable[[], RenderRequest],
        publish: Callable[[RenderRequest, RenderOutcome], None],
        failed: Callable[[Exception], None],
    ) -> None:
        self.foreground, self.views = foreground, views
        self.capture, self.publish, self.failed = capture, publish, failed
        self._ready = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def active_count(self) -> int:
        """Unfinished render ownership, including cancellation drainage."""
        return int(self._task is not None and not self._task.done())

    def request(self) -> None:
        if not self._closed:
            self._ready.set()

    def start(self) -> None:
        if not self._closed and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self._ready.wait()
                if not await self.foreground.wait() or self._closed:
                    return
                self._ready.clear()
                request = self.capture()
                driver = self.views.resolve(request.route)
                await self.views.retire_inactive(request.route)
                outcome = await driver.render(request)
                if outcome.applied:
                    self.publish(request, outcome)
        except Exception as error:
            self.failed(error)

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is None:
            return
        task.cancel()
        cancelled = False
        owner = asyncio.current_task()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled |= owner is not None and owner.cancelling() > 0
        with suppress(asyncio.CancelledError):
            task.result()
        self._task = None
        if cancelled:
            raise asyncio.CancelledError
