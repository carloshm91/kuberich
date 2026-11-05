"""Read aggregate Prometheus history through one captured Kubernetes session."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.history import (
    HISTORY_SECONDS,
    HISTORY_STEP_SECONDS,
    HistoryBackend,
    HistoryPoint,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    history_queries,
    parse_history_range,
)
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned

if TYPE_CHECKING:
    from kuberich.adapters.kubernetes import KubernetesSession


async def _parse(
    document: object, start: datetime, end: datetime
) -> tuple[tuple[HistoryPoint, ...], bool]:
    worker = asyncio.create_task(asyncio.to_thread(parse_history_range, document, start, end))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await finish_owned(asyncio.gather(worker, return_exceptions=True))
        raise


class HistoryReader:
    """No private client, credential copying, discovery side effects or history cache."""

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
        partial = False
        for key, query in queries:
            points: tuple[HistoryPoint, ...] = ()
            try:
                async with asyncio.timeout(10):
                    document = await session.get_json(
                        backend.path,
                        params={
                            "query": query,
                            "start": str(int(start.timestamp())),
                            "end": str(int(end.timestamp())),
                            "step": str(HISTORY_STEP_SECONDS),
                            "timeout": "8s",
                        },
                        max_bytes=1024 * 1024,
                    )
                    points, warning = await _parse(document, start, end)
                partial |= warning
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
                if partial or errors or not all(found)
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
