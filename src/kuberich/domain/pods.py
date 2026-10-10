"""Owned pod health and typed ordering, independent of widgets and SDK objects."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from fractions import Fraction
from typing import cast

from kuberich.domain.resources import ResourceRecord
from kuberich.errors import AppError


class PodColumn(StrEnum):
    NAMESPACE = "namespace"
    NAME = "name"
    READY = "ready"
    STATUS = "status"
    RESTARTS = "restarts"
    AGE = "age"


def _object(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _objects(value: object) -> tuple[dict[str, object], ...]:
    return tuple(_object(entry) for entry in value) if isinstance(value, list) else ()


def _text(value: object, fallback: str = "") -> str:
    return value if isinstance(value, str) and value else fallback


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _condition(conditions: tuple[dict[str, object], ...], kind: str) -> bool:
    return any(entry.get("type") == kind and entry.get("status") == "True" for entry in conditions)


def _termination(state: dict[str, object]) -> str:
    reason = _text(state.get("reason"))
    if reason:
        return reason
    signal = _count(state.get("signal"))
    return f"Signal:{signal}" if signal else f"ExitCode:{_count(state.get('exitCode'))}"


def _ready(status: dict[str, object]) -> bool:
    return status.get("ready") is True and isinstance(
        _object(status.get("state")).get("running"), dict
    )


@dataclass(frozen=True)
class PodRow:
    uid: str
    namespace: str
    name: str
    ready: int
    containers: int
    status: str
    restarts: int
    created_at: datetime | None

    def cells(self, now: datetime) -> tuple[str, ...]:
        return (
            self.namespace,
            self.name,
            f"{self.ready}/{self.containers}",
            self.status,
            str(self.restarts),
            age(self.created_at, now),
        )


def age(created: datetime | None, now: datetime) -> str:
    """Unknown is explicit; clock skew never creates a negative display age."""
    if created is None:
        return "—"
    seconds = max(0, int((now - created).total_seconds()))
    for unit, size in (("y", 31536000), ("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def pod_row(record: ResourceRecord) -> PodRow:
    """Summarize declared application/sidecar containers; ephemeral debug ones are excluded.

    Initialization failures precede application state until Initialized=True.
    Completed regular init restarts are historical: only active sidecars and app
    containers contribute afterwards. Pod-level reasons and terminal phases are
    retained, and deletion cannot turn a terminal pod into a running one.
    """
    if record.uid is None:
        raise AppError("Pod table requires Kubernetes UID identity.")
    manifest = record.manifest
    spec = _object(manifest.get("spec"))
    status = _object(manifest.get("status"))
    metadata = _object(manifest.get("metadata"))
    containers = _objects(spec.get("containers"))
    init = _objects(spec.get("initContainers"))
    app_statuses = {
        _text(entry.get("name")): entry for entry in _objects(status.get("containerStatuses"))
    }
    init_statuses = {
        _text(entry.get("name")): entry for entry in _objects(status.get("initContainerStatuses"))
    }
    sidecars = tuple(entry for entry in init if entry.get("restartPolicy") == "Always")
    conditions = _objects(status.get("conditions"))
    phase = _text(status.get("phase"), "Unknown")
    reason = _text(status.get("reason"), phase)
    ready = sum(_ready(app_statuses.get(_text(entry.get("name")), {})) for entry in containers)
    ready += sum(
        _ready(init_statuses.get(_text(entry.get("name")), {}))
        and init_statuses.get(_text(entry.get("name")), {}).get("started") is True
        for entry in sidecars
    )
    init_reason = ""
    for index, entry in enumerate(init):
        current = init_statuses.get(_text(entry.get("name")), {})
        state = _object(current.get("state"))
        terminated = _object(state.get("terminated"))
        if terminated and terminated.get("exitCode") == 0:
            continue
        if entry.get("restartPolicy") == "Always" and current.get("started") is True:
            continue
        waiting = _text(_object(state.get("waiting")).get("reason"))
        init_reason = (
            "Init:" + _termination(terminated)
            if terminated
            else "Init:" + waiting
            if waiting and waiting != "PodInitializing"
            else f"Init:{index}/{len(init)}"
        )
        break
    initializing = bool(init_reason) and not _condition(conditions, "Initialized")
    active_init = init if initializing else sidecars
    restarts = sum(
        _count(init_statuses.get(_text(entry.get("name")), {}).get("restartCount"))
        for entry in active_init
    )
    if initializing:
        reason = init_reason
    else:
        active = tuple(app_statuses.get(_text(entry.get("name")), {}) for entry in containers)
        restarts += sum(_count(entry.get("restartCount")) for entry in active)
        # A failed sidecar still affects a live pod after Initialized=True.
        # Terminal Jobs retain their application outcome while sidecars stop.
        if phase not in {"Succeeded", "Failed"}:
            active += tuple(init_statuses.get(_text(entry.get("name")), {}) for entry in sidecars)
        waiting_reasons = tuple(
            _text(_object(_object(entry.get("state")).get("waiting")).get("reason"))
            for entry in active
        )
        terminated_states = tuple(
            _object(_object(entry.get("state")).get("terminated")) for entry in active
        )
        failed = tuple(entry for entry in terminated_states if entry and entry.get("exitCode") != 0)
        if not _text(status.get("reason")):
            if any(waiting_reasons):
                reason = next(value for value in waiting_reasons if value)
            elif failed:
                reason = _termination(failed[0])
            elif any(terminated_states) and not any(_ready(entry) for entry in active):
                reason = _termination(next(entry for entry in terminated_states if entry))
            elif any(terminated_states):
                reason = "Running" if _condition(conditions, "Ready") else "NotReady"
    if any(
        entry.get("type") == "PodScheduled" and entry.get("reason") == "SchedulingGated"
        for entry in conditions
    ):
        reason = "SchedulingGated"
    if metadata.get("deletionTimestamp"):
        if status.get("reason") == "NodeLost":
            reason = "Unknown"
        elif phase not in {"Succeeded", "Failed"}:
            reason = "Terminating"
    return PodRow(
        record.uid,
        record.namespace or "—",
        record.name,
        ready,
        len(containers) + len(sidecars),
        reason,
        restarts,
        record.created_at,
    )


def sort_value(row: PodRow, column: PodColumn) -> str | int | float | Fraction | None:
    """Share the actual typed ordering value with incremental table decisions."""
    if column is PodColumn.NAMESPACE:
        return row.namespace.casefold()
    if column is PodColumn.NAME:
        return row.name.casefold()
    if column is PodColumn.READY:
        return Fraction(row.ready, max(1, row.containers))
    if column is PodColumn.STATUS:
        return row.status.casefold()
    if column is PodColumn.RESTARTS:
        return row.restarts
    return -row.created_at.timestamp() if row.created_at is not None else None


def order(
    rows: tuple[PodRow, ...], column: PodColumn, descending: bool = False
) -> tuple[PodRow, ...]:
    """Order typed values with stable name/namespace/UID ties and unknown ages last."""

    def key(row: PodRow) -> str | int | float | Fraction:
        return cast(str | int | float | Fraction, sort_value(row, column))

    stable = sorted(rows, key=lambda row: (row.namespace, row.name, row.uid))
    known = [row for row in stable if column is not PodColumn.AGE or row.created_at is not None]
    unknown = [row for row in stable if column is PodColumn.AGE and row.created_at is None]
    return (*sorted(known, key=key, reverse=descending), *unknown)


def utc_now() -> datetime:
    return datetime.now(UTC)
