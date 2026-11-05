"""Bounded aggregate history, its declared scope and explicit availability."""

import json
import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import cast

from kuberich.domain.connections import namespace_name
from kuberich.errors import AppError

HISTORY_SECONDS = 900
HISTORY_STEP_SECONDS = 15
HISTORY_MAX_AGE = 60
MAX_HISTORY_POINTS = 2048
_LABEL = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}", re.ASCII)


class HistoryStatus(StrEnum):
    UNCONFIGURED = "not configured"
    LOADING = "loading"
    VALID = "valid"
    NO_DATA = "no data"
    UNAVAILABLE = "backend unavailable"
    FORBIDDEN = "forbidden"
    FAILED = "read failed"
    STALE = "stale"
    PARTIAL = "partial"


def _matcher(name: object, value: object) -> tuple[str, str]:
    if not isinstance(name, str) or _LABEL.fullmatch(name) is None:
        raise AppError("History matcher names require bounded Prometheus label names.")
    if (
        not isinstance(value, str)
        or len(value) > 256
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
    ):
        raise AppError("History matcher values require bounded text without controls.")
    return name, value


@dataclass(frozen=True)
class HistoryBackend:
    namespace: str
    service: str
    port: int = 9090
    scheme: str = "http"
    matchers: tuple[tuple[str, str], ...] = ()
    cluster_label: str | None = None
    cluster_value: str | None = None

    def __post_init__(self) -> None:
        namespace_name(self.namespace)
        namespace_name(self.service)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise AppError("History Service port must be an integer between 1 and 65535.")
        if self.scheme not in {"http", "https"}:
            raise AppError("History Service scheme must be http or https.")
        if not isinstance(self.matchers, tuple) or len(self.matchers) > 8:
            raise AppError("History accepts at most eight literal label matchers.")
        seen: set[str] = set()
        for pair in self.matchers:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise AppError("History matchers require name/value pairs.")
            name, _ = _matcher(*pair)
            if name in seen:
                raise AppError("History matcher names must be unique.")
            seen.add(name)
        if (self.cluster_label is None) != (self.cluster_value is None):
            raise AppError("History cluster_label and cluster_value must be configured together.")
        if self.cluster_label is not None:
            name, value = _matcher(self.cluster_label, self.cluster_value)
            if not value or (name in seen and dict(self.matchers)[name] != value):
                raise AppError("History cluster binding must be nonempty and match its selectors.")

    @property
    def path(self) -> str:
        return (
            f"/api/v1/namespaces/{self.namespace}/services/"
            f"{self.scheme}:{self.service}:{self.port}/proxy/api/v1/query_range"
        )

    def labels(self, namespace: str | None) -> tuple[tuple[str, str], ...]:
        labels = dict(self.matchers)
        if self.cluster_label is not None:
            labels[self.cluster_label] = cast(str, self.cluster_value)
        if namespace is not None:
            namespace_name(namespace)
            if "namespace" in labels and labels["namespace"] != namespace:
                raise AppError("History namespace selector conflicts with the active namespace.")
            labels["namespace"] = namespace
        return tuple(sorted(labels.items()))

    def scope_label(self, namespace: str | None) -> str:
        binding = (
            f"Configured cluster selector {self.cluster_label}={self.cluster_value}"
            if self.cluster_label is not None
            else "Backend scope: Kubernetes cluster binding unverified"
        )
        selected = ", ".join(f"{key}={value}" for key, value in self.labels(namespace))
        return f"{binding} · selectors: {selected or 'none'}"


@dataclass(frozen=True)
class HistoryPoint:
    timestamp: datetime
    value: Decimal | None


@dataclass(frozen=True)
class HistorySeries:
    key: str
    label: str
    unit: str
    points: tuple[HistoryPoint, ...]


@dataclass(frozen=True)
class HistorySnapshot:
    status: HistoryStatus = HistoryStatus.UNCONFIGURED
    observed_at: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    step_seconds: int = HISTORY_STEP_SECONDS
    series: tuple[HistorySeries, ...] = ()
    detail: str = "Configure an observability history Service for this context."
    scope_label: str = "No historical backend selected"

    def fresh(self, now: datetime) -> "HistorySnapshot":
        if self.status not in {HistoryStatus.VALID, HistoryStatus.PARTIAL}:
            return self
        if (
            self.observed_at is not None
            and 0 <= (now - self.observed_at).total_seconds() < HISTORY_MAX_AGE
        ):
            return self
        return replace(
            self,
            status=HistoryStatus.STALE,
            series=tuple(
                replace(series, points=tuple(replace(point, value=None) for point in series.points))
                for series in self.series
            ),
            detail="History cache expired; evaluation timestamps do not prove scrape freshness.",
        )


def history_queries(backend: HistoryBackend, namespace: str | None) -> tuple[tuple[str, str], ...]:
    """Two internal aggregate expressions; every configured matcher is literal."""
    labels = ",".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}"
        for name, value in backend.labels(namespace)
    )
    selector = '{container!="",container!="POD",pod!=""' + ("," + labels if labels else "") + "}"
    return (
        ("cpu", f"sum(rate(container_cpu_usage_seconds_total{selector}[5m]))"),
        ("memory", f"sum(container_memory_working_set_bytes{selector})"),
    )


def parse_history_range(
    document: object, start: datetime, end: datetime, step_seconds: int = HISTORY_STEP_SECONDS
) -> tuple[tuple[HistoryPoint, ...], bool]:
    """Read one aggregate matrix, retaining missing and nonfinite values as gaps."""
    problem = "Invalid or oversized aggregate history response."
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or type(step_seconds) is not int
        or not 1 <= step_seconds <= 3600
        or not 0 <= (end - start).total_seconds() <= 86400
    ):
        raise AppError(problem)
    count = int((end - start).total_seconds() // step_seconds) + 1
    if count > MAX_HISTORY_POINTS or not isinstance(document, dict):
        raise AppError(problem)
    if document.get("status") != "success":
        raise AppError("History backend did not return a successful query.")
    data = document.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise AppError(problem)
    results = data.get("result")
    if not isinstance(results, list) or len(results) > 1:
        raise AppError(problem)
    partial = False
    for key in ("warnings", "infos"):
        notices = document.get(key, [])
        if (
            not isinstance(notices, list)
            or len(notices) > 16
            or any(not isinstance(value, str) or len(value) > 512 for value in notices)
        ):
            raise AppError(problem)
        partial |= bool(notices)
    grid = [
        HistoryPoint(start + timedelta(seconds=index * step_seconds), None)
        for index in range(count)
    ]
    if not results:
        return tuple(grid), partial
    result = results[0]
    values = result.get("values") if isinstance(result, dict) else None
    if not isinstance(values, list) or len(values) > count:
        raise AppError(problem)
    previous = -1
    for point in values:
        if not isinstance(point, list) or len(point) != 2:
            raise AppError(problem)
        timestamp, raw = point
        if (
            type(timestamp) not in {int, float}
            or not -1e12 <= timestamp <= 1e12
            or not math.isfinite(timestamp)
            or not isinstance(raw, str)
            or not 1 <= len(raw) <= 64
        ):
            raise AppError(problem)
        position = (timestamp - start.timestamp()) / step_seconds
        index = round(position)
        if not 0 <= index < count or abs(position - index) > 0.000001 or index <= previous:
            raise AppError(problem)
        previous = index
        value: Decimal | None
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise AppError(problem) from None
        if not value.is_finite():
            value = None
            partial = True
        elif not 0 <= value <= Decimal("1e30"):
            raise AppError(problem)
        grid[index] = HistoryPoint(grid[index].timestamp, value)
    return tuple(grid), partial or len(values) != count
