"""Observe the real asyncio owners entering a public coroutine boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any


class CoroutineCalls:
    """Record actual callers without reading tasks from application internals."""

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[Any]] = []

    @property
    def latest(self) -> asyncio.Task[Any] | None:
        return self.tasks[-1] if self.tasks else None

    def clear(self) -> None:
        self.tasks.clear()

    def capture(self) -> asyncio.Task[Any]:
        task = asyncio.current_task()
        assert task is not None
        if not self.tasks or self.tasks[-1] is not task:
            self.tasks.append(task)
        return task

    def observe(self, operation: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(operation)
        async def observed(*args: Any, **kwargs: Any) -> Any:
            self.capture()
            return await operation(*args, **kwargs)

        return observed
