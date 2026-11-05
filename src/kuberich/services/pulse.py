"""One serialized, scope-owned and bounded cluster overview collector."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from typing import TypedDict

from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.history import HistorySnapshot
from kuberich.domain.metrics import MAX_SAMPLE_AGE, MetricReport, MetricStatus
from kuberich.domain.pulse import (
    FAMILIES,
    PulsePredicate,
    PulseScope,
    PulseSnapshot,
    PulseSource,
    PulseStatus,
    expire_metrics,
    overview_metrics,
    pod_budgets,
    predicates,
    rows,
)
from kuberich.domain.resources import (
    MAX_RESOURCE_BYTES,
    MAX_RESOURCE_ITEMS,
    ApiResource,
    Discovery,
    ResourceSnapshot,
)
from kuberich.errors import AppError
from kuberich.services.resources import ResourceReader, parse_owned

PULSE_INTERVAL = 15.0


class RetentionBudget(TypedDict):
    max_items: int
    max_retained_bytes: int


class PulseAccumulator:
    """Page prefixes reuse previous work; collection restarts replace every count."""

    def __init__(self, name: str) -> None:
        self.predicates = predicates(name)
        self.counts: dict[PulsePredicate, int] = dict.fromkeys(self.predicates, 0)
        self.processed = 0
        self.version: str | None = None
        self.first: tuple[str | None, str | None] | None = None

    def apply(self, snapshot: ResourceSnapshot) -> dict[PulsePredicate, int]:
        first = (
            (snapshot.items[0].uid, snapshot.items[0].resource_version) if snapshot.items else None
        )
        if (
            snapshot.resource_version != self.version
            or len(snapshot.items) < self.processed
            or first != self.first
        ):
            self.counts = dict.fromkeys(self.predicates, 0)
            self.processed = 0
        for record in snapshot.items[self.processed :]:
            for predicate in self.predicates:
                self.counts[predicate] = self.counts.get(predicate, 0) + predicate.matches(record)
        self.processed = len(snapshot.items)
        self.version, self.first = snapshot.resource_version, first
        return dict(self.counts)


def _failure(problem: ConnectionProblem | AppError) -> tuple[PulseStatus, str]:
    if isinstance(problem, HttpProblem):
        return (
            PulseStatus.FORBIDDEN
            if problem.status == 403
            else PulseStatus.UNAVAILABLE
            if problem.status in {404, 503}
            else PulseStatus.FAILED,
            f"Read HTTP {problem.status}",
        )
    if isinstance(problem, ConnectionProblem):
        return PulseStatus.FAILED, f"Read {problem.state.name.lower()}"
    return PulseStatus.FAILED, "Invalid or excessive overview payload"


def _metric_status(status: PulseStatus) -> MetricStatus:
    return {
        PulseStatus.FORBIDDEN: MetricStatus.FORBIDDEN,
        PulseStatus.UNAVAILABLE: MetricStatus.UNAVAILABLE,
        PulseStatus.FAILED: MetricStatus.ERROR,
        PulseStatus.PARTIAL: MetricStatus.PARTIAL,
    }[status]


def _failed_report(
    report: MetricReport,
    status: PulseStatus,
    detail: str,
    *,
    membership_unknown: bool = False,
) -> MetricReport:
    return replace(
        report,
        status=_metric_status(status),
        cpu=replace(
            report.cpu,
            usage=None,
            partial=True,
            uncertain=report.cpu.uncertain or membership_unknown,
        ),
        memory=replace(
            report.memory,
            usage=None,
            partial=True,
            uncertain=report.memory.uncertain or membership_unknown,
        ),
        allocation_uncertain=report.allocation_uncertain or membership_unknown,
        detail=detail,
    )


class PulseService:
    """No watch, per-row HTTP, overlapping refresh or unbounded observation queue."""

    def __init__(
        self,
        reader: ResourceReader,
        discovery: Discovery,
        scope: PulseScope,
        current: Callable[[], bool],
        *,
        history: Callable[[], Awaitable[HistorySnapshot]] | None = None,
        interval: float = PULSE_INTERVAL,
        max_items: int = MAX_RESOURCE_ITEMS,
        max_retained_bytes: int = MAX_RESOURCE_BYTES,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        expiry_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not 0.01 <= interval <= 60:
            raise AppError("Pulse refresh interval is outside its bounds.")
        if type(max_items) is not int or not 4 <= max_items <= MAX_RESOURCE_ITEMS:
            raise AppError("Pulse retention count is outside its bounds.")
        if type(max_retained_bytes) is not int or not 4 <= max_retained_bytes <= MAX_RESOURCE_BYTES:
            raise AppError("Pulse retention bytes are outside their bounds.")
        self.reader, self.discovery, self.scope, self.current = reader, discovery, scope, current
        self.history, self.interval = history, interval
        self.max_items, self.max_retained_bytes = max_items, max_retained_bytes
        self.now, self.expiry_sleep = now, expiry_sleep
        self.snapshot = PulseSnapshot(scope)
        self.retained_count = 0
        self.retained_bytes = 0
        self.peak_retained_count = 0
        self.peak_retained_bytes = 0

    def _check(self) -> None:
        if not self.current():
            raise asyncio.CancelledError

    def _missing(self, key: str, group: str) -> PulseSource:
        forbidden = any(
            issue.reason == "forbidden"
            and (
                issue.source == ("/apis" if group else "/api")
                or issue.source.partition("/")[0] == (group or "v1")
            )
            for issue in self.discovery.issues
        )
        return PulseSource(
            key,
            None,
            None if key in {"nodes", "node_metrics"} else self.scope.namespace,
            PulseStatus.FORBIDDEN if forbidden else PulseStatus.UNAVAILABLE,
            None,
            detail="API was not discovered; check availability and read access",
        )

    def _resource(self, name: str, group: str) -> ApiResource | None:
        try:
            return self.discovery.find(name, group=group)
        except AppError:
            return None

    def _retention(self, *snapshots: ResourceSnapshot) -> None:
        self.retained_count = sum(len(snapshot.items) for snapshot in snapshots)
        self.retained_bytes = sum(snapshot.collection.retained_bytes for snapshot in snapshots)
        self.peak_retained_count = max(self.peak_retained_count, self.retained_count)
        self.peak_retained_bytes = max(self.peak_retained_bytes, self.retained_bytes)
        if self.retained_count > self.max_items or self.retained_bytes > self.max_retained_bytes:
            raise AppError("Pulse combined retention exceeded its bound.")

    def _budget(self, *, reserve: bool) -> RetentionBudget:
        # Keep room for captured Node/Pod membership, metrics and UID reverification.
        return {
            "max_items": min(
                self.max_items - self.retained_count,
                self.max_items // 4 if reserve else self.max_items,
            ),
            "max_retained_bytes": min(
                self.max_retained_bytes - self.retained_bytes,
                self.max_retained_bytes // 4 if reserve else self.max_retained_bytes,
            ),
        }

    async def collect(self, publish: Callable[[PulseSnapshot], None]) -> PulseSnapshot:
        try:
            return await self._collect(publish)
        finally:
            self._retention()

    async def _collect(self, publish: Callable[[PulseSnapshot], None]) -> PulseSnapshot:
        """Publish honest loading/page snapshots while fixed families are read serially."""
        if self.snapshot.scope != self.scope:
            raise AppError("Pulse cache does not belong to its captured session and scope.")
        sources: dict[str, PulseSource] = {}
        counts: dict[str, dict[PulsePredicate, int] | None] = {}
        retained: dict[str, ResourceSnapshot] = {}
        previous_sources = {source.key: source for source in self.snapshot.sources}
        self._retention()
        for group, name in FAMILIES:
            resource = self._resource(name, group)
            sources[name] = (
                PulseSource(
                    name,
                    resource,
                    self.scope.namespace if resource.namespaced else None,
                    PulseStatus.LOADING,
                    None,
                )
                if resource is not None
                else self._missing(name, group)
            )
            counts[name] = None
        for name in ("nodes", "pods"):
            resource = self._resource(name, "metrics.k8s.io")
            key = "node_metrics" if name == "nodes" else "pod_metrics"
            sources[key] = (
                PulseSource(
                    key,
                    resource,
                    self.scope.namespace if resource.namespaced else None,
                    PulseStatus.LOADING,
                    None,
                )
                if resource is not None
                else self._missing(key, "metrics.k8s.io")
            )
        for key, source in tuple(sources.items()):
            previous = previous_sources.get(key)
            if previous is not None and (
                previous.resource == source.resource and previous.namespace == source.namespace
            ):
                sources[key] = replace(source, observed_at=previous.observed_at)

        def emit() -> None:
            self._check()
            self.snapshot = expire_metrics(
                replace(
                    self.snapshot,
                    sources=tuple(sources.values()),
                    rows=tuple(row for key in counts for row in rows(sources[key], counts[key])),
                ),
                self.now(),
            )
            publish(self.snapshot)

        # Previous current samples remain independently timestamped while new reads load.
        emit()
        snapshot: ResourceSnapshot | None = None
        for _, name in FAMILIES:
            self._check()
            source = sources[name]
            if source.resource is None:
                continue
            accumulator = PulseAccumulator(name)

            async def receive(
                snapshot: ResourceSnapshot,
                *,
                key: str = name,
                accumulator: PulseAccumulator = accumulator,
            ) -> None:
                self._check()
                self._retention(*retained.values(), snapshot)
                counts[key] = await parse_owned(partial(accumulator.apply, snapshot))
                self._check()
                observed_at = self.now()
                sources[key] = replace(
                    sources[key],
                    status=PulseStatus.VALID
                    if snapshot.collection.complete
                    else PulseStatus.PARTIAL,
                    observed_at=observed_at,
                    attempted_at=observed_at,
                    complete=snapshot.collection.complete,
                    limited=snapshot.collection.limited,
                    count=len(snapshot.items),
                    detail="Retained subset · collection limit"
                    if snapshot.collection.limited
                    else f"Loading page {snapshot.collection.pages}"
                    if not snapshot.collection.complete
                    else "",
                )
                emit()

            try:
                snapshot = await self.reader.list(
                    source.resource,
                    source.namespace,
                    progress=receive,
                    **self._budget(reserve=name in {"nodes", "pods"}),
                )
                await receive(snapshot)
                if name in {"nodes", "pods"}:
                    retained[name] = snapshot
                    if name == "pods":
                        budget = await parse_owned(partial(pod_budgets, snapshot))
                        self.snapshot = replace(
                            self.snapshot,
                            pod_metrics=budget,
                            budgets_observed_at=sources[name].observed_at,
                        )
                    else:
                        capacity = await parse_owned(
                            partial(overview_metrics, snapshot, None, None, self.now())
                        )
                        self.snapshot = replace(
                            self.snapshot,
                            node_metrics=capacity,
                            capacity_observed_at=sources[name].observed_at,
                        )
                    emit()
            except (ConnectionProblem, AppError) as problem:
                retained.pop(name, None)
                status, detail = _failure(problem)
                sources[name] = replace(
                    source,
                    status=status,
                    attempted_at=self.now(),
                    detail=detail,
                )
                counts[name] = None
                emit()
            finally:
                snapshot = None
            self._retention(*retained.values())
        for name, key in (("nodes", "node_metrics"), ("pods", "pod_metrics")):
            self._check()
            source = sources[key]
            selected = retained.get(name)
            report = self.snapshot.node_metrics if name == "nodes" else self.snapshot.pod_metrics
            if source.resource is None or selected is None:
                if selected is None and source.resource is not None:
                    source = replace(
                        source,
                        status=PulseStatus.UNAVAILABLE,
                        detail="Resource membership unavailable; current usage cannot be verified",
                        attempted_at=self.now(),
                    )
                report = _failed_report(
                    report,
                    source.status,
                    source.detail,
                    membership_unknown=selected is None,
                )
                sources[key] = source
            else:
                samples: ResourceSnapshot | None = None
                after: ResourceSnapshot | None = None
                try:
                    samples = await self.reader.list(
                        source.resource, source.namespace, **self._budget(reserve=True)
                    )
                    self._retention(*retained.values(), samples)
                    after = await self.reader.list(
                        selected.resource, selected.namespace, **self._budget(reserve=True)
                    )
                    self._retention(*retained.values(), samples, after)
                    report = await parse_owned(
                        partial(overview_metrics, selected, samples, after, self.now())
                    )
                    observed_at = self.now()
                    sources[key] = replace(
                        source,
                        status=PulseStatus.VALID
                        if report.status is MetricStatus.VALID
                        else PulseStatus.STALE
                        if report.status is MetricStatus.STALE
                        else PulseStatus.PARTIAL,
                        observed_at=observed_at,
                        attempted_at=observed_at,
                        complete=selected.collection.complete
                        and samples.collection.complete
                        and after.collection.complete,
                        limited=samples.collection.limited or after.collection.limited,
                        count=len(samples.items),
                        detail=report.detail,
                    )
                except (ConnectionProblem, AppError) as problem:
                    status, detail = _failure(problem)
                    sources[key] = replace(
                        source,
                        status=status,
                        attempted_at=self.now(),
                        detail=detail,
                    )
                    report = _failed_report(report, status, detail)
                finally:
                    samples = after = None
            self.snapshot = (
                replace(self.snapshot, node_metrics=report)
                if name == "nodes"
                else replace(self.snapshot, pod_metrics=report)
            )
            self._retention(*retained.values())
            emit()
        if self.history is not None:
            history = await self.history()
            self._check()
            self.snapshot = replace(self.snapshot, history=history)
        self.snapshot = replace(self.snapshot, observed_at=self.now())
        emit()
        retained.clear()
        self._retention()
        return self.snapshot

    async def run(self, publish: Callable[[PulseSnapshot], None]) -> None:
        async def expire() -> None:
            while self.current():
                await self.expiry_sleep(min(1.0, MAX_SAMPLE_AGE))
                if self.current():
                    fresh = expire_metrics(self.snapshot, self.now())
                    if fresh != self.snapshot:
                        self.snapshot = fresh
                        publish(fresh)

        expiry = asyncio.create_task(expire(), name="kuberich-pulse-expiry")
        try:
            while self.current():
                await self.collect(publish)
                await asyncio.sleep(self.interval)
        finally:
            expiry.cancel()
            completion = asyncio.gather(expiry, return_exceptions=True)
            while not completion.done():
                try:
                    await asyncio.shield(completion)
                except asyncio.CancelledError:
                    continue
            if not expiry.cancelled():
                expiry.result()
            self._retention()
