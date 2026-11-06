"""One bounded, cooperatively drained Event projection; LIST/WATCH stays upstream."""

import asyncio
import threading
import weakref
from dataclasses import dataclass

from kuberich.domain.curated_navigation import ResolvedCollectionBookmark
from kuberich.domain.events import (
    MAX_EVENT_FACT_BYTES,
    MAX_EVENT_FACTS,
    EventFact,
    EventOptions,
    EventRow,
    EventSourceState,
    event_descriptor_supported,
    event_fact,
    event_rows,
)
from kuberich.domain.resources import ResourceRecord, ResourceSnapshot
from kuberich.domain.views import ResourceScope, ViewStatus
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned


@dataclass(frozen=True, slots=True)
class EventProjectionResult:
    rows: tuple[EventRow, ...]
    source: EventSourceState | None
    limited: bool
    notices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CachedFact:
    record: weakref.ReferenceType[ResourceRecord]
    fact: EventFact
    size: int


class _Stopped(Exception):
    """The owned thread reached a cooperative supersession checkpoint."""


class EventProjection:
    def __init__(
        self, *, max_facts: int = MAX_EVENT_FACTS, max_bytes: int = MAX_EVENT_FACT_BYTES
    ) -> None:
        if (
            type(max_facts) is not int
            or not 1 <= max_facts <= MAX_EVENT_FACTS
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_EVENT_FACT_BYTES
        ):
            raise AppError("Event projection budgets must be positive and within hard limits.")
        self._max_facts, self._max_bytes = max_facts, max_bytes
        self._cache: dict[str, _CachedFact] = {}
        self._scope: ResourceScope | None = None
        self._bytes = 0
        self._intent = 0
        self._lock = asyncio.Lock()
        self._stop: threading.Event | None = None
        self._active: (
            asyncio.Task[tuple[EventProjectionResult, dict[str, _CachedFact], int]] | None
        ) = None

    @property
    def cached_count(self) -> int:
        return len(self._cache)

    @property
    def accounted_bytes(self) -> int:
        return self._bytes

    @property
    def operation_count(self) -> int:
        return int(self._active is not None and not self._active.done())

    def _supersede(self) -> int:
        self._intent += 1
        if self._stop is not None:
            self._stop.set()
        return self._intent

    @staticmethod
    def _check(stop: threading.Event) -> None:
        if stop.is_set():
            raise _Stopped

    def _project(
        self,
        snapshot: ResourceSnapshot,
        source: EventSourceState,
        options: EventOptions,
        bookmark: ResolvedCollectionBookmark | None,
        previous: dict[str, _CachedFact],
        stop: threading.Event,
    ) -> tuple[EventProjectionResult, dict[str, _CachedFact], int]:
        cache: dict[str, _CachedFact] = {}
        used = invalid = omitted = 0
        notices: set[str] = set()
        for record in snapshot.items:
            self._check(stop)
            # A duplicated UID still denotes its latest record. An invalid or
            # over-budget replacement must not expose an earlier occurrence.
            prior = cache.pop(record.uid or "", None)
            if prior is not None:
                used -= prior.size
            if source.scope.namespace is not None and record.namespace != source.scope.namespace:
                invalid += 1
                continue
            if bookmark is not None and not bookmark.predicate.matches(snapshot.resource, record):
                continue
            cached = previous.get(record.uid or "")
            if cached is None or cached.record() is not record:
                try:
                    fact = event_fact(snapshot.resource, record)
                except AppError:
                    invalid += 1
                    continue
                cached = _CachedFact(
                    weakref.ref(record), fact, len(repr(fact).encode("utf-8")) + 256
                )
            if len(cache) >= self._max_facts or used + cached.size > self._max_bytes:
                omitted += 1
                continue
            cache[cached.fact.uid] = cached
            used += cached.size
            notices.update(cached.fact.notices)
        self._check(stop)
        facts = tuple(cached.fact for cached in cache.values())
        unknown_types = (
            sum(fact.event_type is None for fact in facts) if options.warnings_only else 0
        )
        if unknown_types:
            notices.add(f"Warning-only filtering omitted {unknown_types} Events with unknown type.")
        if invalid:
            notices.add(f"Omitted {invalid} Events with invalid or mismatched source identity.")
        if omitted:
            notices.add(f"Projection limit: omitted {omitted} Events; showing a retained subset.")
        if not source.collection.complete:
            notices.add("Source collection is incomplete; showing only its retained subset.")
        if source.status in {ViewStatus.STALE, ViewStatus.RELISTING, ViewStatus.FAILED}:
            notices.add(
                f"Source status is {source.status.name.lower()}; retained observations are not a fresh LIST."
            )
        rows = event_rows(facts, options, observed_at=source.snapshot_seen_at)
        self._check(stop)
        return (
            EventProjectionResult(
                rows,
                source,
                bool(invalid or omitted or not source.collection.complete),
                tuple(sorted(notices)),
            ),
            cache,
            used,
        )

    @staticmethod
    def _valid_source(
        snapshot: ResourceSnapshot,
        source: EventSourceState | None,
        bookmark: ResolvedCollectionBookmark | None,
    ) -> bool:
        return (
            source is not None
            and event_descriptor_supported(snapshot.resource)
            and snapshot.resource == source.scope.resource
            and snapshot.namespace == source.scope.namespace
            and snapshot.collection == source.collection
            and source.snapshot_seen_at.tzinfo is not None
            and (
                bookmark is None
                or (
                    bookmark.resource == source.scope.resource
                    and bookmark.namespace == source.scope.namespace
                    and bookmark.query == source.scope.query
                )
            )
        )

    async def project(
        self,
        snapshot: ResourceSnapshot | None,
        source_state: EventSourceState | None,
        options: EventOptions,
        *,
        bookmark: ResolvedCollectionBookmark | None = None,
    ) -> EventProjectionResult:
        intent = self._supersede()
        async with self._lock:
            if intent != self._intent:
                raise asyncio.CancelledError
            if snapshot is None or not self._valid_source(snapshot, source_state, bookmark):
                self._cache.clear()
                self._scope, self._bytes = None, 0
                return EventProjectionResult(
                    (),
                    source_state,
                    snapshot is not None,
                    (
                        "Event source identity or captured collection is unavailable or inconsistent.",
                    )
                    if snapshot is not None
                    else (),
                )
            assert source_state is not None
            previous = self._cache if self._scope == source_state.scope else {}
            stop = threading.Event()
            worker = asyncio.create_task(
                asyncio.to_thread(
                    self._project, snapshot, source_state, options, bookmark, previous, stop
                )
            )
            self._active, self._stop = worker, stop
            try:
                result, cache, used = await asyncio.shield(worker)
                if intent != self._intent:
                    raise asyncio.CancelledError
                self._cache, self._scope, self._bytes = cache, source_state.scope, used
                return result
            except _Stopped:
                raise asyncio.CancelledError from None
            except asyncio.CancelledError:
                stop.set()
                await finish_owned(asyncio.gather(worker, return_exceptions=True))
                raise
            finally:
                self._active, self._stop = None, None

    async def retire(self) -> None:
        intent = self._supersede()
        worker = self._active
        try:
            async with self._lock:
                if intent == self._intent:
                    self._cache.clear()
                    self._scope, self._bytes = None, 0
        except asyncio.CancelledError:
            if worker is not None:
                await finish_owned(asyncio.gather(worker, return_exceptions=True))
            if intent == self._intent:
                self._cache.clear()
                self._scope, self._bytes = None, 0
            raise
