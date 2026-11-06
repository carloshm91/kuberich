"""Read aggregate Prometheus history through one captured Kubernetes session."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Literal, Protocol

from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.history import (
    HISTORY_SECONDS,
    HISTORY_STEP_SECONDS,
    MAX_HISTORY_BODY_BYTES,
    MAX_HISTORY_QUERIES,
    MAX_SNAPSHOT_POINTS,
    MAX_SNAPSHOT_SERIES,
    HistoryBackend,
    HistoryPoint,
    HistoryQueryPlan,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    ParsedHistory,
    QuerySpec,
    SourceStatus,
    history_queries,
    parse_history_matrix,
    parse_history_range,
)
from kuberich.domain.read_budget import ReadBudget
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import parse_owned

if TYPE_CHECKING:
    from kuberich.adapters.kubernetes import KubernetesSession

type HistorySuffix = Literal["query", "query_range", "status/buildinfo"]


class HistoryTransport(Protocol):
    async def get_json(
        self, suffix: HistorySuffix, params: Mapping[str, str], *, max_bytes: int
    ) -> object: ...

    async def close(self) -> None: ...


class ServiceHistoryTransport:
    """Use only the captured API server; retain its proper API-hop identity."""

    def __init__(
        self,
        session: KubernetesSession,
        backend: HistoryBackend,
        service_uid: str,
        *,
        prefix: str = "",
        budget: ReadBudget | None = None,
    ) -> None:
        from kuberich.domain.history import history_prefix

        if not service_uid:
            raise AppError("History Service requires captured UID evidence.")
        self._session = session
        self._budget = budget
        self._base = backend.path.removesuffix("/api/v1/query_range") + history_prefix(prefix)
        self._tasks: set[asyncio.Task[object]] = set()
        self._closed = False

    async def get_json(
        self, suffix: HistorySuffix, params: Mapping[str, str], *, max_bytes: int
    ) -> object:
        if (
            self._closed
            or suffix not in {"query", "query_range", "status/buildinfo"}
            or (type(max_bytes) is not int or not 1 <= max_bytes <= MAX_HISTORY_BODY_BYTES)
        ):
            raise AppError("History Service requires a fixed API suffix and bounded body.")
        if self._budget is not None:
            self._budget.charge()
        task: asyncio.Task[object] = asyncio.create_task(
            self._session.get_json(
                self._base + "/api/v1/" + suffix, params=dict(params), max_bytes=max_bytes
            )
        )
        self._tasks.add(task)
        try:
            return await task
        finally:
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))


def _failure(error: Exception, *, legacy: bool = False) -> HistoryStatus:
    if isinstance(error, HttpProblem):
        if error.status == 403:
            return HistoryStatus.FORBIDDEN
        if error.status in {404, 429, 503}:
            return HistoryStatus.UNAVAILABLE
        if error.status == 401 and not legacy:
            return HistoryStatus.UNAUTHORIZED
    if (
        isinstance(error, TimeoutError)
        or (isinstance(error, ConnectionProblem) and error.state is ConnectionState.TIMEOUT)
    ) and not legacy:
        return HistoryStatus.TIMEOUT
    if isinstance(error, AppError) and not legacy:
        return HistoryStatus.INVALID_RESPONSE
    return HistoryStatus.FAILED


async def _parse(
    document: object, start: datetime, end: datetime
) -> tuple[tuple[HistoryPoint, ...], bool]:
    worker = asyncio.create_task(asyncio.to_thread(parse_history_range, document, start, end))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await finish_owned(asyncio.gather(worker, return_exceptions=True))
        raise


async def _range_document(
    read: Callable[..., Awaitable[object]],
    expression: str,
    start: datetime,
    end: datetime,
    step_seconds: int,
    parameters: tuple[tuple[str, str], ...] = (),
) -> object:
    """The legacy overview and detailed reader share the same fixed HTTP engine."""
    async with asyncio.timeout(10):
        return await read(
            params={
                "query": expression,
                "start": str(int(start.timestamp())),
                "end": str(int(end.timestamp())),
                "step": str(step_seconds),
                "timeout": "8s",
                **dict(parameters),
            },
            max_bytes=MAX_HISTORY_BODY_BYTES,
        )


class HistoryReader:
    """No private client, credential copying, discovery side effects or history cache."""

    async def collect(
        self,
        transport: HistoryTransport,
        plan: HistoryQueryPlan,
        current: Callable[[], bool],
        *,
        now: Callable[[], datetime],
    ) -> HistorySnapshot:
        """Run a finite plan with two bodies at most and owned parser drainage."""
        from kuberich.domain.history import finalize_history_results

        request = plan.request
        if len(plan.queries) > MAX_HISTORY_QUERIES:
            raise AppError("History query plan exceeds its finite query bound.")
        results: list[tuple[QuerySpec, ParsedHistory]] = []
        errors: list[HistoryStatus] = []
        points = series = 0
        statuses: list[tuple[str, SourceStatus]] = []

        async def fetch(query: QuerySpec) -> object:
            return await _range_document(
                partial(transport.get_json, "query_range"),
                query.expression,
                request.start,
                request.end,
                request.step_seconds,
                plan.provider_parameters,
            )

        async with asyncio.timeout(30):
            for offset in range(0, len(plan.queries), 2):
                if not current():
                    raise asyncio.CancelledError
                batch = plan.queries[offset : offset + 2]
                tasks = [asyncio.create_task(fetch(query)) for query in batch]
                try:
                    documents = await asyncio.gather(*tasks, return_exceptions=True)
                except asyncio.CancelledError:
                    for task in tasks:
                        task.cancel()
                    await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
                    raise
                for query, document in zip(batch, documents, strict=True):
                    parsed = ParsedHistory((), (), "unavailable", 0)
                    try:
                        if isinstance(document, BaseException):
                            raise document
                        parsed = await parse_owned(
                            partial(
                                parse_history_matrix,
                                document,
                                query,
                                request.start,
                                request.end,
                                request.step_seconds,
                                remaining_series=MAX_SNAPSHOT_SERIES - series,
                                remaining_points=MAX_SNAPSHOT_POINTS - points,
                            )
                        )
                        series += len(parsed.series)
                        points += sum(len(item.points) for item in parsed.series)
                    except (AppError, ConnectionProblem, TimeoutError) as error:
                        errors.append(_failure(error))
                    results.append((query, parsed))
                    statuses.append((query.key, parsed.source_status))
                documents.clear()
        if not current():
            raise asyncio.CancelledError
        final = await parse_owned(lambda: finalize_history_results(plan, tuple(results)))
        found = any(point.value is not None for item in final.series for point in item.points)
        status = (
            (
                HistoryStatus.PARTIAL
                if errors
                or final.source_status == "partial"
                or any(notice.severity == "warning" for notice in final.notices)
                else HistoryStatus.VALID
            )
            if found
            else next(iter(errors), HistoryStatus.NO_DATA)
        )
        return HistorySnapshot(
            status,
            now(),
            request.start,
            request.end,
            request.step_seconds,
            final.series,
            "Evaluation timestamps do not prove scrape freshness. Contributor completeness follows the recorded source evidence.",
            request.options.endpoint.scope_label(request.scope.namespace),
            request_id=request.id,
            membership_evidence=plan.membership_evidence,
            source_status=tuple(statuses),
            notices=final.notices,
            accounted_bytes=final.accounted_bytes,
        )

    async def read(
        self,
        session: KubernetesSession,
        backend: HistoryBackend | None,
        namespace: str | None,
        *,
        now: datetime | None = None,
    ) -> HistorySnapshot:
        if backend is None:
            return HistorySnapshot()
        observed = now or datetime.now(UTC)
        end = datetime.fromtimestamp(
            int(observed.timestamp()) // HISTORY_STEP_SECONDS * HISTORY_STEP_SECONDS, UTC
        )
        start = end - timedelta(seconds=HISTORY_SECONDS)
        try:
            scope_label = backend.scope_label(namespace)
            queries = history_queries(backend, namespace)
        except AppError:
            return HistorySnapshot(
                HistoryStatus.FAILED,
                observed_at=observed,
                start=start,
                end=end,
                detail="History selectors conflict with the selected namespace.",
                scope_label="History query scope is unavailable",
            )
        series = []
        errors: list[HistoryStatus] = []
        has_partial = False
        for key, query in queries:
            points: tuple[HistoryPoint, ...] = ()
            try:
                async with asyncio.timeout(10):
                    document = await _range_document(
                        partial(session.get_json, backend.path),
                        query,
                        start,
                        end,
                        HISTORY_STEP_SECONDS,
                    )
                    points, warning = await _parse(document, start, end)
                has_partial |= warning
            except HttpProblem as error:
                errors.append(
                    HistoryStatus.FORBIDDEN
                    if error.status == 403
                    else HistoryStatus.UNAVAILABLE
                    if error.status in {404, 503}
                    else HistoryStatus.FAILED
                )
            except (AppError, ConnectionProblem, TimeoutError):
                errors.append(HistoryStatus.FAILED)
            series.append(
                HistorySeries(
                    key,
                    "Container CPU history" if key == "cpu" else "Container memory history",
                    "cores" if key == "cpu" else "bytes",
                    points,
                )
            )
        found = [any(point.value is not None for point in item.points) for item in series]
        if any(found):
            status = (
                HistoryStatus.PARTIAL
                if has_partial or errors or not all(found)
                else HistoryStatus.VALID
            )
        else:
            status = next(
                (
                    state
                    for state in (
                        HistoryStatus.FORBIDDEN,
                        HistoryStatus.FAILED,
                        HistoryStatus.UNAVAILABLE,
                    )
                    if state in errors
                ),
                HistoryStatus.NO_DATA,
            )
        detail = (
            "Some history is missing, failed or accompanied by backend notices."
            if status is HistoryStatus.PARTIAL
            else f"History {status.value}."
        ) + " Evaluation timestamps do not prove scrape freshness."
        return HistorySnapshot(
            status,
            observed,
            start,
            end,
            HISTORY_STEP_SECONDS,
            tuple(series),
            detail,
            scope_label,
        )
