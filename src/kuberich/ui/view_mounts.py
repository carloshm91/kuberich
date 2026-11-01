"""Own deferred DOM registration of the workspace's existing resource tables."""

import asyncio
from collections.abc import Awaitable, Callable

from textual.app import App
from textual.widget import Widget


async def wait_for_mount(completion: Awaitable[None]) -> None:
    """Wait for native Textual registration without changing its lifecycle."""
    await completion


async def _drain[T](completion: asyncio.Future[T]) -> T:
    while not completion.done():
        try:
            await asyncio.shield(completion)
        except asyncio.CancelledError:
            continue
    return completion.result()


class ViewMounts:
    """Mount inactive known tables after paint, preserving synchronous routing.

    The supplied tables keep their normal, nonblocking Textual Mount handlers.
    Only this owner's completion waits are cancellable; arbitrary third-party
    Mount handlers are outside this adapter's contract.
    """

    def __init__(
        self,
        app: App[None],
        container: Widget,
        tables: tuple[Widget, ...],
        anchor: Widget,
        on_error: Callable[[Exception], None],
        *,
        wait: Callable[[Awaitable[None]], Awaitable[None]] = wait_for_mount,
    ) -> None:
        self._app, self._container, self._tables, self._anchor = app, container, tables, anchor
        self._on_error, self._wait = on_error, wait
        self._started = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._completions: list[asyncio.Task[None]] = []
        self._native: list[asyncio.Future[None]] = []
        self._closing = False
        self._failure: Exception | None = None

    def ensure(self, table: Widget) -> None:
        """Register a selected table before its synchronous configure/focus."""
        if table not in self._tables:
            raise ValueError("Only the workspace's owned resource tables may be registered.")
        if self._closing or not self._app.is_running:
            return
        if self._app.is_mounted(table):
            return
        completion = asyncio.ensure_future(self._container.mount(table, before=self._anchor))
        self._native.append(completion)
        owned = asyncio.create_task(self._complete(completion))
        self._completions.append(owned)
        owned.add_done_callback(self._finished)

    async def _complete(self, completion: asyncio.Future[None]) -> None:
        try:
            await self._wait(asyncio.shield(completion))
        finally:
            # Cancelling the owned wait must not cancel or abandon Textual's
            # native completion. Its concrete table handlers never block.
            await _drain(completion)

    def start(self) -> None:
        """Schedule work without returning an awaitable to after-refresh."""
        if self._closing or self._task is not None or not self._app.is_running:
            return
        self._task = asyncio.create_task(self._mount_all())
        self._task.add_done_callback(self._finished)
        self._started.set()

    async def _mount_all(self) -> None:
        # Python's eager task factory can start this coroutine inline. Yield
        # before any registration so the refresh callback itself stays cheap.
        await asyncio.sleep(0)
        for table in self._tables:
            if self._closing or not self._app.is_running:
                raise asyncio.CancelledError
            self.ensure(table)
            # Let pending input and shutdown run between registrations.
            await asyncio.sleep(0)
        await asyncio.gather(*self._completions)

    def _finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if self._failure is None and isinstance(error, Exception):
            self._failure = error
            self._on_error(error)

    async def wait_ready(self) -> None:
        """Keep connection preparation behind paint and complete registration."""
        await self._started.wait()
        if self._closing:
            raise asyncio.CancelledError
        assert self._task is not None
        await asyncio.shield(self._task)
        if self._closing:
            raise asyncio.CancelledError

    def stop(self) -> None:
        """Prevent any further registration before synchronous App.exit."""
        self._closing = True
        self._started.set()
        if self._task is not None:
            self._task.cancel()
        for completion in self._completions:
            completion.cancel()

    async def close(self) -> None:
        """Cancel and drain every owner; Textual owns widget teardown."""
        self.stop()
        tasks = [*self._completions]
        if self._task is not None:
            tasks.append(self._task)
        await _drain(asyncio.gather(*tasks, return_exceptions=True))
        # A task cancelled before its coroutine starts cannot run its finally
        # block. Retain and drain native futures independently of those owners.
        await _drain(asyncio.gather(*self._native, return_exceptions=True))
