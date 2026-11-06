"""Finite Event observations and identity-safe grouping, without a transport owner."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from typing import Literal

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import namespace_name
from kuberich.domain.relationships import RelationshipRef, fact_name
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    ResourceRecord,
    split_api_version,
)
from kuberich.domain.table_values import Value
from kuberich.domain.views import ResourceScope, ViewStatus
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_EVENT_FACTS = 10000
MAX_EVENT_FACT_BYTES = 16 * 1024 * 1024
MAX_EVENT_REPORTERS = 32
EVENT_FIELDS = ("type", "reason", "object", "occurrences", "last-seen", "reporter")
type EventOrigin = Literal["series", "legacy", "singleton", "unknown"]


@dataclass(frozen=True, slots=True)
class EventFact:
    resource: ApiResource
    uid: str
    name: str
    namespace: str
    resource_version: str | None
    regarding: RelationshipRef | None
    event_type: str | None
    reason: str | None
    reporter: str | None
    count: int | None
    count_origin: EventOrigin
    first_at: datetime | None
    last_at: datetime | None
    last_origin: EventOrigin
    notices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventGroupKey:
    source_api_version: str
    namespace: str
    event_type: str | None
    reason: str | None
    regarding_group: str | None
    regarding_kind: str | None
    regarding_namespace: str | None
    regarding_name: str | None
    regarding_uid: str | None
    missing_uid_member: str | None


@dataclass(frozen=True, slots=True)
class EventGroupMembers:
    key: EventGroupKey

    def matches(self, resource: ApiResource, record: ResourceRecord) -> bool:
        try:
            return group_key(event_fact(resource, record)) == self.key
        except AppError:
            return False


@dataclass(frozen=True, slots=True)
class EventOptions:
    grouped: bool = False
    warnings_only: bool = False
    members: EventGroupMembers | None = None

    def __post_init__(self) -> None:
        if type(self.grouped) is not bool or type(self.warnings_only) is not bool:
            raise AppError("Events options require boolean grouped and warnings choices.")
        if self.members is not None and not isinstance(self.members, EventGroupMembers):
            raise AppError("Events members require an exact group predicate.")


@dataclass(frozen=True, slots=True)
class EventSourceState:
    scope: ResourceScope
    revision: int
    collection: CollectionState
    status: ViewStatus
    snapshot_seen_at: datetime


@dataclass(frozen=True, slots=True)
class EventGroup:
    key: EventGroupKey
    row_key: str
    member_uids: tuple[str, ...]
    known_occurrences: int
    unknown_count_members: int
    last_at: datetime | None
    unknown_time_members: int
    reporters: tuple[str, ...]
    omitted_reporters: int


@dataclass(frozen=True, slots=True)
class EventObjectRow:
    uid: str
    values: tuple[Value, ...]
    fact: EventFact


@dataclass(frozen=True, slots=True)
class EventGroupRow:
    key: str
    values: tuple[Value, ...]
    group: EventGroup


type EventRow = EventObjectRow | EventGroupRow


def _optional(value: object, field: str, notices: list[str]) -> str | None:
    if value is None or value == "":
        return None
    try:
        if not isinstance(value, str):
            raise AppError("Invalid Event text.")
        return validate_argument(value)
    except AppError:
        notices.append(f"{field} is malformed or exceeds the text limit.")
        return None


def _time(value: object, field: str, notices: list[str]) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, OverflowError):
        notices.append(f"{field} is not a bounded timezone-aware timestamp.")
        return None


def _count(value: object, notices: list[str]) -> int | None:
    if type(value) is int and 0 <= value <= 2147483647:
        return value
    notices.append("Occurrence count is malformed, missing or outside the API integer range.")
    return None


def _reference(value: object, notices: list[str]) -> RelationshipRef | None:
    try:
        if not isinstance(value, dict):
            raise AppError("Missing Event object reference.")
        group, version = split_api_version(value.get("apiVersion"))
        api_version = f"{group}/{version}" if group else version
        kind = value.get("kind")
        if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind):
            raise AppError("Invalid Event reference kind.")
        name = fact_name(value.get("name"))
        namespace = value.get("namespace")
        if namespace == "":
            namespace = None
        if namespace is not None:
            namespace = namespace_name(validate_argument(namespace))
        uid = value.get("uid")
        if uid == "":
            uid = None
        if uid is not None:
            uid = validate_argument(uid)
        return RelationshipRef(api_version, kind, namespace, name, uid, None)
    except AppError:
        notices.append("Regarding object identity is unavailable; no object link is implied.")
        return None


def event_descriptor_supported(resource: ApiResource) -> bool:
    return (
        resource.group,
        resource.version,
        resource.name,
        resource.kind,
        resource.namespaced,
    ) in {
        ("", "v1", "events", "Event", True),
        ("events.k8s.io", "v1", "events", "Event", True),
    } and resource.namespaced is True


def event_fact(resource: ApiResource, record: ResourceRecord) -> EventFact:
    if (
        not event_descriptor_supported(resource)
        or record.uid is None
        or record.namespace is None
        or record.size_bytes > 64 * 1024 * 1024
    ):
        raise AppError("Event facts require a complete supported Event descriptor and UID.")
    manifest = record.manifest
    observed_type = manifest.get("apiVersion", resource.api_version), manifest.get("kind", "Event")
    if observed_type != (resource.api_version, "Event") and not (
        record.metadata_only and observed_type == ("meta.k8s.io/v1", "PartialObjectMetadata")
    ):
        raise AppError("Event contents contradict the served descriptor.")
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict) or (
        metadata.get("name"),
        metadata.get("uid"),
        metadata.get("namespace"),
        metadata.get("resourceVersion"),
    ) != (record.name, record.uid, record.namespace, record.resource_version):
        raise AppError("Event metadata contradicts its captured identity.")
    fact_name(record.name)
    validate_argument(record.uid)
    namespace_name(record.namespace)
    if record.metadata_only:
        return EventFact(
            resource,
            record.uid,
            record.name,
            record.namespace,
            record.resource_version,
            None,
            None,
            None,
            None,
            None,
            "unknown",
            None,
            None,
            "unknown",
            (
                "Metadata-only Event: body facts, counts and occurrence times are unknown; warning-only filtering omits this unclassified type.",
            ),
        )
    notices: list[str] = []
    modern = bool(resource.group)
    legacy_count = "deprecatedCount" if modern else "count"
    legacy_first = "deprecatedFirstTimestamp" if modern else "firstTimestamp"
    legacy_last = "deprecatedLastTimestamp" if modern else "lastTimestamp"
    series_present = manifest.get("series") is not None
    raw_series = manifest.get("series")
    series = raw_series if isinstance(raw_series, dict) else {}
    if series_present:
        count = _count(series.get("count"), notices)
        count_origin: EventOrigin = "series" if count is not None else "unknown"
    elif legacy_count in manifest:
        count = _count(manifest[legacy_count], notices)
        count_origin = "legacy" if count is not None else "unknown"
    elif modern:
        count, count_origin = 1, "singleton"
    else:
        count, count_origin = None, "unknown"
    event_at = _time(manifest.get("eventTime"), "eventTime", notices)
    first_at = event_at or _time(manifest.get(legacy_first), legacy_first, notices)
    last_at = (
        _time(series.get("lastObservedTime"), "series.lastObservedTime", notices)
        if series_present
        else None
    )
    last_origin: EventOrigin = "series" if last_at is not None else "unknown"
    if last_at is None:
        last_at = _time(manifest.get(legacy_last), legacy_last, notices)
        if last_at is not None:
            last_origin = "legacy"
            if series_present:
                notices.append(
                    "Series last timestamp unavailable; using reported legacy timestamp."
                )
    if last_at is None and not series_present and count == 1:
        last_at = event_at
        if last_at is not None:
            last_origin = "singleton"
    if last_at is None:
        notices.append("Latest occurrence time is unknown; creation time is not a substitute.")
    if count is None:
        notices.append("Occurrence count is unknown; missing is not zero.")
    controller_field = "reportingController" if modern else "reportingComponent"
    controller = _optional(manifest.get(controller_field), controller_field, notices)
    instance = _optional(manifest.get("reportingInstance"), "reportingInstance", notices)
    if controller is None:
        source = manifest.get("deprecatedSource" if modern else "source")
        if isinstance(source, dict):
            controller = _optional(source.get("component"), "source.component", notices)
            instance = _optional(source.get("host"), "source.host", notices)
    reporter = (
        json.dumps((controller, instance), ensure_ascii=False, separators=(",", ":"))
        if controller is not None or instance is not None
        else None
    )
    return EventFact(
        resource,
        record.uid,
        record.name,
        record.namespace,
        record.resource_version,
        _reference(manifest.get("regarding" if modern else "involvedObject"), notices),
        _optional(manifest.get("type"), "type", notices),
        _optional(manifest.get("reason"), "reason", notices),
        reporter,
        count,
        count_origin,
        first_at,
        last_at,
        last_origin,
        tuple(notices),
    )


def group_key(fact: EventFact) -> EventGroupKey:
    ref = fact.regarding
    return EventGroupKey(
        fact.resource.api_version,
        fact.namespace,
        fact.event_type,
        fact.reason,
        split_api_version(ref.api_version)[0] if ref else None,
        ref.kind if ref else None,
        ref.namespace if ref else None,
        ref.name if ref else None,
        ref.uid if ref else None,
        fact.uid if ref is None or ref.uid is None else None,
    )


def _selected(facts: tuple[EventFact, ...], options: EventOptions) -> tuple[EventFact, ...]:
    if len(facts) > MAX_EVENT_FACTS:
        raise AppError("Event fact count exceeds the retained membership limit.")
    latest = {}
    size = 0
    for fact in facts:
        size += len(repr(fact).encode("utf-8"))
        if size > MAX_EVENT_FACT_BYTES:
            raise AppError("Event facts exceed the retained byte limit.")
        latest[(fact.resource.api_version, fact.uid)] = fact
    return tuple(
        fact
        for fact in latest.values()
        if (not options.warnings_only or fact.event_type == "Warning")
        and (options.members is None or group_key(fact) == options.members.key)
    )


def group_events(facts: tuple[EventFact, ...], options: EventOptions) -> tuple[EventGroup, ...]:
    grouped: dict[EventGroupKey, list[EventFact]] = {}
    for fact in _selected(facts, options):
        grouped.setdefault(group_key(fact), []).append(fact)
    result = []
    for key, members in grouped.items():
        reporters = tuple(
            sorted({member.reporter for member in members if member.reporter is not None})
        )
        times = [member.last_at for member in members if member.last_at is not None]
        digest = hashlib.sha256(
            json.dumps(astuple(key), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result.append(
            EventGroup(
                key,
                "event-group:" + digest,
                tuple(sorted(member.uid for member in members)),
                sum(member.count for member in members if member.count is not None),
                sum(member.count is None for member in members),
                max(times) if times else None,
                sum(member.last_at is None for member in members),
                reporters[:MAX_EVENT_REPORTERS],
                max(0, len(reporters) - MAX_EVENT_REPORTERS),
            )
        )
    return tuple(sorted(result, key=lambda group: group.row_key))


def _display(value: str | None) -> Value:
    return (
        Value(sanitize_text(value)[:256], value)
        if value is not None and value != ""
        else Value("unknown", None)
    )


def _last(value: datetime | None, origin: str, seen_at: datetime | None) -> Value:
    if value is None:
        return Value("unknown", None)
    if seen_at is not None and seen_at.tzinfo is None:
        raise AppError("Event source observation time must have a timezone.")
    return Value(
        value.isoformat(timespec="seconds")
        + " · "
        + origin
        + (" · future reported time" if seen_at is not None and value > seen_at else ""),
        value.timestamp(),
    )


def event_rows(
    facts: tuple[EventFact, ...], options: EventOptions, *, observed_at: datetime | None = None
) -> tuple[EventRow, ...]:
    if options.grouped:
        return tuple(
            EventGroupRow(
                group.row_key,
                (
                    _display(group.key.event_type),
                    _display(group.key.reason),
                    _display(
                        (group.key.regarding_kind or "unknown")
                        + "/"
                        + (group.key.regarding_name or "unknown")
                    ),
                    Value(
                        str(group.known_occurrences)
                        + (
                            f" known · {group.unknown_count_members} unknown members"
                            if group.unknown_count_members
                            else ""
                        ),
                        None if group.unknown_count_members else group.known_occurrences,
                    ),
                    _last(
                        group.last_at,
                        f"latest reported · {group.unknown_time_members} unknown members",
                        observed_at,
                    ),
                    _display(
                        (f"{group.omitted_reporters} omitted · " if group.omitted_reporters else "")
                        + "; ".join(group.reporters)
                    ),
                ),
                group,
            )
            for group in group_events(facts, options)
        )
    return tuple(
        EventObjectRow(
            fact.uid,
            (
                _display(fact.event_type),
                _display(fact.reason),
                _display(
                    fact.regarding.kind + "/" + fact.regarding.name if fact.regarding else None
                ),
                Value(str(fact.count) + " · " + fact.count_origin, fact.count)
                if fact.count is not None
                else Value("unknown", None),
                _last(fact.last_at, fact.last_origin, observed_at),
                _display(fact.reporter),
            ),
            fact,
        )
        for fact in _selected(facts, options)
    )
