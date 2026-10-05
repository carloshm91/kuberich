"""Owned list/watch loop with pull backpressure and injectable retry time."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing

from kubetrol.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kubetrol.domain.resources import ApiResource
from kubetrol.domain.watches import (
    Recovery,
    SyncStatus,
    SyncUpdate,
    WatchEvent,
    WatchState,
    recovery,
    retry_delay,
    watch_event,
)
from kubetrol.errors import AppError
from kubetrol.services.resources import ResourceReader

Sink = Callable[[SyncUpdate], Awaitable[None]]


class _ConsumerFailure(Exception):
    def __init__(self, problem: ConnectionProblem) -> None:
        self.problem = problem


async def _emit(sink: Sink, update: SyncUpdate) -> None:
    try:
        await sink(update)
    except ConnectionProblem as problem:
        # Consumer failures are not transport failures and must not trigger retries.
        raise _ConsumerFailure(problem) from None


class ListWatch:
    def __init__(
        self,
        reader: ResourceReader,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reader = reader
        self.sleep = sleep
        self.jitter = jitter
        self.monotonic = monotonic

    async def _event(
        self, resource: ApiResource, payload: object, namespace: str | None
    ) -> WatchEvent:
        task = asyncio.create_task(asyncio.to_thread(watch_event, resource, payload, namespace))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        except AppError:
            raise ConnectionProblem(
                ConnectionState.API_ERROR, "Invalid Kubernetes watch event."
            ) from None

    async def run(self, resource: ApiResource, namespace: str | None, sink: Sink) -> None:
        if not {"list", "watch"} <= resource.verbs:
            raise AppError("Live resources require advertised list and watch support.")
        path = resource.path(namespace)
        state = None
        failures = 0
        await sink(SyncUpdate(SyncStatus.LOADING))
        while True:
            opened = None
            try:
                if state is None:
                    try:
                        state = WatchState(await self.reader.list(resource, namespace))
                    except AppError:
                        raise ConnectionProblem(
                            ConnectionState.API_ERROR,
                            "Invalid Kubernetes live collection snapshot.",
                        ) from None
                    await _emit(sink, SyncUpdate(SyncStatus.SNAPSHOT, state.snapshot))
                stream = self.reader.session.watch_json(path, state.resource_version)
                async with aclosing(stream):
                    async for payload in stream:
                        if payload is None:
                            opened = self.monotonic()
                            await _emit(sink, SyncUpdate(SyncStatus.LIVE, state.snapshot))
                            continue
                        event = await self._event(resource, payload, namespace)
                        try:
                            changed = state.apply(event)
                        except AppError:
                            raise ConnectionProblem(
                                ConnectionState.API_ERROR,
                                "Invalid or excessive live resource state.",
                            ) from None
                        failures = 0
                        if changed:
                            await _emit(sink, SyncUpdate(SyncStatus.LIVE, state.snapshot, event))
                if opened is not None and self.monotonic() - opened >= min(
                    1.0, self.reader.session.timeout / 2
                ):
                    # Normal bounded watch renewal retains LIVE and the checkpoint.
                    failures = 0
                    continue
                problem = ConnectionProblem(
                    ConnectionState.UNREACHABLE,
                    "The watch ended. Reconnecting from its last version.",
                )
            except _ConsumerFailure as error:
                raise error.problem from None
            except ConnectionProblem as error:
                problem = error
            # Only an established healthy stream resets consecutive failures.
            # Slow failed headers, LISTs and immediate EOFs still back off.
            if (
                opened is not None
                and problem.state in {ConnectionState.TIMEOUT, ConnectionState.UNREACHABLE}
                and self.monotonic() - opened >= min(1.0, self.reader.session.timeout / 2)
            ):
                failures = 0
            action = recovery(problem)
            if action is Recovery.STOP:
                await sink(
                    SyncUpdate(
                        SyncStatus.FAILED, state.snapshot if state else None, problem=problem
                    )
                )
                raise problem
            minimum = problem.retry_after or 0.0 if isinstance(problem, HttpProblem) else 0.0
            delay = retry_delay(failures, self.jitter(), minimum)
            failures = min(failures + 1, 7)
            if action is Recovery.RELIST:
                state = None
            await sink(
                SyncUpdate(
                    SyncStatus.RELISTING if action is Recovery.RELIST else SyncStatus.RETRYING,
                    state.snapshot if state else None,
                    problem=problem,
                    retry_in=delay,
                )
            )
            await self.sleep(delay)
