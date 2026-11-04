"""Read-only container details from a captured pod, without invented metrics."""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from kuberich.domain.logs import log_containers
from kuberich.domain.metrics import METRIC_LABELS, MetricReport, MetricStatus

CONTAINER_METRIC_KEYS = (
    "cpu",
    "memory",
    "cpu-percent-request",
    "cpu-percent-limit",
    "memory-percent-request",
    "memory-percent-limit",
    "metrics",
    "sample",
    "window",
)
CONTAINER_COLUMNS = (
    "NAME",
    "TYPE",
    "READY",
    "STATE",
    "RESTARTS",
    "IMAGE",
    "PROBES(R:L:S)",
    "CPU REQ/LIM",
    "MEM REQ/LIM",
    "PORTS",
    *(METRIC_LABELS.get(key, key.upper()) for key in CONTAINER_METRIC_KEYS),
)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object, fallback: str = "—") -> str:
    return value[:512] if isinstance(value, str) and value else fallback


def _state(status: dict[str, Any]) -> str:
    state = _object(status.get("state"))
    if isinstance(state.get("waiting"), dict):
        return _text(state["waiting"].get("reason"), "Waiting")
    if isinstance(state.get("running"), dict):
        return "Running"
    if isinstance(state.get("terminated"), dict):
        ended = state["terminated"]
        if isinstance(ended.get("reason"), str) and ended["reason"]:
            return _text(ended["reason"])
        code = ended.get("exitCode")
        if type(code) is int:
            return "Completed" if code == 0 else f"ExitCode:{code}"
        return "Terminated"
    return "Unknown"


def _limits(spec: dict[str, Any], resource: str) -> str:
    values = _object(spec.get("resources"))
    return "/".join(
        _text(_object(values.get(kind)).get(resource), "unlimited" if kind == "limits" else "N/A")
        for kind in ("requests", "limits")
    )


def _ports(spec: dict[str, Any]) -> str:
    values = spec.get("ports")
    if not isinstance(values, list):
        return "—"
    ports = []
    for entry in values[:16]:
        port = _object(entry)
        number = port.get("containerPort")
        if type(number) is not int or not 1 <= number <= 65535:
            continue
        name = _text(port.get("name"), "")
        protocol = _text(port.get("protocol"), "TCP")
        ports.append(f"{name + ':' if name else ''}{number}/{protocol}")
    if len(values) > 16:
        ports.append("…")
    return ", ".join(ports) or "—"


@dataclass(frozen=True)
class ContainerRow:
    name: str
    kind: str
    ready: str
    state: str
    restarts: str
    image: str
    probes: str
    cpu: str
    memory: str
    ports: str
    metrics: MetricReport = dataclass_field(default_factory=MetricReport)

    def cells(self) -> tuple[str, ...]:
        return (
            self.name,
            self.kind,
            self.ready,
            self.state,
            self.restarts,
            self.image,
            self.probes,
            self.cpu,
            self.memory,
            self.ports,
            *(self.metrics.value(key)[0] for key in CONTAINER_METRIC_KEYS),
        )


def container_rows(
    manifest: dict[str, Any], metrics: MetricReport | None = None
) -> tuple[ContainerRow, ...]:
    names = log_containers(manifest)
    metrics = metrics or MetricReport()
    observed_metrics = dict(metrics.containers)
    spec, status = _object(manifest.get("spec")), _object(manifest.get("status"))
    declarations: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for field, status_field in (
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ):
        raw = status.get(status_field)
        statuses = {
            item.get("name"): item
            for item in (raw if isinstance(raw, list) else [])
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        for item in spec.get(field) or []:
            kind = (
                "App"
                if field == "containers"
                else "Ephemeral"
                if field == "ephemeralContainers"
                else ("Sidecar" if item.get("restartPolicy") == "Always" else "Init")
            )
            declarations[item["name"]] = kind, item, statuses.get(item["name"], {})
    rows = []
    for name in names:
        kind, declaration, observed = declarations[name]
        ready, restarts = observed.get("ready"), observed.get("restartCount")
        rows.append(
            ContainerRow(
                name,
                kind,
                "true" if ready is True else "false" if ready is False else "—",
                _state(observed),
                str(restarts) if type(restarts) is int and restarts >= 0 else "—",
                _text(declaration.get("image")),
                ":".join(
                    "on" if isinstance(declaration.get(probe), dict) else "off"
                    for probe in ("readinessProbe", "livenessProbe", "startupProbe")
                ),
                _limits(declaration, "cpu"),
                _limits(declaration, "memory"),
                _ports(declaration),
                observed_metrics.get(
                    name,
                    MetricReport(
                        metrics.status
                        if metrics.status not in {MetricStatus.VALID, MetricStatus.PARTIAL}
                        else MetricStatus.NO_SAMPLE,
                        detail=metrics.detail,
                    ),
                ),
            )
        )
    return tuple(rows)
