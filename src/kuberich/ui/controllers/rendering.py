"""Coalesce observations through one owned render task and actual resume events."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceScope
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
        *,
        recover: Callable[[RenderRequest, Exception | None], None] | None = None,
    ) -> None:
        self.foreground, self.views = foreground, views
        self.capture, self.publish, self.failed = capture, publish, failed
        self.recover = recover
        self._blocked: dict[ViewRoute, tuple[str | None, ResourceScope | None]] = {}
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

    def retry(self) -> None:
        """Retry only the current view; watch observations cannot cause an error loop."""
        if not self._closed:
            self._blocked.pop(self.capture().route, None)
            self.request()

    def is_failed(self, request: RenderRequest) -> bool:
        return request.route in self._blocked and self._blocked[request.route] == (
            request.observation.context,
            request.observation.scope,
        )

    def fail(self, request: RenderRequest, error: Exception) -> None:
        """Isolate a current observation's presentation fault without retaining its frames."""
        if self._closed or not request.current():
            return
        if self.recover is None:
            self.failed(error)
            return
        self._blocked[request.route] = (request.observation.context, request.observation.scope)
        self.recover(request, error)

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
                if self.is_failed(request):
                    if self.recover is not None:
                        self.recover(request, None)
                    continue
                self._blocked.pop(request.route, None)
                if self.recover is not None:
                    self.recover(request, None)
                # Ownership failures remain fatal; only view construction,
                # projection and rendering are recoverable here.
                await self.views.retire_inactive(request.route)
                try:
                    driver = self.views.resolve(request.route)
                    outcome = await driver.render(request)
                    if outcome.applied:
                        self.publish(request, outcome)
                except Exception as error:
                    if self.recover is None:
                        raise
                    self.fail(request, error)
                    continue
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
        self._blocked.clear()
        if cancelled:
            raise asyncio.CancelledError
