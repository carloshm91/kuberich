"""One captured aggregate owner for membership watches and bounded log readers."""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import partial

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.aggregate_logs import (
    MAX_READERS,
    MAX_RETIRED,
    MAX_SOURCES,
    LogSource,
    intermediate_resource,
    sources,
    workload_kind,
)
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.logs import LogLine, LogOptions
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.logs import PODS, ContainerNotStarted, LogStream
from kuberich.services.processes import _finish_owned
from kuberich.services.resources import ResourceReader, parse_owned
from kuberich.services.watches import ListWatch

_PODS = replace(PODS, verbs=frozenset({"get", "list", "watch"}))
SourceSink = Callable[[LogSource, int, LogLine], Awaitable[None]]


@dataclass
class SourceState:
    source: LogSource
    number: int
    status: str = "waiting"
    message: str = ""
    task: asyncio.Task[None] | None = None
    retry_after_start: str | None = None


class _HeadComplete(Exception):
    pass


class AggregateLogs:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        kind = workload_kind(target)
        if (
            target.session.context != client.context.name
            or resource.group != target.group
            or resource.name != target.resource
            or resource.kind != kind
            or not resource.namespaced
            or not {"get", "list", "watch"} <= resource.verbs
            or target.container is not None
        ):
            raise AppError(
                "Aggregated logs require the captured client, resource and workload identity."
            )
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current = policy, current
        self.reader = ResourceReader(client)
        self.states: dict[tuple[str, str], SourceState] = {}
        self.retired: deque[SourceState] = deque(maxlen=MAX_RETIRED)
        self.excess = 0
        self.closed = False
        self.selected: frozenset[tuple[str, str]] | None = None
        self._next_number = 1
        self._generation = 0
        self._changed = asyncio.Event()
        self._pods: tuple[ResourceRecord, ...] = ()
        self._intermediates: tuple[ResourceRecord, ...] = ()
        self._ready: set[str] = set()
        self._owned: list[asyncio.Task[None]] = []
        self._notice: Callable[[str], None] = lambda message: None
        self._fault: Exception | None = None

    def require_current(self) -> None:
        if self.closed:
            raise AppError("The aggregate owner has stopped; close and reopen the viewer.")
        if not self.current():
            raise AppError("The aggregate target is stale; select the Pod or workload again.")

    def choose(self, keys: frozenset[tuple[str, str]] | None, *, reopen: bool = False) -> None:
        """Explicit admission, independent of the retained-output display filter."""
        self.require_current()
        if keys is not None and (len(keys) > MAX_READERS or not keys <= self.states.keys()):
            raise AppError("Choose at most eight currently available log sources.")
        self.selected = keys
        if reopen:
            for key in keys if keys is not None else self.states:
                state = self.states[key]
                if state.status in {"ended", "failed", "starting"}:
                    state.retry_after_start = None
                    state.status, state.message = (
                        "waiting",
                        "Explicitly reopened; history may repeat",
                    )
        self._changed.set()

    def require_source(self, source: LogSource, number: int) -> None:
        self.require_current()
        state = self.states.get(source.key)
        if state is None or state.number != number or state.status != "active":
            raise AppError("The log source has been removed or replaced.")

    async def _cancel(self, tasks: list[asyncio.Task[None]]) -> None:
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await _finish_owned(asyncio.gather(*tasks, return_exceptions=True))

    async def _watch(self, resource: ApiResource) -> None:
        async def observe(update: SyncUpdate) -> None:
            self.require_current()
            if (
                update.status in {SyncStatus.SNAPSHOT, SyncStatus.LIVE}
                and update.snapshot is not None
            ):
                if resource.name == "pods":
                    self._pods = update.snapshot.items
                else:
                    self._intermediates = update.snapshot.items
                self._ready.add(resource.name)
                self._changed.set()
            if update.problem is not None:
                self._notice(f"Membership {resource.name}: {update.problem}")

        await ListWatch(self.reader).run(resource, self.target.namespace, observe)

    async def _control(self, options: LogOptions, sink: SourceSink, head_lines: int | None) -> None:
        required = {"pods"}
        intermediate = intermediate_resource(self.target)
        if intermediate is not None:
            required.add(intermediate.name)
        while True:
            await self._changed.wait()
            self._changed.clear()
            self.require_current()
            if not required <= self._ready:
                continue
            if self._fault is not None:
                raise self._fault
            pods, owners = self._pods, self._intermediates
            available, excess = await parse_owned(
                partial(sources, self.target, pods, owners, previous=options.previous)
            )
            self.require_current()
            # Membership may have advanced while its bounded parser was owned.
            if pods is not self._pods or owners is not self._intermediates:
                self._changed.set()
                continue
            if excess:
                self.excess = excess
                raise AppError(
                    f"Aggregate exceeds {MAX_SOURCES} sources; select a smaller workload or a Pod. No excess reader is opened."
                )
            keys = {source.key for source in available}
            if self.selected is not None:
                self.selected = frozenset(key for key in self.selected if key in keys)
            removed = [state for key, state in self.states.items() if key not in keys]
            for state in removed:
                del self.states[state.source.key]
                state.status, state.message = (
                    "removed",
                    "Pod/container no longer belongs to this target",
                )
                self.retired.append(state)
            await self._cancel([state.task for state in removed if state.task is not None])
            for source in available:
                if source.key not in self.states:
                    previous = next(
                        (state for state in self.retired if state.source.key == source.key), None
                    )
                    state = SourceState(source, self._next_number)
                    self._next_number += 1
                    if previous is not None:
                        state.status, state.message = (
                            "ended",
                            "Returned source; choose Reopen to read again",
                        )
                    self.states[source.key] = state
                else:
                    self.states[source.key].source = source
            self.excess = excess
            desired = self.selected
            stopping = [
                state
                for key, state in self.states.items()
                if state.status == "active" and desired is not None and key not in desired
            ]
            for state in stopping:
                state.status, state.message = "excluded", "Stopped by explicit source selection"
            await self._cancel([state.task for state in stopping if state.task is not None])
            active = sum(state.status == "active" for state in self.states.values())
            for key, state in self.states.items():
                if state.status in {"ended", "failed", "active"}:
                    continue
                state.status = (
                    "excluded"
                    if desired is not None and key not in desired
                    else "starting"
                    if state.source.start_token is None
                    or state.source.start_token == state.retry_after_start
                    else "waiting"
                )
                if state.status == "starting" and options.previous:
                    state.status, state.message = (
                        "no prior",
                        "No previous terminated container instance",
                    )
                if state.status == "waiting" and active < MAX_READERS:
                    state.status = "active"
                    state.task = asyncio.create_task(
                        self._read(state, self._generation, options, sink, head_lines)
                    )
                    active += 1
            self._notice("Sources updated")

    async def _read(
        self,
        state: SourceState,
        generation: int,
        options: LogOptions,
        sink: SourceSink,
        head_lines: int | None,
    ) -> None:
        source = state.source
        target = ResourceTarget(
            self.target.session,
            "",
            "pods",
            source.namespace,
            source.pod,
            source.uid,
            source.container,
        )

        def current() -> bool:
            return (
                not self.closed
                and self.current()
                and generation == self._generation
                and self.states.get(source.key) is state
                and state.status == "active"
            )

        stream = LogStream(self.client, target, self.policy, current)
        count = 0
        was_opened = False

        async def retain(line: LogLine) -> None:
            nonlocal count
            stream.require_current()
            await sink(source, state.number, line)
            stream.require_current()
            count += 1
            if head_lines is not None and count == head_lines:
                raise _HeadComplete
            if count % 64 == 0:
                await asyncio.sleep(0)

        def opened() -> None:
            nonlocal was_opened
            was_opened = True
            state.message = "Waiting for output"
            self._notice("Reader opened")

        try:
            await stream.run(options, retain, opened=opened)
        except _HeadComplete:
            state.status, state.message = "ended", "Head snapshot complete"
        except ContainerNotStarted as error:
            if current():
                state.status, state.message = ("failed" if was_opened else "starting"), str(error)
                if not was_opened:
                    state.retry_after_start = source.start_token
        except (AppError, ConnectionProblem) as error:
            if current():
                state.status, state.message = "failed", str(error)
        except Exception as error:
            self._fault = error
        else:
            state.status, state.message = (
                "ended",
                f"Stream complete · {count} lines; no automatic replay",
            )
        finally:
            self._changed.set()

    async def run(
        self,
        options: LogOptions,
        sink: SourceSink,
        notice: Callable[[str], None],
        *,
        head_lines: int | None = None,
    ) -> None:
        self.policy.require(Action.READ)
        self.require_current()
        if self._owned:
            raise AppError("The aggregate owner is already running.")
        self._notice = notice
        self._generation += 1
        self._ready.clear()
        self._fault = None
        self._pods, self._intermediates = (), ()
        record = await self.reader.get(self.resource, self.target.name, self.target.namespace)
        self.require_current()
        self.target.require_current(self.target.session, uid=record.uid or "")
        if record.name != self.target.name:
            raise AppError("Aggregate API response does not match the captured workload name.")
        intermediate = intermediate_resource(self.target)
        self._owned = [
            asyncio.create_task(self._watch(_PODS)),
            asyncio.create_task(self._control(options, sink, head_lines)),
        ]
        if intermediate is not None:
            self._owned.append(asyncio.create_task(self._watch(intermediate)))
        try:
            await asyncio.gather(*self._owned)
        finally:
            await self.close()

    async def close(self) -> None:
        self.closed = True
        self._generation += 1
        await self._cancel(self._owned)
        await self._cancel([state.task for state in self.states.values() if state.task is not None])
        for state in self.states.values():
            if state.status not in {"ended", "failed"}:
                state.status, state.message = "stopped", "Aggregate owner stopped; no active reader"
        self._owned.clear()
