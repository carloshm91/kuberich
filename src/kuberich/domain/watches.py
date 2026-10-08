"""Pure watch normalization, bounded UID state and reconnect decisions."""

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum, auto
from math import ldexp
from typing import Any

from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.resources import (
    MAX_RESOURCE_BYTES,
    MAX_RESOURCE_ITEMS,
    ApiResource,
    ResourceRecord,
    ResourceSnapshot,
    resource_object,
    resource_record,
    resource_text,
)
from kuberich.errors import AppError

MAX_RECENT_EVENTS = 1024


class EventType(Enum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    BOOKMARK = "BOOKMARK"


@dataclass(frozen=True, repr=False)
class WatchEvent:
    type: EventType
    resource_version: str
    record: ResourceRecord | None = None


def watch_event(resource: ApiResource, value: Any, namespace: str | None = None) -> WatchEvent:
    data = resource_object(value)
    obj = resource_object(data.get("object"))
    if data.get("type") == "ERROR":
        if obj.get("kind", "Status") != "Status":
            raise AppError("Invalid watch error object.")
        code = obj.get("code")
        if type(code) is not int or not 400 <= code <= 599:
            raise AppError("Invalid watch error status.")
        delay = resource_object(obj.get("details", {})).get("retryAfterSeconds")
        if delay is not None and (type(delay) is not int or delay < 0):
            raise AppError("Invalid watch retry delay.")
        raise HttpProblem(code, retry_after=min(delay, 300) if delay is not None else None)
    try:
        kind = EventType(data.get("type"))
    except ValueError:
        raise AppError("Unsupported watch event type.") from None
    if kind is EventType.BOOKMARK:
        if (
            obj.get("apiVersion", resource.api_version) != resource.api_version
            or obj.get("kind", resource.kind) != resource.kind
        ):
            raise AppError("Bookmark does not match the discovered resource.")
        version = resource_text(resource_object(obj.get("metadata")).get("resourceVersion"))
        return WatchEvent(kind, version)
    record = resource_record(resource, obj, namespace)
    if record.uid is None or record.resource_version is None:
        raise AppError("Watch events require a UID and resourceVersion.")
    return WatchEvent(kind, record.resource_version, record)


class Recovery(Enum):
    RETRY = auto()
    RELIST = auto()
    STOP = auto()


def recovery(problem: ConnectionProblem) -> Recovery:
    if isinstance(problem, HttpProblem):
        if problem.status == 410:
            return Recovery.RELIST
        if problem.status in {408, 429, 500, 502, 503, 504}:
            return Recovery.RETRY
        return Recovery.STOP
    if problem.state in {ConnectionState.TIMEOUT, ConnectionState.UNREACHABLE}:
        return Recovery.RETRY
    return Recovery.STOP


def retry_delay(attempt: int, jitter: float, minimum: float = 0.0) -> float:
    if type(attempt) is not int or attempt < 0 or not 0 <= jitter <= 1 or not 0 <= minimum <= 300:
        raise AppError("Invalid watch retry policy input.")
    base = ldexp(0.25, min(attempt, 7))
    return max(minimum, min(30.0, base * (0.8 + 0.4 * jitter)))


class WatchState:
    """Single-owner state; row ordering remains a separate UI concern."""

    def __init__(self, snapshot: ResourceSnapshot) -> None:
        if "watch" not in snapshot.resource.verbs or snapshot.resource_version in (None, "0"):
            raise AppError("A live collection requires watch support and a collection version.")
        self.resource = snapshot.resource
        self.namespace = snapshot.namespace
        self.resource_version = resource_text(snapshot.resource_version)
        self._records: dict[str, ResourceRecord] = {}
        self._names: dict[tuple[str | None, str], str] = {}
        self._bytes = 0
        self._events: OrderedDict[tuple[EventType, str | None, str], None] = OrderedDict()
        self._versions: OrderedDict[str, None] = OrderedDict()
        for record in snapshot.items:
            if record.uid is None or record.resource_version is None:
                raise AppError("A live collection item requires a UID and resourceVersion.")
            identity = record.namespace, record.name
            if record.uid in self._records or identity in self._names:
                raise AppError("Duplicate live collection identity.")
            self._put(record.uid, record)
        self._versions[self.resource_version] = None

    @property
    def snapshot(self) -> ResourceSnapshot:
        return ResourceSnapshot(
            self.resource, self.namespace, self.resource_version, tuple(self._records.values())
        )

    def _put(self, uid: str, record: ResourceRecord) -> None:
        identity = record.namespace, record.name
        if (
            self.resource.namespaced
            and self.namespace is not None
            and record.namespace != self.namespace
        ) or (not self.resource.namespaced and record.namespace is not None):
            raise AppError("Live resource belongs to another scope.")
        current = self._records.get(uid)
        other_uid = self._names.get(identity, uid)
        other = self._records.get(other_uid) if other_uid != uid else None
        count = len(self._records) + 1 - int(current is not None) - int(other is not None)
        size = self._bytes + record.size_bytes
        if current is not None:
            size -= current.size_bytes
        if other is not None:
            size -= other.size_bytes
        if count > MAX_RESOURCE_ITEMS or size > MAX_RESOURCE_BYTES:
            raise AppError("Live collection exceeds its item/memory limit.")
        if other is not None:
            del self._records[other_uid]
        self._records[uid] = record
        self._names[identity] = uid
        self._bytes = size

    def _remember(self, event: WatchEvent) -> None:
        key = (
            event.type,
            event.record.uid if event.record is not None else None,
            event.resource_version,
        )
        self._events[key] = None
        if len(self._events) > MAX_RECENT_EVENTS:
            self._events.popitem(last=False)
        self._versions[event.resource_version] = None
        if len(self._versions) > MAX_RECENT_EVENTS:
            self._versions.popitem(last=False)

    def apply(self, event: WatchEvent) -> bool:
        record = event.record
        key = event.type, record.uid if record is not None else None, event.resource_version
        if key in self._events:
            return False
        if event.type is EventType.BOOKMARK:
            if event.resource_version in self._versions:
                return False
        else:
            if record is None or record.uid is None:
                raise AppError("A resource event requires a concrete UID identity.")
            current = self._records.get(record.uid)
            if current is not None and (current.namespace, current.name) != (
                record.namespace,
                record.name,
            ):
                raise AppError("A resource event changed its UID identity.")
            if event.type is EventType.DELETED:
                if current is not None:
                    del self._records[record.uid]
                    del self._names[current.namespace, current.name]
                    self._bytes -= current.size_bytes
            else:
                if current is not None and current.resource_version == record.resource_version:
                    self._remember(event)
                    return False
                self._put(record.uid, record)
        self.resource_version = event.resource_version
        self._remember(event)
        return True


class SyncStatus(Enum):
    LOADING = auto()
    SNAPSHOT = auto()
    LIVE = auto()
    RETRYING = auto()
    RELISTING = auto()
    FAILED = auto()


@dataclass(frozen=True, repr=False)
class SyncUpdate:
    status: SyncStatus
    snapshot: ResourceSnapshot | None = None
    event: WatchEvent | None = None
    problem: ConnectionProblem | None = None
    retry_in: float | None = None
