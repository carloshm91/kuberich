"""Bounded aggregate history, its declared scope and explicit availability."""

import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from kuberich.domain.connections import namespace_name
from kuberich.domain.resources import ApiResource, ResourceSnapshot
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

HISTORY_SECONDS = 900
HISTORY_STEP_SECONDS = 15
HISTORY_MAX_AGE = 60
MAX_HISTORY_POINTS = 2048
MAX_SERIES_POINTS = 721
MAX_SNAPSHOT_SERIES = 32
MAX_SNAPSHOT_POINTS = 16384
MAX_HISTORY_BODY_BYTES = 1024 * 1024
MAX_HISTORY_QUERIES = 12
MAX_HISTORY_QUERY_BYTES = 8192
MAX_HISTORY_LABELS = 32
MAX_HISTORY_NOTICES = 16
MAX_HISTORY_MEMBERS = 256
MAX_HISTORY_CACHE_ENTRIES = 8
MAX_HISTORY_CACHE_POINTS = 65536
MAX_HISTORY_CACHE_BYTES = 4 * 1024 * 1024
HISTORY_CACHE_TTL = 30
HISTORY_RANGES = (900, 1800, 3600, 10800, 21600, 43200, 86400)
_HISTORY_STEPS = dict(zip(HISTORY_RANGES, (15, 15, 15, 30, 60, 60, 120), strict=True))
type Provider = Literal["auto", "prometheus", "victoriametrics", "thanos"]
type HistoryRange = Literal[900, 1800, 3600, 10800, 21600, 43200, 86400]
type MetricFamily = Literal["cpu", "memory", "network", "filesystem"]
type MembershipMode = Literal["backend-history", "current-members"]
type ScopeKind = Literal["cluster", "node", "workload", "pod", "container"]
type MembershipStatus = Literal[
    "uid-observed", "name-inferred", "current-only", "partial", "unavailable"
]
type SourceStatus = Literal["available", "partial", "no-data", "unavailable", "invalid"]
type EndpointStatus = Literal[
    "unverified",
    "compatible",
    "unavailable",
    "unauthorized",
    "forbidden",
    "invalid-response",
    "timeout",
    "configuration-conflict",
    "cancelled",
]
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
    UNAUTHORIZED = "unauthorized"
    INVALID_RESPONSE = "invalid response"
    TIMEOUT = "timeout"
    CONFIGURATION_CONFLICT = "configuration conflict"
    CANCELLED = "cancelled"


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


def _matchers(
    pairs: tuple[tuple[str, str], ...], endpoint: "HistoryBackend | ExternalHistoryBackend"
) -> None:
    # Reuse the Service contract so external and family selectors cannot drift.
    HistoryBackend(
        "observability",
        "history",
        matchers=pairs,
        cluster_label=endpoint.cluster_label,
        cluster_value=endpoint.cluster_value,
    )


def history_prefix(value: str) -> str:
    """A bounded literal API prefix; no URL escapes or dot-segment normalization."""
    if (
        not isinstance(value, str)
        or len(value) > 512
        or (
            value
            and (not value.startswith("/") or re.fullmatch(r"/[A-Za-z0-9_./-]*", value) is None)
        )
    ):
        raise AppError("History API prefix requires a bounded absolute path.")
    if any(part in {".", ".."} for part in value.split("/")) or "//" in value:
        raise AppError("History API prefix cannot contain dot or empty segments.")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class ExternalHistoryBackend:
    url: str
    matchers: tuple[tuple[str, str], ...] = ()
    cluster_label: str | None = None
    cluster_value: str | None = None
    ca_file: Path | None = field(default=None, repr=False)
    bearer_token_file: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.url, str)
            or len(self.url) > 2048
            or any(ord(char) < 33 or ord(char) > 126 for char in self.url)
        ):
            raise AppError("History URL requires bounded HTTP or HTTPS text.")
        try:
            parts = urlsplit(self.url)
            port = parts.port
        except ValueError:
            raise AppError("History URL is invalid.") from None
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or "?" in self.url
            or "#" in self.url
            or "\\" in self.url
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise AppError(
                "History URL must have an origin without credentials, query or fragment."
            )
        prefix = history_prefix(parts.path)
        object.__setattr__(self, "url", urlunsplit((parts.scheme, parts.netloc, prefix, "", "")))
        HistoryBackend(
            "observability",
            "history",
            matchers=self.matchers,
            cluster_label=self.cluster_label,
            cluster_value=self.cluster_value,
        )
        if any(
            value is not None and not isinstance(value, Path)
            for value in (self.ca_file, self.bearer_token_file)
        ):
            raise AppError("History credential files require filesystem paths.")
        if self.bearer_token_file is not None and parts.scheme != "https":
            raise AppError("History bearer authentication requires HTTPS.")

    def labels(self, namespace: str | None) -> tuple[tuple[str, str], ...]:
        return HistoryBackend(
            "observability",
            "history",
            matchers=self.matchers,
            cluster_label=self.cluster_label,
            cluster_value=self.cluster_value,
        ).labels(namespace)

    def scope_label(self, namespace: str | None) -> str:
        return HistoryBackend(
            "observability",
            "history",
            matchers=self.matchers,
            cluster_label=self.cluster_label,
            cluster_value=self.cluster_value,
        ).scope_label(namespace)

    @property
    def origin(self) -> str:
        parts = urlsplit(self.url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    @property
    def prefix(self) -> str:
        return urlsplit(self.url).path


@dataclass(frozen=True, slots=True)
class HistoryOptions:
    endpoint: HistoryBackend | ExternalHistoryBackend
    provider: Provider = "auto"
    profile: Literal["kubernetes-standard"] = "kubernetes-standard"
    node_matchers: tuple[tuple[str, str], ...] = ()
    state_matchers: tuple[tuple[str, str], ...] = ()
    api_prefix: str = ""
    rate_window_seconds: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, (HistoryBackend, ExternalHistoryBackend)) or (
            self.provider not in {"auto", "prometheus", "victoriametrics", "thanos"}
            or self.profile != "kubernetes-standard"
        ):
            raise AppError("History endpoint/provider/profile is unsupported.")
        _matchers(self.node_matchers, self.endpoint)
        _matchers(self.state_matchers, self.endpoint)
        object.__setattr__(self, "api_prefix", history_prefix(self.api_prefix))
        if isinstance(self.endpoint, ExternalHistoryBackend) and self.api_prefix:
            raise AppError("An external history URL already carries its API prefix.")
        if type(self.rate_window_seconds) is not int or not 60 <= self.rate_window_seconds <= 3600:
            raise AppError("History rate window must be between 60 and 3600 seconds.")


@dataclass(frozen=True, slots=True)
class HistoryScope:
    session: SessionIdentity
    kind: ScopeKind
    namespace: str | None = None
    target: ResourceTarget | None = None
    resource: ApiResource | None = None
    created_at: datetime | None = None
    container_field: Literal["containers", "initContainers", "ephemeralContainers"] | None = None
    membership: MembershipMode = "backend-history"
    host_network: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session, SessionIdentity)
            or self.kind not in {"cluster", "node", "workload", "pod", "container"}
            or self.membership not in {"backend-history", "current-members"}
        ):
            raise AppError("History requires an explicit supported scope and session.")
        if self.namespace is not None:
            namespace_name(self.namespace)
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise AppError("History creation time requires a timezone.")
        if type(self.host_network) is not bool:
            raise AppError("History host-network evidence must be boolean.")
        if self.kind == "cluster":
            if (
                self.target is not None
                or self.resource is not None
                or self.container_field is not None
            ):
                raise AppError("Cluster history cannot carry a resource target.")
            return
        target, resource = self.target, self.resource
        if (
            target is None
            or resource is None
            or (
                target.session != self.session
                or target.namespace != self.namespace
                or target.group != resource.group
                or target.resource != resource.name
                or resource.namespaced != (self.namespace is not None)
            )
        ):
            raise AppError(
                "History target must match its captured session, resource and namespace."
            )
        expected = {
            "node": {("", "nodes")},
            "pod": {("", "pods")},
            "container": {("", "pods")},
            "workload": {
                ("apps", "deployments"),
                ("apps", "replicasets"),
                ("apps", "statefulsets"),
                ("apps", "daemonsets"),
                ("batch", "jobs"),
                ("batch", "cronjobs"),
                ("", "replicationcontrollers"),
            },
        }
        if (resource.group, resource.name) not in expected[self.kind]:
            raise AppError("History resource does not support the selected scope.")
        if self.kind == "container":
            if target.container is None or self.container_field not in {
                "containers",
                "initContainers",
                "ephemeralContainers",
            }:
                raise AppError("Container history requires a captured name and declaration family.")
        elif target.container is not None or self.container_field is not None:
            raise AppError("Only container history can carry a selected container.")


@dataclass(frozen=True, slots=True)
class MemberIdentity:
    namespace: str
    pod: str
    uid: str | None = None
    created_at: datetime | None = None
    owner_uid: str | None = None

    def __post_init__(self) -> None:
        namespace_name(self.namespace)
        namespace_name(self.pod)
        for value in (self.uid, self.owner_uid):
            if value is not None:
                _matcher("uid", value)
        if self.created_at is not None and self.created_at.tzinfo is None:
            raise AppError("History member creation time requires a timezone.")


@dataclass(frozen=True, slots=True)
class MembershipEvidence:
    mode: MembershipMode = "backend-history"
    status: MembershipStatus = "name-inferred"
    observed_at: datetime | None = None
    members: tuple[MemberIdentity, ...] = ()
    fingerprint: str = ""
    detail_code: str = "backend-name-linkage"


@dataclass(frozen=True, slots=True)
class HistoryNotice:
    code: str
    message: str
    severity: Literal["info", "warning"] = "warning"


class PointQuality(StrEnum):
    OBSERVED = "observed"
    MISSING = "missing"
    NONFINITE = "nonfinite"
    INVALID = "invalid"
    IDENTITY_UNCERTAIN = "identity-uncertain"
    MEMBERSHIP_PARTIAL = "membership-partial"


@dataclass(frozen=True, slots=True)
class EndpointIdentity:
    transport: Literal["service", "external"]
    provider: Provider = "auto"
    namespace: str | None = None
    service: str | None = None
    service_uid: str | None = None
    origin: str | None = None
    prefix: str = ""
    status: EndpointStatus = "unverified"
    compatibility: str = "Provider unverified"


@dataclass(frozen=True, slots=True)
class BackendCandidate:
    namespace: str
    service: str
    uid: str
    port: int
    prefix: str = ""
    provider_hint: Provider = "auto"
    scheme: Literal["http", "https"] = "http"


@dataclass(frozen=True, slots=True)
class BackendCandidates:
    items: tuple[BackendCandidate, ...] = ()
    complete: bool = True
    sources: tuple[tuple[str, SourceStatus], ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryRequest:
    id: UUID
    scope: HistoryScope
    options: HistoryOptions
    start: datetime
    end: datetime
    step_seconds: int
    families: tuple[MetricFamily, ...]
    config_revision: int

    def __post_init__(self) -> None:
        duration = (
            (self.end - self.start).total_seconds()
            if (self.start.tzinfo is not None and self.end.tzinfo is not None)
            else -1
        )
        if (
            not isinstance(self.id, UUID)
            or duration not in _HISTORY_STEPS
            or (
                type(self.step_seconds) is not int
                or self.step_seconds != _HISTORY_STEPS[int(duration)]
                or self.start.timestamp() % self.step_seconds != 0
                or self.end.timestamp() % self.step_seconds != 0
                or type(self.config_revision) is not int
                or self.config_revision < 0
                or not isinstance(self.families, tuple)
                or not self.families
                or len(set(self.families)) != len(self.families)
                or any(
                    family not in {"cpu", "memory", "network", "filesystem"}
                    for family in self.families
                )
            )
        ):
            raise AppError("History request has an unsupported window, family or revision.")


@dataclass(frozen=True, slots=True)
class QuerySpec:
    key: str
    expression: str = field(repr=False)
    unit: Literal["cores", "bytes", "bytes/s", "count"] = "count"
    role: Literal["value", "membership", "coverage"] = "value"
    allowed_labels: frozenset[str] = frozenset()
    maximum_series: int = 1
    label: str = ""
    measurement: str = ""
    family: MetricFamily | None = None
    created_after: datetime | None = None
    rate_window_seconds: int = 0

    def __post_init__(self) -> None:
        if (
            not self.key
            or len(self.key) > 64
            or len(self.expression.encode()) > MAX_HISTORY_QUERY_BYTES
        ):
            raise AppError("History query identity or expression exceeds its bound.")
        if not 1 <= self.maximum_series <= MAX_SNAPSHOT_SERIES or (
            len(self.allowed_labels) > MAX_HISTORY_LABELS
            or any(_LABEL.fullmatch(name) is None for name in self.allowed_labels)
        ):
            raise AppError("History query series or label bound is invalid.")


@dataclass(frozen=True, slots=True)
class HistoryQueryPlan:
    request: HistoryRequest
    queries: tuple[QuerySpec, ...]
    provider_parameters: tuple[tuple[str, str], ...]
    membership_evidence: MembershipEvidence
    notices: tuple[HistoryNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedHistory:
    series: tuple["HistorySeries", ...]
    notices: tuple[HistoryNotice, ...]
    source_status: SourceStatus
    accounted_bytes: int


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
    labels: tuple[tuple[str, str], ...] = ()
    quality: tuple[PointQuality, ...] = ()
    measurement: str = ""


@dataclass(frozen=True)
class HistorySnapshot:
    status: HistoryStatus = HistoryStatus.UNCONFIGURED
    observed_at: datetime | None = None
    start: datetime | None = None
    end: datetime | None = None
    step_seconds: int = HISTORY_STEP_SECONDS
    series: tuple[HistorySeries, ...] = ()
    detail: str = "Configure an observability history backend for this context."
    scope_label: str = "No historical backend selected"
    request_id: UUID | None = None
    endpoint_identity: EndpointIdentity | None = None
    membership_evidence: MembershipEvidence | None = None
    source_status: tuple[tuple[str, SourceStatus], ...] = ()
    notices: tuple[HistoryNotice, ...] = ()
    accounted_bytes: int = 0

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
                replace(
                    series,
                    points=tuple(replace(point, value=None) for point in series.points),
                    quality=tuple(
                        PointQuality.MISSING if quality == PointQuality.OBSERVED else quality
                        for quality in series.quality
                    ),
                )
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
        elif (
            not 0 <= value <= Decimal("1e30")
            or not -64 <= cast(int, value.as_tuple().exponent) <= 30
        ):
            raise AppError(problem)
        grid[index] = HistoryPoint(grid[index].timestamp, value)
    return tuple(grid), partial or len(values) != count


def history_window(now: datetime, seconds: HistoryRange) -> tuple[datetime, datetime, int]:
    """Align a supported evaluation interval to UTC and its fixed grid."""
    if now.tzinfo is None or type(seconds) is not int or seconds not in _HISTORY_STEPS:
        raise AppError("History requires a timezone and a supported 15m-24h range.")
    step = _HISTORY_STEPS[seconds]
    end = datetime.fromtimestamp(math.floor(now.timestamp() / step) * step, UTC)
    return end - timedelta(seconds=seconds), end, step


def build_history_plan(request: HistoryRequest, membership: MembershipEvidence) -> HistoryQueryPlan:
    from kuberich.domain.history_queries import compile_plan

    return compile_plan(request, membership)


def parse_history_matrix(
    document: object,
    query: QuerySpec,
    start: datetime,
    end: datetime,
    step_seconds: int,
    *,
    remaining_series: int = MAX_SNAPSHOT_SERIES,
    remaining_points: int = MAX_SNAPSHOT_POINTS,
) -> ParsedHistory:
    from kuberich.domain.history_queries import parse_matrix

    return parse_matrix(
        document,
        query,
        start,
        end,
        step_seconds,
        remaining_series=remaining_series,
        remaining_points=remaining_points,
    )


def current_history_members(
    target: ResourceTarget,
    resource: ApiResource,
    pods: ResourceSnapshot,
    intermediates: ResourceSnapshot | None,
    after: ResourceSnapshot,
) -> MembershipEvidence:
    from kuberich.domain.history_membership import current_members

    return current_members(target, resource, pods, intermediates, after)


def finalize_history_results(
    plan: HistoryQueryPlan,
    results: tuple[tuple[QuerySpec, ParsedHistory], ...],
) -> ParsedHistory:
    from kuberich.domain.history_queries import finalize_results

    return finalize_results(plan, results)
