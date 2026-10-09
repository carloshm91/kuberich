"""Bounded source membership, sanitized structured lines and aggregate retention."""

import json
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from functools import cached_property

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.log_json import TIMESTAMP, structured_payload
from kuberich.domain.log_view import MAX_COPY_BYTES, LogEntry
from kuberich.domain.logs import MAX_BYTES, MAX_LINES, LogBuffer, LogLine, log_containers
from kuberich.domain.resources import ApiResource, ResourceRecord, split_api_version
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError

MAX_READERS = 8
MAX_SOURCES = 256
MAX_RETIRED = 64
SOURCE_LINES = 500
SOURCE_BYTES = 256 * 1024
MAX_PAYLOAD = 4096
_WORKLOADS = {
    ("", "pods"): "Pod",
    ("", "replicationcontrollers"): "ReplicationController",
    ("apps", "deployments"): "Deployment",
    ("apps", "replicasets"): "ReplicaSet",
    ("apps", "statefulsets"): "StatefulSet",
    ("apps", "daemonsets"): "DaemonSet",
    ("batch", "jobs"): "Job",
    ("batch", "cronjobs"): "CronJob",
}


def workload_kind(target: ResourceTarget) -> str:
    kind = _WORKLOADS.get((target.group, target.resource))
    if kind is None or target.namespace is None:
        raise AppError("Aggregated logs require a namespaced Pod or supported workload.")
    return kind


def intermediate_resource(target: ResourceTarget) -> ApiResource | None:
    kind = workload_kind(target)
    if kind == "Deployment":
        return ApiResource(
            "apps", "v1", "replicasets", "ReplicaSet", True, frozenset({"get", "list", "watch"})
        )
    if kind == "CronJob":
        return ApiResource("batch", "v1", "jobs", "Job", True, frozenset({"get", "list", "watch"}))
    return None


def owned_by(record: ResourceRecord, target: ResourceTarget, kind: str) -> bool:
    if record.namespace != target.namespace:
        return False
    owners = record.manifest.get("metadata", {}).get("ownerReferences", [])
    if not isinstance(owners, list) or len(owners) > 128:
        raise AppError("Invalid or excessive workload owner references.")
    for owner in owners:
        if not isinstance(owner, dict) or owner.get("controller") is not True:
            continue
        version = owner.get("apiVersion")
        if not isinstance(version, str):
            continue
        try:
            group, _ = split_api_version(version)
        except AppError:
            continue
        if (
            group == target.group
            and owner.get("kind") == kind
            and owner.get("uid") == target.uid
            and owner.get("name") == target.name
        ):
            return True
    return False


def _intermediate_owner(pod: ResourceRecord, owners: dict[str, ResourceTarget], kind: str) -> bool:
    references = pod.manifest.get("metadata", {}).get("ownerReferences", [])
    if not isinstance(references, list) or len(references) > 128:
        raise AppError("Invalid or excessive workload owner references.")
    # Index exact UIDs: work is bounded by references per Pod, not Pod/owner pairs.
    return any(
        isinstance(reference, dict)
        and isinstance(reference.get("uid"), str)
        and reference["uid"] in owners
        and owned_by(pod, owners[reference["uid"]], kind)
        for reference in references
    )


@dataclass(frozen=True)
class LogSource:
    namespace: str
    pod: str
    uid: str
    container: str
    start_token: str | None = field(default=None, compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.uid, self.container

    def label(self, number: int) -> str:
        return sanitize_text(
            f"s{number} {self.namespace}/{self.pod}:{self.container} uid={self.uid}"
        )


def _log_state(entry: dict[str, object], previous: bool) -> tuple[str, dict[str, object]] | None:
    state = entry.get("state")
    state = state if isinstance(state, dict) else {}
    if not previous:
        running = state.get("running")
        if isinstance(running, dict):
            return "running", {**running, "containerID": entry.get("containerID")}
        terminated = state.get("terminated")
        if (
            isinstance(terminated, dict)
            and isinstance(terminated.get("containerID"), str)
            and terminated["containerID"]
        ):
            return "terminated", terminated
    last = entry.get("lastState")
    last = last.get("terminated") if isinstance(last, dict) else None
    if isinstance(last, dict) and isinstance(last.get("containerID"), str) and last["containerID"]:
        return "last-terminated", last
    return None


def container_starts(manifest: dict[str, object], *, previous: bool = False) -> dict[str, str]:
    """A declaration/Pod phase alone cannot establish that this container has logs."""
    status = manifest.get("status")
    if not isinstance(status, dict):
        return {}
    result = {}
    for field_name in ("containerStatuses", "initContainerStatuses", "ephemeralContainerStatuses"):
        entries = status.get(field_name, [])
        if not isinstance(entries, list) or len(entries) > 128:
            raise AppError("Invalid or excessive log container statuses.")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                continue
            selected = _log_state(entry, previous)
            if selected is None:
                continue
            phase, observed = selected
            values = (
                observed.get("containerID"),
                observed.get("startedAt"),
                observed.get("finishedAt"),
            )
            identity = tuple(value[:512] if isinstance(value, str) else None for value in values)
            restarts = entry.get("restartCount")
            result[entry["name"]] = sanitize_text(
                str(
                    (phase, identity, restarts if type(restarts) is int and restarts >= 0 else None)
                )
            )
    return result


def sources(
    target: ResourceTarget,
    pods: tuple[ResourceRecord, ...],
    intermediates: tuple[ResourceRecord, ...] = (),
    *,
    previous: bool = False,
) -> tuple[tuple[LogSource, ...], int]:
    """Labels never establish membership; only an exact controller chain does."""
    kind = workload_kind(target)
    intermediate = intermediate_resource(target)
    owners = {
        record.uid: ResourceTarget(
            target.session,
            intermediate.group,
            intermediate.name,
            record.namespace,
            record.name,
            record.uid,
        )
        for record in intermediates
        if intermediate is not None and record.uid and owned_by(record, target, kind)
    }
    selected: list[LogSource] = []
    excess = 0
    for pod in sorted(
        pods, key=lambda record: (record.namespace or "", record.name, record.uid or "")
    ):
        if pod.namespace != target.namespace or not pod.uid:
            continue
        member = (
            pod.uid == target.uid and pod.name == target.name
            if kind == "Pod"
            else _intermediate_owner(pod, owners, intermediate.kind)
            if intermediate is not None
            else owned_by(pod, target, kind)
        )
        if not member:
            continue
        starts = container_starts(pod.manifest, previous=previous)
        for container in log_containers(pod.manifest):
            if len(selected) < MAX_SOURCES:
                selected.append(
                    LogSource(
                        target.namespace or "", pod.name, pod.uid, container, starts.get(container)
                    )
                )
            else:
                excess += 1
    return tuple(selected), excess


@dataclass(frozen=True)
class AggregateLine:
    number: int
    source: LogSource
    source_number: int
    timestamp: str | None
    payload: str
    structured: str | None

    def text(self, *, json_mode: bool, timestamps: bool = True) -> str:
        if json_mode:
            value = {
                "source": {
                    "id": self.source_number,
                    "namespace": sanitize_text(self.source.namespace),
                    "pod": sanitize_text(self.source.pod),
                    "container": sanitize_text(self.source.container),
                    "uid": sanitize_text(self.source.uid),
                },
                "line": self.number,
                "timestamp": self.timestamp if timestamps else None,
                "payload": json.loads(self.structured)
                if self.structured is not None
                else self.payload,
            }
            return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        timestamp = f"{self.timestamp} " if timestamps and self.timestamp is not None else ""
        return f"[{self.source.label(self.source_number)}] {timestamp}{self.payload}"

    @cached_property
    def size_bytes(self) -> int:
        # Reserve the larger representation so changing modes cannot evade retention.
        return max(
            len(self.text(json_mode=False).encode()), len(self.text(json_mode=True).encode())
        )


def aggregate_line(
    number: int, source: LogSource, source_number: int, line: LogLine
) -> AggregateLine:
    match = TIMESTAMP.match(line.text)
    timestamp = match.group(1) if match else None
    payload = line.text[match.end() :] if match else line.text
    safe, structured = structured_payload(payload)
    if max(len(safe), len(structured or "")) > MAX_PAYLOAD:
        # Budget after control escaping/JSON expansion, before adding source identity.
        safe = safe[:MAX_PAYLOAD] + " [aggregate payload truncated]"
        structured = None
    return AggregateLine(number, source, source_number, timestamp, safe, structured)


class AggregateHistory:
    def __init__(
        self,
        *,
        max_lines: int = MAX_LINES,
        max_bytes: int = MAX_BYTES,
        source_lines: int = SOURCE_LINES,
        source_bytes: int = SOURCE_BYTES,
    ) -> None:
        if not 0 < source_lines <= SOURCE_LINES or not 0 < source_bytes <= SOURCE_BYTES:
            raise AppError("Invalid per-source log retention bounds.")
        self.buffer = LogBuffer(max_lines=max_lines, max_bytes=max_bytes)
        self.source_lines, self.source_bytes = source_lines, source_bytes
        self.records: OrderedDict[int, AggregateLine] = OrderedDict()
        self.by_source: dict[tuple[str, str], deque[int]] = {}
        self.sizes: dict[tuple[str, str], int] = {}
        self.marks: set[int] = set()
        self.next_number = 1
        self.json_mode = False
        self.filter: tuple[str, str] | None = None

    @property
    def entries(self) -> tuple[LogEntry, ...]:
        return tuple(
            LogEntry(record.number, LogLine(record.text(json_mode=self.json_mode)))
            for record in self.records.values()
            if self.filter is None or record.source.key == self.filter
        )

    def _remove(self, number: int) -> None:
        record = self.records.pop(number)
        key = record.source.key
        self.by_source[key].remove(number)
        self.sizes[key] -= record.size_bytes
        self.buffer.size_bytes -= record.size_bytes
        self.buffer.dropped_lines += 1
        self.marks.discard(number)
        if not self.by_source[key]:
            del self.by_source[key], self.sizes[key]

    def retain(self, source: LogSource, source_number: int, line: LogLine) -> None:
        record = aggregate_line(self.next_number, source, source_number, line)
        self.next_number += 1
        key = source.key
        self.records[record.number] = record
        self.by_source.setdefault(key, deque()).append(record.number)
        self.sizes[key] = self.sizes.get(key, 0) + record.size_bytes
        self.buffer.size_bytes += record.size_bytes
        while key in self.by_source and (
            len(self.by_source[key]) > self.source_lines or self.sizes[key] > self.source_bytes
        ):
            self._remove(self.by_source[key][0])
        while (
            len(self.records) > self.buffer.max_lines
            or self.buffer.size_bytes > self.buffer.max_bytes
        ):
            self._remove(next(iter(self.records)))

    def append(self, line: LogLine) -> None:
        raise AppError("Aggregated log lines require a captured source identity.")

    def clear(self) -> int:
        count = len(self.records)
        self.records.clear()
        self.by_source.clear()
        self.sizes.clear()
        self.marks.clear()
        self.buffer.size_bytes = self.buffer.dropped_lines = 0
        return count

    def mark(self, number: int) -> None:
        if number not in self.records:
            raise AppError("That log line is no longer retained.")
        if number in self.marks:
            self.marks.remove(number)
        else:
            self.marks.add(number)

    def export(self, *, clipboard: bool = False) -> str:
        text = "\n".join(
            record.text(json_mode=self.json_mode)
            for record in self.records.values()
            if self.filter is None or record.source.key == self.filter
        )
        if clipboard and len(text.encode()) > MAX_COPY_BYTES:
            raise AppError("Copy exceeds 1 MiB; filter sources or save to a file.")
        return text

    def display_entries(self, timestamps: bool) -> tuple[LogEntry, ...]:
        return tuple(
            LogEntry(
                record.number, LogLine(record.text(json_mode=self.json_mode, timestamps=timestamps))
            )
            for record in self.records.values()
            if self.filter is None or record.source.key == self.filter
        )
