"""Current resource samples and honest budget reconciliation, without SDK/UI types."""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from kuberich.domain.quantities import parse_quantity
from kuberich.domain.resources import ResourceRecord
from kuberich.errors import AppError

MAX_SAMPLE_AGE = 60.0
MAX_CONTAINERS = 128
MAX_RESOURCES = 128
ZERO = Decimal(0)
METRIC_KEYS = (
    "cpu",
    "memory",
    "cpu-req",
    "cpu-lim",
    "memory-req",
    "memory-lim",
    "cpu-percent-request",
    "cpu-percent-limit",
    "memory-percent-request",
    "memory-percent-limit",
    "metrics",
    "sample",
    "window",
    "extended",
    "cpu-capacity",
    "cpu-allocatable",
    "memory-capacity",
    "memory-allocatable",
    "cpu-percent-allocatable",
    "memory-percent-allocatable",
)
METRIC_LABELS = {
    "cpu": "CPU(m)",
    "memory": "MEM(MiB)",
    "sample": "SAMPLE(UTC)",
    "window": "WINDOW(s)",
    "cpu-req": "CPU REQ(m)",
    "cpu-lim": "CPU LIM(m)",
    "memory-req": "MEM REQ(MiB)",
    "memory-lim": "MEM LIM(MiB)",
    "cpu-percent-request": "CPU%REQ",
    "cpu-percent-limit": "CPU%LIM",
    "memory-percent-request": "MEM%REQ",
    "memory-percent-limit": "MEM%LIM",
    "cpu-capacity": "CPU CAP(m)",
    "cpu-allocatable": "CPU ALLOC(m)",
    "memory-capacity": "MEM CAP(MiB)",
    "memory-allocatable": "MEM ALLOC(MiB)",
    "cpu-percent-allocatable": "CPU%ALLOC",
    "memory-percent-allocatable": "MEM%ALLOC",
}


class MetricStatus(StrEnum):
    VALID = "valid"
    UNAVAILABLE = "API unavailable"
    FORBIDDEN = "forbidden"
    NO_SAMPLE = "no sample"
    STALE = "stale"
    ERROR = "read failed"
    PARTIAL = "partial"


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _entries(value: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > MAX_CONTAINERS
        or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or not 1 <= len(entry["name"]) <= 253
            for entry in value
        )
    ):
        raise AppError("Invalid or excessive metrics container entries.")
    return value


def amount(value: object) -> Decimal | None:
    number = parse_quantity(value)
    return number if number is not None and number <= 2**63 - 1 else None


def _resources(value: Any) -> dict[str, Decimal | None]:
    data = _object(value)
    if len(data) > MAX_RESOURCES or any(
        not isinstance(key, str) or not 1 <= len(key) <= 253 for key in data
    ):
        raise AppError("Invalid or excessive resource keys.")
    return {key: amount(value) for key, value in data.items()}


def percentage(usage: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    return usage * 100 / denominator if usage is not None and denominator else None


def number(value: Decimal | None, unit: str = "") -> str:
    if value is None:
        return "N/A"
    scaled = value * 1000 if unit == "cpu" else value / 2**20 if unit == "memory" else value
    if ZERO < scaled < Decimal("0.001"):
        return "<0.001"
    return f"{scaled:.3f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class ResourceAmount:
    usage: Decimal | None = None
    request: Decimal | None = None
    limit: Decimal | None = None
    unlimited: bool = False
    uncertain: bool = False
    partial: bool = False
    capacity: Decimal | None = None
    allocatable: Decimal | None = None

    def percent(self, denominator: str) -> Decimal | None:
        return (
            None
            if self.partial or (self.uncertain and denominator != "allocatable")
            else percentage(self.usage, getattr(self, denominator))
        )


@dataclass(frozen=True)
class MetricReport:
    status: MetricStatus = MetricStatus.NO_SAMPLE
    cpu: ResourceAmount = ResourceAmount()
    memory: ResourceAmount = ResourceAmount()
    timestamp: datetime | None = None
    window: Decimal | None = None
    detail: str = ""
    extended: tuple[tuple[str, ResourceAmount], ...] = ()
    containers: tuple[tuple[str, "MetricReport"], ...] = ()
    allocation_uncertain: bool = False

    def fresh(self, now: datetime) -> "MetricReport":
        if self.timestamp is not None and (now - self.timestamp).total_seconds() > MAX_SAMPLE_AGE:
            return replace(
                self,
                status=MetricStatus.STALE,
                cpu=replace(self.cpu, usage=None),
                memory=replace(self.memory, usage=None),
                containers=tuple((name, report.fresh(now)) for name, report in self.containers),
            )
        return self

    def value(self, key: str) -> tuple[str, str | Decimal | None]:
        if key == "metrics":
            text = str(self.status) + (f" · {self.detail}" if self.detail else "")
            return text, text
        if key == "sample":
            return (
                self.timestamp.astimezone(UTC).isoformat() if self.timestamp else "N/A",
                Decimal(str(self.timestamp.timestamp())) if self.timestamp else None,
            )
        if key == "window":
            return number(self.window), self.window
        if key == "extended":
            text = (
                "; ".join(
                    f"{key} req={'N/A' if value.uncertain else number(value.request)} lim={'N/A' if value.uncertain else 'unlimited' if value.unlimited else number(value.limit)}"
                    + (
                        f" cap={number(value.capacity)} alloc={number(value.allocatable)}"
                        if value.capacity is not None or value.allocatable is not None
                        else ""
                    )
                    + (" (uncertain budget)" if value.uncertain else "")
                    for key, value in self.extended
                )
                or "—"
            )
            return text, text
        resource, separator, field = key.partition("-")
        value = self.cpu if resource == "cpu" else self.memory
        if field.startswith("percent-"):
            result = value.percent(field.removeprefix("percent-"))
            return number(result), result
        selected = {"req": "request", "lim": "limit"}.get(field, field) if separator else "usage"
        result = getattr(value, selected)
        if selected in {"request", "limit"} and value.uncertain:
            return "N/A (budget)", None
        if selected == "limit" and value.unlimited:
            return "unlimited", None
        return number(result, resource), result


@dataclass(frozen=True)
class MetricsSnapshot:
    reports: tuple[tuple[str, MetricReport], ...] = ()
    status: MetricStatus = MetricStatus.NO_SAMPLE
    detail: str = "Waiting for metrics"

    def report(self, uid: str, now: datetime | None = None) -> MetricReport:
        # Projection indexes once per batch; this convenience port is for captured containers.
        return (
            dict(self.reports)
            .get(uid, MetricReport(self.status, detail=self.detail))
            .fresh(now or datetime.now(UTC))
        )


def _budget(resources: Any, key: str, *, uncertain: bool = False) -> ResourceAmount:
    resources = _object(resources)
    requests, limits = _object(resources.get("requests")), _object(resources.get("limits"))
    return ResourceAmount(
        request=amount(requests.get(key)) if key in {"cpu", "memory"} or key in requests else ZERO,
        limit=amount(limits.get(key))
        if key in {"cpu", "memory"} or key in limits or key in requests
        else ZERO,
        unlimited=key in {"cpu", "memory"} and key not in limits,
        uncertain=uncertain,
    )


def _sum(values: tuple[ResourceAmount, ...]) -> ResourceAmount:
    requests = tuple(value.request for value in values)
    limits = tuple(value.limit for value in values)
    return ResourceAmount(
        usage=sum((value.usage for value in values if value.usage is not None), ZERO)
        if values and any(value.usage is not None for value in values)
        else None,
        request=sum((value for value in requests if value is not None), ZERO)
        if values and all(value is not None for value in requests)
        else None,
        limit=sum((value for value in limits if value is not None), ZERO)
        if values and all(value is not None for value in limits)
        else None,
        unlimited=bool(values) and any(value.unlimited for value in values),
        uncertain=any(value.uncertain for value in values),
        partial=any(value.partial or value.usage is None for value in values),
    )


def _contradicts(
    observed: Any, declared: dict[str, Decimal | None], *, compute_only: bool = False
) -> bool:
    if not isinstance(observed, dict):
        return True
    # Missing optional telemetry is not a contradiction. Only compare fields
    # actually reported by kubelet; preserve admitted extended-resource requests.
    return any(
        value is None or declared.get(key) is None or value != declared[key]
        for key, value in _resources(observed).items()
        if not compute_only or key in {"cpu", "memory"}
    )


def _allocation_problem(
    declarations: list[dict[str, Any]], statuses: list[Any], status: dict[str, Any]
) -> str | None:
    if status.get("resize"):
        return "reported Pod resize"
    conditions = status.get("conditions") or []
    if not isinstance(conditions, list) or len(conditions) > MAX_CONTAINERS:
        raise AppError("Invalid or excessive Pod conditions.")
    for condition in conditions:
        condition = _object(condition)
        if (
            condition.get("type") in {"PodResizePending", "PodResizeInProgress"}
            and condition.get("status") != "False"
        ):
            return "Pod resize active or unconfirmed"
    declared = {entry["name"]: _object(entry.get("resources")) for entry in declarations}
    if len(declared) != len(declarations):
        return "ambiguous declared container identity"
    seen: set[str] = set()
    for entry in statuses:
        entry = _object(entry)
        name = entry.get("name")
        if not isinstance(name, str) or name not in declared or name in seen:
            return "unconfirmed container allocation identity"
        seen.add(name)
        requested = _resources(declared[name].get("requests"))
        allocated = entry.get("allocatedResources")
        if allocated is not None and _contradicts(allocated, requested, compute_only=True):
            return "declared/allocated container requests differ"
        enacted = entry.get("resources")
        if enacted is not None:
            if not isinstance(enacted, dict):
                return "invalid enacted container resources"
            for field in ("requests", "limits"):
                actual = enacted.get(field)
                if actual is not None and _contradicts(
                    actual, _resources(declared[name].get(field))
                ):
                    return "declared/enacted container resources differ"
    totals: dict[str, dict[str, Decimal | None]] = {}
    for field in ("requests", "limits"):
        total: dict[str, Decimal | None] = {}
        for resources in declared.values():
            for key, value in _resources(resources.get(field)).items():
                previous = total.get(key, ZERO)
                total[key] = (
                    previous + value if previous is not None and value is not None else None
                )
        totals[field] = total
    pod_allocated = status.get("allocatedResources")
    if pod_allocated is not None and _contradicts(
        pod_allocated, totals["requests"], compute_only=True
    ):
        return "declared/allocated Pod requests differ"
    pod_resources = status.get("resources")
    if pod_resources is not None:
        if not isinstance(pod_resources, dict):
            return "invalid enacted Pod resources"
        for field in ("requests", "limits"):
            actual = pod_resources.get(field)
            if actual is not None and _contradicts(actual, totals[field], compute_only=True):
                return "declared/enacted Pod resources differ"
    return None


def pod_budget(record: ResourceRecord) -> MetricReport:
    manifest = record.manifest
    spec, status = _object(manifest.get("spec")), _object(manifest.get("status"))
    declarations = _entries(spec.get("containers") or [])
    statuses = status.get("containerStatuses") or []
    if not isinstance(statuses, list) or len(statuses) > MAX_CONTAINERS:
        raise AppError("Invalid or excessive observed container statuses.")
    keys = {"cpu", "memory"}
    for declaration in (*declarations, *_entries(spec.get("initContainers") or [])):
        for field in ("requests", "limits"):
            keys.update(_resources(_object(declaration.get("resources")).get(field)))
    for field in ("requests", "limits"):
        keys.update(_resources(_object(spec.get("resources")).get(field)))
    keys.update(_resources(spec.get("overhead")))
    if len(keys) > MAX_RESOURCES:
        raise AppError("Excessive Pod resource keys.")
    # Complex Pod allocation remains deliberately uncertain. Ordinary status
    # fields describe normal admission too; their mere presence is not resize.
    problem = (
        "init/sidecar Pod budget"
        if spec.get("initContainers")
        else "Pod overhead"
        if spec.get("overhead")
        else "Pod-level budget"
        if spec.get("resources")
        else None
    )
    uncertain = problem is not None
    allocation_problem = (
        _allocation_problem(declarations, statuses, status) if not uncertain else None
    )
    # Configured denominators remain known across status-only differences,
    # including kubelet's Pod-cgroup quantization. Ambiguous declarations cannot
    # establish even a configured sum; complex spec budgets need scheduling math.
    uncertain = uncertain or allocation_problem == "ambiguous declared container identity"
    values = {
        key: _sum(
            tuple(_budget(item.get("resources"), key, uncertain=uncertain) for item in declarations)
        )
        for key in keys
    }
    return MetricReport(
        cpu=values["cpu"],
        memory=values["memory"],
        detail="uncertain Pod allocation · " + problem
        if problem is not None
        else "configured budgets; active allocation unconfirmed · " + allocation_problem
        if allocation_problem is not None
        else "",
        extended=tuple((key, values[key]) for key in sorted(keys - {"cpu", "memory"})),
        allocation_uncertain=uncertain or allocation_problem is not None,
    )


_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)")
_DURATION_SCALES = {
    "ns": Decimal("1e-9"),
    "us": Decimal("1e-6"),
    "µs": Decimal("1e-6"),
    "ms": Decimal(".001"),
    "s": Decimal(1),
    "m": Decimal(60),
    "h": Decimal(3600),
}


def sample_time(manifest: dict[str, Any], now: datetime) -> tuple[datetime, Decimal, MetricStatus]:
    timestamp, window = manifest.get("timestamp"), manifest.get("window")
    if (
        not isinstance(timestamp, str)
        or len(timestamp) > 64
        or not isinstance(window, str)
        or len(window) > 64
    ):
        raise AppError("Metrics require a bounded timestamp and window.")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        raise AppError("Invalid metrics timestamp.") from None
    intervals = tuple(_DURATION.finditer(window))
    if parsed.tzinfo is None or not intervals or "".join(match[0] for match in intervals) != window:
        raise AppError("Invalid metrics timestamp/window.")
    seconds = sum((Decimal(match[1]) * _DURATION_SCALES[match[2]] for match in intervals), ZERO)
    if not ZERO < seconds <= 86400 or (parsed - now).total_seconds() > 5:
        raise AppError("Invalid metrics sampling interval.")
    return (
        parsed,
        seconds,
        MetricStatus.STALE
        if (now - parsed).total_seconds() > MAX_SAMPLE_AGE
        else MetricStatus.VALID,
    )


def pod_sample(pod: ResourceRecord, sample: ResourceRecord | None, now: datetime) -> MetricReport:
    budget = pod_budget(pod)
    if sample is None:
        return budget
    data = sample.manifest
    timestamp, window, state = sample_time(data, now)
    if (sample.uid is not None and sample.uid != pod.uid) or (
        pod.created_at is not None and timestamp < pod.created_at
    ):
        return budget
    spec = _object(pod.manifest.get("spec"))
    declared = {
        entry.get("name"): entry
        for field in ("containers", "initContainers", "ephemeralContainers")
        for entry in _entries(spec.get(field) or [])
    }
    expected = {entry.get("name") for entry in _entries(spec.get("containers") or [])}
    expected.update(
        entry.get("name")
        for entry in _entries(spec.get("initContainers") or [])
        if entry.get("restartPolicy") == "Always"
    )
    status = _object(pod.manifest.get("status"))
    for field in ("initContainerStatuses", "ephemeralContainerStatuses"):
        for entry in _entries(status.get(field) or []):
            if isinstance(_object(entry.get("state")).get("running"), dict):
                expected.add(entry["name"])
    seen: set[str] = set()
    containers = []
    for entry in _entries(data.get("containers")):
        name = entry.get("name")
        if not isinstance(name, str) or name not in declared or name in seen:
            raise AppError("Metrics container does not match this Pod.")
        seen.add(name)
        usage = _resources(entry.get("usage"))
        declaration = declared[name]
        cpu, memory = (
            _budget(declaration.get("resources"), "cpu"),
            _budget(declaration.get("resources"), "memory"),
        )
        valid = state is MetricStatus.VALID
        containers.append(
            (
                name,
                MetricReport(
                    state
                    if usage.get("cpu") is not None and usage.get("memory") is not None
                    else MetricStatus.PARTIAL,
                    replace(cpu, usage=usage.get("cpu") if valid else None),
                    replace(memory, usage=usage.get("memory") if valid else None),
                    timestamp,
                    window,
                    detail=budget.detail,
                    allocation_uncertain=budget.allocation_uncertain,
                ),
            )
        )
    complete = (
        expected <= seen
        and bool(seen)
        and all(report.status is MetricStatus.VALID for _, report in containers)
    )
    return replace(
        budget,
        status=state if complete or state is MetricStatus.STALE else MetricStatus.PARTIAL,
        cpu=replace(
            budget.cpu,
            usage=_sum(tuple(report.cpu for _, report in containers)).usage,
            partial=not complete,
        ),
        memory=replace(
            budget.memory,
            usage=_sum(tuple(report.memory for _, report in containers)).usage,
            partial=not complete,
        ),
        timestamp=timestamp,
        window=window,
        detail=" · ".join(
            filter(
                None,
                (
                    budget.detail,
                    f"{len(seen & expected)}/{len(expected)} containers" if not complete else "",
                ),
            )
        ),
        containers=tuple(containers),
    )


def aggregate(reports: tuple[MetricReport, ...], *, complete: bool = True) -> MetricReport:
    sampled = sum(report.status is MetricStatus.VALID for report in reports)
    full = complete and bool(reports) and sampled == len(reports)
    cpu, memory = (
        _sum(tuple(report.cpu for report in reports)),
        _sum(tuple(report.memory for report in reports)),
    )
    keys = sorted({key for report in reports for key, _ in report.extended})
    if len(keys) > MAX_RESOURCES:
        raise AppError("Excessive aggregated resource keys.")
    return MetricReport(
        MetricStatus.VALID if full else MetricStatus.PARTIAL if reports else MetricStatus.NO_SAMPLE,
        replace(cpu, partial=not full, uncertain=cpu.uncertain or not complete),
        replace(memory, partial=not full, uncertain=memory.uncertain or not complete),
        min((report.timestamp for report in reports if report.timestamp is not None), default=None),
        max((report.window for report in reports if report.window is not None), default=None),
        f"{sampled}/{len(reports)} Pods"
        + (" · membership incomplete" if not complete else "")
        + (" · uncertain Pod allocation" if cpu.uncertain or memory.uncertain else "")
        + (
            " · configured budgets; active allocation unconfirmed"
            if any(report.allocation_uncertain for report in reports)
            else ""
        ),
        tuple(
            (
                key,
                _sum(
                    tuple(
                        replace(
                            dict(report.extended).get(
                                key, ResourceAmount(request=ZERO, limit=ZERO)
                            ),
                            uncertain=report.cpu.uncertain
                            or report.memory.uncertain
                            or dict(report.extended).get(key, ResourceAmount()).uncertain
                            or not complete,
                        )
                        for report in reports
                    )
                ),
            )
            for key in keys
        ),
        allocation_uncertain=not complete or any(report.allocation_uncertain for report in reports),
    )


def node_sample(
    node: ResourceRecord,
    sample: ResourceRecord | None,
    pods: tuple[MetricReport, ...],
    now: datetime,
    *,
    complete: bool = True,
) -> MetricReport:
    status = _object(node.manifest.get("status"))
    capacity, allocatable = (
        _resources(status.get("capacity")),
        _resources(status.get("allocatable")),
    )
    requests = (
        aggregate(pods, complete=complete)
        if pods
        else MetricReport(
            cpu=ResourceAmount(request=ZERO, limit=ZERO),
            memory=ResourceAmount(request=ZERO, limit=ZERO),
        )
    )
    usage: dict[str, Decimal | None] = {}
    timestamp, window, state = None, None, MetricStatus.NO_SAMPLE
    if sample is not None:
        timestamp, window, state = sample_time(sample.manifest, now)
        if (sample.uid is not None and sample.uid != node.uid) or (
            node.created_at is not None and timestamp < node.created_at
        ):
            timestamp, window, state = None, None, MetricStatus.NO_SAMPLE
        elif state is MetricStatus.VALID:
            usage = _resources(sample.manifest.get("usage"))
            if usage.get("cpu") is None or usage.get("memory") is None:
                state = MetricStatus.PARTIAL

    def value(key: str) -> ResourceAmount:
        declared = requests.cpu if key == "cpu" else requests.memory
        return replace(
            declared,
            usage=usage.get(key),
            capacity=capacity.get(key),
            allocatable=allocatable.get(key),
            uncertain=not complete
            or requests.allocation_uncertain
            or requests.cpu.uncertain
            or requests.memory.uncertain,
            partial=state is not MetricStatus.VALID,
        )

    keys = (
        set(capacity) | set(allocatable) | {key for report in pods for key, _ in report.extended}
    ) - {"cpu", "memory"}
    return MetricReport(
        state,
        value("cpu"),
        value("memory"),
        timestamp,
        window,
        "Pod requests incomplete"
        if not complete
        else "Pod allocation uncertain"
        if requests.cpu.uncertain or requests.memory.uncertain or requests.allocation_uncertain
        else "",
        tuple(
            (
                key,
                replace(
                    dict(requests.extended).get(key, ResourceAmount()),
                    capacity=capacity.get(key),
                    allocatable=allocatable.get(key),
                    uncertain=not complete
                    or requests.allocation_uncertain
                    or requests.cpu.uncertain
                    or requests.memory.uncertain
                    or dict(requests.extended).get(key, ResourceAmount()).uncertain,
                ),
            )
            for key in sorted(keys)
        ),
        allocation_uncertain=not complete or requests.allocation_uncertain,
    )
