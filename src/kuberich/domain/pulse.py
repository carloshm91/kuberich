"""Bounded cluster overview decisions and exact captured drill-downs."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from kuberich.domain.connections import namespace_name
from kuberich.domain.history import HistorySnapshot
from kuberich.domain.metrics import (
    MetricReport,
    MetricStatus,
    ResourceAmount,
    aggregate,
    node_sample,
    pod_budget,
    pod_sample,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ApiResource, ResourceRecord, ResourceSnapshot
from kuberich.domain.targets import SessionIdentity

FAMILIES = (
    ("", "nodes"),
    ("", "pods"),
    ("apps", "deployments"),
    ("apps", "replicasets"),
    ("apps", "statefulsets"),
    ("apps", "daemonsets"),
    ("batch", "jobs"),
    ("batch", "cronjobs"),
)


class PulseStatus(StrEnum):
    LOADING = "loading"
    VALID = "available"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"
    FAILED = "failed"
    PARTIAL = "partial"
    STALE = "stale"


class PulseHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    COMPLETED = "completed"


@dataclass(frozen=True)
class PulseScope:
    session: SessionIdentity
    namespace: str | None

    def __post_init__(self) -> None:
        if self.namespace is not None:
            namespace_name(self.namespace)


@dataclass(frozen=True)
class PulseSource:
    """Last successful collection time, separate from its latest read attempt."""

    key: str
    resource: ApiResource | None
    namespace: str | None
    status: PulseStatus
    observed_at: datetime | None
    complete: bool = False
    limited: bool = False
    count: int | None = None
    detail: str = ""
    attempted_at: datetime | None = None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _conditions(data: dict[str, Any]) -> dict[str, str]:
    entries = data.get("conditions")
    if not isinstance(entries, list) or len(entries) > 128:
        return {}
    result: dict[str, str] = {}
    for entry in entries:
        item = _object(entry)
        name, state = item.get("type"), item.get("status")
        if isinstance(name, str) and state in ("True", "False", "Unknown"):
            # Contradictory duplicate conditions cannot establish health.
            result[name] = state if name not in result else "Unknown"
    return result


def _count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _node_ready(manifest: dict[str, Any]) -> str | None:
    return _conditions(_object(manifest.get("status"))).get("Ready")


def _node_pressure(manifest: dict[str, Any]) -> bool:
    conditions = _conditions(_object(manifest.get("status")))
    return any(
        conditions.get(key) == "True"
        for key in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")
    )


def health(record: ResourceRecord) -> PulseHealth:
    """Known observed state only; missing/malformed controller data stays unknown."""
    manifest = record.manifest
    kind = manifest.get("kind")
    spec, status = _object(manifest.get("spec")), _object(manifest.get("status"))
    conditions = _conditions(status)
    if record.metadata_only:
        return PulseHealth.UNKNOWN
    if kind == "Node":
        ready = _node_ready(manifest)
        if ready == "False" or _node_pressure(manifest):
            return PulseHealth.DEGRADED
        return PulseHealth.HEALTHY if ready == "True" else PulseHealth.UNKNOWN
    if kind == "Pod":
        phase = status.get("phase")
        if phase == "Succeeded":
            return PulseHealth.COMPLETED
        if phase in ("Failed", "Pending"):
            return PulseHealth.DEGRADED
        if phase == "Running":
            ready = conditions.get("Ready")
            return (
                PulseHealth.HEALTHY
                if ready == "True"
                else PulseHealth.DEGRADED
                if ready == "False"
                else PulseHealth.UNKNOWN
            )
        return PulseHealth.UNKNOWN
    if kind == "Job":
        if conditions.get("Failed") == "True":
            return PulseHealth.DEGRADED
        if conditions.get("Complete") == "True":
            return PulseHealth.COMPLETED
        if conditions.get("Failed") == "Unknown" or spec.get("suspend") is True:
            return PulseHealth.UNKNOWN
        active, failed = _count(status.get("active")), _count(status.get("failed", 0))
        if failed is not None and failed > 0:
            return PulseHealth.DEGRADED
        return PulseHealth.HEALTHY if active is not None and active > 0 else PulseHealth.UNKNOWN
    if kind == "CronJob":
        if spec.get("suspend") is True or not isinstance(spec.get("schedule"), str):
            return PulseHealth.UNKNOWN
        scheduled = _timestamp(status.get("lastScheduleTime"))
        successful = _timestamp(status.get("lastSuccessfulTime"))
        # A scheduled Job alone does not establish that its latest run succeeded.
        return (
            PulseHealth.HEALTHY
            if scheduled is not None and successful is not None and successful >= scheduled
            else PulseHealth.UNKNOWN
        )
    metadata = _object(manifest.get("metadata"))
    generation = _count(metadata.get("generation"))
    observed = _count(status.get("observedGeneration"))
    if generation is None or observed is None or observed < generation:
        return PulseHealth.UNKNOWN
    if kind == "DaemonSet":
        desired = _count(status.get("desiredNumberScheduled"))
        values = tuple(
            _count(status.get(key))
            for key in ("numberReady", "numberAvailable", "updatedNumberScheduled")
        )
    elif kind in {"Deployment", "ReplicaSet", "StatefulSet"}:
        desired = _count(spec.get("replicas", 1))
        keys = (
            ("readyReplicas", "availableReplicas", "updatedReplicas")
            if kind == "Deployment"
            else ("readyReplicas", "updatedReplicas")
            if kind == "StatefulSet"
            else ("readyReplicas", "availableReplicas")
        )
        values = tuple(_count(status.get(key, 0)) for key in keys)
    else:
        return PulseHealth.UNKNOWN
    if desired is None or not status or any(value is None for value in values):
        return PulseHealth.UNKNOWN
    if any(value != desired for value in values):
        return PulseHealth.DEGRADED
    if kind == "StatefulSet" and status.get("currentRevision") != status.get("updateRevision"):
        return PulseHealth.DEGRADED
    if (
        conditions.get("Available") == "False"
        or conditions.get("Progressing") == "False"
        or conditions.get("ReplicaFailure") == "True"
    ):
        return PulseHealth.DEGRADED
    if any(value == "Unknown" for value in conditions.values()):
        return PulseHealth.UNKNOWN
    return PulseHealth.HEALTHY


class PulsePredicate(StrEnum):
    ALL = "all"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    NODE_READY = "node-ready"
    NODE_NOT_READY = "node-not-ready"
    NODE_CORDONED = "node-cordoned"
    NODE_PRESSURE = "node-pressure"
    POD_RUNNING = "pod-running"
    POD_PENDING = "pod-pending"
    POD_SUCCEEDED = "pod-succeeded"
    POD_FAILED = "pod-failed"
    POD_UNSCHEDULED = "pod-unscheduled"
    POD_NOT_READY = "pod-not-ready"
    POD_ACTIVE = "pod-active"

    def matches(self, record: ResourceRecord) -> bool:
        if self is PulsePredicate.ALL:
            return True
        if self.value in {value.value for value in PulseHealth}:
            return health(record).value == self.value
        manifest = record.manifest
        if record.metadata_only:
            return False
        if self.value.startswith("node-"):
            if manifest.get("kind") != "Node":
                return False
            if self is PulsePredicate.NODE_CORDONED:
                return _object(manifest.get("spec")).get("unschedulable") is True
            if self is PulsePredicate.NODE_PRESSURE:
                return _node_pressure(manifest)
            return _node_ready(manifest) == (
                "True" if self is PulsePredicate.NODE_READY else "False"
            )
        if manifest.get("kind") != "Pod":
            return False
        status = _object(manifest.get("status"))
        phase = status.get("phase")
        if self is PulsePredicate.POD_ACTIVE:
            return phase not in ("Succeeded", "Failed")
        if self is PulsePredicate.POD_UNSCHEDULED:
            return phase == "Pending" and not _object(manifest.get("spec")).get("nodeName")
        if self is PulsePredicate.POD_NOT_READY:
            return phase == "Running" and _conditions(status).get("Ready") == "False"
        return (
            phase
            == {
                PulsePredicate.POD_RUNNING: "Running",
                PulsePredicate.POD_PENDING: "Pending",
                PulsePredicate.POD_SUCCEEDED: "Succeeded",
                PulsePredicate.POD_FAILED: "Failed",
            }[self]
        )

    @property
    def query(self) -> ResourceQuery:
        field_selector = {
            PulsePredicate.NODE_CORDONED: "spec.unschedulable=true",
            PulsePredicate.POD_RUNNING: "status.phase=Running",
            PulsePredicate.POD_PENDING: "status.phase=Pending",
            PulsePredicate.POD_SUCCEEDED: "status.phase=Succeeded",
            PulsePredicate.POD_FAILED: "status.phase=Failed",
            PulsePredicate.POD_UNSCHEDULED: "status.phase=Pending,spec.nodeName=",
            PulsePredicate.POD_ACTIVE: "status.phase!=Succeeded,status.phase!=Failed",
        }.get(self)
        return ResourceQuery(field_selector=field_selector)


@dataclass(frozen=True)
class PulseDrilldown:
    resource: ApiResource
    namespace: str | None
    predicate: PulsePredicate = PulsePredicate.ALL
    sort: str = "name"
    uid: str | None = None
    query: ResourceQuery = field(default_factory=ResourceQuery)
    descending: bool = False


@dataclass(frozen=True)
class PulseRow:
    key: str
    label: str
    count: int | None
    source: str
    drilldown: PulseDrilldown | None
    detail: str = ""


@dataclass(frozen=True)
class PulseSnapshot:
    scope: PulseScope
    sources: tuple[PulseSource, ...] = ()
    rows: tuple[PulseRow, ...] = ()
    node_metrics: MetricReport = field(default_factory=MetricReport)
    pod_metrics: MetricReport = field(default_factory=MetricReport)
    history: HistorySnapshot | None = None
    observed_at: datetime | None = None
    capacity_observed_at: datetime | None = None
    budgets_observed_at: datetime | None = None


def predicates(name: str) -> tuple[PulsePredicate, ...]:
    common = tuple(PulsePredicate(value.value) for value in PulseHealth)
    if name == "nodes":
        return (
            PulsePredicate.ALL,
            PulsePredicate.NODE_READY,
            PulsePredicate.NODE_NOT_READY,
            PulsePredicate.UNKNOWN,
            PulsePredicate.NODE_CORDONED,
            PulsePredicate.NODE_PRESSURE,
        )
    if name == "pods":
        return (
            PulsePredicate.ALL,
            PulsePredicate.POD_RUNNING,
            PulsePredicate.POD_PENDING,
            PulsePredicate.POD_SUCCEEDED,
            PulsePredicate.POD_FAILED,
            PulsePredicate.POD_UNSCHEDULED,
            PulsePredicate.POD_NOT_READY,
            PulsePredicate.UNKNOWN,
        )
    return (PulsePredicate.ALL, *common)


def rows(source: PulseSource, counts: dict[PulsePredicate, int] | None) -> tuple[PulseRow, ...]:
    return tuple(
        PulseRow(
            f"{source.key}:{predicate.value}",
            f"{source.key.replace('sets', ' sets').title()} · {predicate.value.replace('-', ' ')}",
            counts.get(predicate, 0) if counts is not None else None,
            source.key,
            PulseDrilldown(source.resource, source.namespace, predicate, query=predicate.query)
            if source.resource is not None
            else None,
            source.detail,
        )
        for predicate in predicates(source.key)
    )


def pod_budgets(snapshot: ResourceSnapshot) -> MetricReport:
    return aggregate(
        tuple(
            pod_budget(record)
            for record in snapshot.items
            if PulsePredicate.POD_ACTIVE.matches(record)
        ),
        complete=snapshot.collection.complete,
    )


def _node_totals(reports: tuple[MetricReport, ...], complete: bool) -> MetricReport:
    full = complete and bool(reports) and all(r.status is MetricStatus.VALID for r in reports)

    def total(key: str) -> ResourceAmount:
        values = tuple(getattr(report, key) for report in reports)

        def summed(field: str) -> Decimal | None:
            amounts = tuple(getattr(value, field) for value in values)
            return (
                sum((value for value in amounts if value is not None), Decimal(0))
                if amounts and all(value is not None for value in amounts)
                else None
            )

        return ResourceAmount(
            usage=summed("usage"),
            capacity=summed("capacity"),
            allocatable=summed("allocatable"),
            partial=not full,
            uncertain=not complete,
        )

    return MetricReport(
        MetricStatus.VALID if full else MetricStatus.PARTIAL if reports else MetricStatus.NO_SAMPLE,
        total("cpu"),
        total("memory"),
        min((r.timestamp for r in reports if r.timestamp is not None), default=None),
        max((r.window for r in reports if r.window is not None), default=None),
        f"{sum(r.status is MetricStatus.VALID for r in reports)}/{len(reports)} Nodes"
        + (" · membership incomplete" if not complete else ""),
    )


def overview_metrics(
    selected: ResourceSnapshot,
    samples: ResourceSnapshot | None,
    after: ResourceSnapshot | None,
    now: datetime,
) -> MetricReport:
    """Reverify actual UIDs around name-only metrics; Node totals preserve capacity."""
    verified = {(r.namespace, r.name): r.uid for r in after.items} if after is not None else {}
    sample_index = {(r.namespace, r.name): r for r in samples.items} if samples is not None else {}
    complete = (
        selected.collection.complete
        and after is not None
        and after.collection.complete
        and samples is not None
        and samples.collection.complete
        and len(selected.items) == len(after.items)
    )
    reports = []
    for record in selected.items:
        stable = (
            record.uid is not None and verified.get((record.namespace, record.name)) == record.uid
        )
        complete = complete and stable
        sample = sample_index.get((record.namespace, record.name)) if stable else None
        if selected.resource.name == "nodes":
            reports.append(node_sample(record, sample, (), now))
        elif PulsePredicate.POD_ACTIVE.matches(record):
            reports.append(pod_sample(record, sample, now))
    if selected.resource.name == "nodes":
        return _node_totals(tuple(reports), complete).fresh(now)
    return aggregate(tuple(reports), complete=complete).fresh(now)


def expire_metrics(snapshot: PulseSnapshot, now: datetime) -> PulseSnapshot:
    """Current values and history expire independently of the next blocked API read."""
    reports = {
        "node_metrics": snapshot.node_metrics.fresh(now),
        "pod_metrics": snapshot.pod_metrics.fresh(now),
    }
    return replace(
        snapshot,
        sources=tuple(
            replace(source, status=PulseStatus.STALE)
            if source.key in reports and reports[source.key].status is MetricStatus.STALE
            else source
            for source in snapshot.sources
        ),
        node_metrics=reports["node_metrics"],
        pod_metrics=reports["pod_metrics"],
        history=snapshot.history.fresh(now) if snapshot.history is not None else None,
    )
