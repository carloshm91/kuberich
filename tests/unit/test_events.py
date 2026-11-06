"""Versioned Event observations, exact identity grouping and bounded immutable rows."""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.events import (
    EVENT_FIELDS,
    MAX_EVENT_FACT_BYTES,
    MAX_EVENT_FACTS,
    EventGroupMembers,
    EventGroupRow,
    EventObjectRow,
    EventOptions,
    EventSourceState,
    event_descriptor_supported,
    event_fact,
    event_rows,
    group_events,
    group_key,
)
from kuberich.domain.resources import (
    CollectionState,
    ResourceRecord,
    metadata_record,
    resource_record,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewStatus
from kuberich.errors import AppError
from tests.support.events import (
    EVENT_CANARY,
    FIRST,
    LAST,
    event_manifest,
    event_record,
    event_resource,
)

AT = datetime(2026, 11, 6, 12, 2, tzinfo=UTC)


def fact(**options):
    return event_fact(event_resource(modern=options.get("modern", True)), event_record(**options))


@pytest.mark.parametrize("modern", [False, True])
def test_schema_specific_origins_safe_facts_and_frozen_state(modern):
    result = fact(modern=modern)
    assert result.resource.api_version == ("events.k8s.io/v1" if modern else "v1")
    assert result.count == (1 if modern else 3)
    assert result.count_origin == result.last_origin == ("singleton" if modern else "legacy")
    assert result.first_at.isoformat() == "2026-11-06T12:00:00+00:00"
    assert result.regarding.uid == "pod-uid" and result.regarding.resource is None
    assert EVENT_CANARY not in repr(result) and json.loads(result.reporter)[1] == "worker-a"
    with pytest.raises(FrozenInstanceError):
        result.count = 4


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("count", [0, 1, 19, 2147483647])
def test_valid_series_overrides_legacy_count_including_zero(modern, count):
    result = fact(
        modern=modern,
        series={"count": count, "lastObservedTime": LAST},
        **{"deprecatedCount" if modern else "count": 999},
    )
    assert result.count == count and result.count_origin == result.last_origin == "series"
    assert result.last_at.isoformat() == "2026-11-06T12:01:00+00:00"


@pytest.mark.parametrize("count", [None, True, False, -1, 2147483648, "4", {}, []])
def test_malformed_series_count_is_unknown_without_legacy_fallback(count):
    result = fact(series={"count": count}, deprecatedCount=99)
    assert result.count is None and result.count_origin == "unknown"
    assert result.last_at is None and result.last_origin == "unknown" and result.notices


@pytest.mark.parametrize("series", [{}, False, 4, [], {"count": 2}])
def test_any_series_refuses_first_eventtime_as_latest_but_qualifies_legacy_time(series):
    result = fact(series=series)
    assert result.first_at is not None and result.last_at is None
    fallback = fact(series=series, deprecatedLastTimestamp=LAST)
    assert fallback.last_origin == "legacy" and fallback.last_at is not None
    assert any("legacy timestamp" in item for item in fallback.notices)


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("count", [0, 1, 5, None, True, -1])
def test_legacy_counts_and_singleton_last_time_are_distinct(modern, count):
    changes = {"deprecatedCount" if modern else "count": count, "eventTime": FIRST}
    if not modern:
        changes["lastTimestamp"] = None
    result = fact(modern=modern, **changes)
    assert result.count == (count if type(count) is int and count >= 0 else None)
    assert (result.last_at is not None) == (type(count) is int and count == 1)


@pytest.mark.parametrize(
    "timestamp",
    [None, "", True, 5, "invalid", "2026-01-01", "x" * 129, "0001-01-01T00:00:00+23:59"],
)
def test_missing_bad_or_overflowing_timestamps_do_not_become_creation_time(timestamp):
    result = fact(eventTime=timestamp)
    assert result.first_at is result.last_at is None


def test_core_missing_counts_timezone_normalization_and_future_evidence():
    resource = event_resource(modern=False)
    raw = event_manifest(modern=False)
    for key in ("count", "firstTimestamp", "lastTimestamp"):
        del raw[key]
    unknown = event_fact(resource, resource_record(resource, raw))
    assert unknown.count is unknown.first_at is unknown.last_at is None
    result = fact(
        eventTime="bad",
        deprecatedFirstTimestamp="2026-11-06T14:00:00+02:00",
        deprecatedLastTimestamp="2030-01-01T00:00:00Z",
    )
    assert result.first_at.isoformat() == "2026-11-06T12:00:00+00:00"
    row = event_rows((result,), EventOptions(), observed_at=AT)[0]
    assert "future reported time" in row.values[4].text
    assert row.values[4].sort == result.last_at.timestamp()
    with pytest.raises(AppError):
        event_rows((result,), EventOptions(), observed_at=datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "reference",
    [
        None,
        {},
        {"apiVersion": "bad/api/version", "kind": "Pod", "name": "pod"},
        {"apiVersion": "v1", "kind": "bad/kind", "name": "pod"},
        {"apiVersion": "v1", "kind": False, "name": "pod"},
        {"apiVersion": "v1", "kind": "Pod", "name": "bad/name"},
        {"apiVersion": "v1", "kind": "Pod", "name": "pod", "namespace": True},
        {"apiVersion": "v1", "kind": "Pod", "name": "pod", "uid": False},
    ],
)
def test_malformed_object_reference_retains_event_but_no_actionable_identity(reference):
    result = fact(regarding=reference)
    assert result.regarding is None and group_key(result).missing_uid_member == result.uid
    assert any("object identity" in item for item in result.notices)


def test_missing_reference_scope_and_uid_are_not_guessed():
    result = fact(
        regarding={
            "apiVersion": "v1",
            "kind": "Node",
            "name": "owned-node",
            "namespace": "",
            "uid": "",
        }
    )
    assert result.regarding.namespace is result.regarding.uid is None
    assert group_key(result).regarding_group == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", 5),
        ("reason", False),
        ("reason", "x" * 8193),
        ("reason", "bad\x1bvalue"),
        ("reportingController", {}),
        ("reportingInstance", []),
    ],
)
def test_optional_fields_fail_to_fixed_notices_without_payload_errors(field, value):
    assert any("malformed" in item for item in fact(**{field: value}).notices)


def test_reporter_pairs_are_unambiguous_and_missing_is_explicit():
    first = fact(
        reportingController="a / b",
        reportingInstance="c",
        deprecatedSource={"component": "ignored", "host": "ignored"},
    )
    second = fact(uid="other", reportingController="a", reportingInstance="b / c")
    assert first.reporter != second.reporter
    fallback = fact(
        reportingController=None, deprecatedSource={"component": "legacy", "host": "worker"}
    )
    assert json.loads(fallback.reporter) == ["legacy", "worker"]
    missing = fact(reportingController=None, reportingInstance=None)
    assert missing.reporter is None
    assert group_events((missing,), EventOptions())[0].reporters == ()
    assert event_rows((missing,), EventOptions(grouped=True))[0].values[-1].sort is None


def test_modification_replaces_current_member_count_and_deletion_removes_member():
    first = fact(uid="a", series={"count": 2, "lastObservedTime": LAST})
    second = fact(uid="b", series={"count": 4, "lastObservedTime": LAST}, reportingInstance="other")
    updated = replace(first, count=5)
    result = group_events((first, second, updated), EventOptions())[0]
    assert result.known_occurrences == 9 and result.member_uids == ("a", "b")
    assert len(result.reporters) == 2 and result.unknown_count_members == 0
    remaining = group_events((updated,), EventOptions())[0]
    assert remaining.known_occurrences == 5 and remaining.member_uids == ("a",)
    assert result.row_key == remaining.row_key and result.row_key.startswith("event-group:")


def test_group_full_identity_source_and_clipping_never_merge_distinct_objects():
    base = fact()
    refs = [
        replace(base.regarding, uid="replacement"),
        replace(base.regarding, namespace="other"),
        replace(base.regarding, kind="Service"),
        replace(base.regarding, name="other"),
    ]
    inputs = [
        base,
        *(replace(base, uid=str(index), regarding=ref) for index, ref in enumerate(refs)),
        replace(fact(modern=False), uid="legacy"),
        replace(base, uid="normal", event_type="Normal"),
        replace(base, uid="reason", reason="Other"),
        replace(base, uid="namespace", namespace="other"),
    ]
    assert len(group_events(tuple(inputs), EventOptions())) == len(inputs)
    rows = event_rows(
        (fact(reason="x" * 256 + "a"), fact(uid="two", reason="x" * 256 + "b")),
        EventOptions(grouped=True),
    )
    assert len(rows) == 2 and rows[0].values[1].text == rows[1].values[1].text
    assert rows[0].key != rows[1].key


def test_warning_filter_and_exact_members_predicate_keep_missing_uid_events_separate():
    first, second = fact(object_uid=None), fact(uid="second", object_uid=None)
    assert len(group_events((first, second), EventOptions())) == 2
    warning = fact(uid="warning")
    groups = group_events(
        (fact(uid="normal", type="Normal"), warning), EventOptions(warnings_only=True)
    )
    assert groups[0].member_uids == ("warning",)
    members = EventGroupMembers(group_key(first))
    assert members.matches(event_resource(), event_record(object_uid=None))
    assert not members.matches(event_resource(), event_record(uid="second", object_uid=None))
    assert not members.matches(replace(event_resource(), version="v2"), event_record())
    assert len(event_rows((first, second), EventOptions(members=members))) == 1


def test_unknown_count_time_and_reporter_omissions_are_visible_and_not_zero():
    unknown = fact(uid="unknown", series={"count": None})
    known = fact(uid="known", series={"count": 4, "lastObservedTime": LAST})
    group = group_events((unknown, known), EventOptions())[0]
    assert (
        group.known_occurrences == 4
        and group.unknown_count_members == group.unknown_time_members == 1
    )
    row = event_rows((unknown, known), EventOptions(grouped=True), observed_at=AT)[0]
    assert row.values[3].sort is None and "unknown members" in row.values[3].text
    assert "latest reported" in row.values[4].text
    assert group_events((unknown,), EventOptions())[0].last_at is None
    assert event_rows((unknown,), EventOptions(grouped=True))[0].values[4].sort is None
    assert event_rows((unknown,), EventOptions())[0].values[3].sort is None
    reporters = tuple(fact(uid=str(index), reportingInstance=str(index)) for index in range(40))
    result = group_events(reporters, EventOptions())[0]
    assert len(result.reporters) == 32 and result.omitted_reporters == 8
    assert "8 omitted" in event_rows(reporters, EventOptions(grouped=True))[0].values[-1].text


def test_disjoint_raw_group_rows_matrix_columns_and_source_state():
    source = fact()
    raw = event_rows((source,), EventOptions())[0]
    grouped = event_rows((source,), EventOptions(grouped=True))[0]
    assert isinstance(raw, EventObjectRow) and raw.uid == source.uid
    assert isinstance(grouped, EventGroupRow) and not hasattr(grouped, "uid")
    assert len(raw.values) == len(grouped.values) == len(EVENT_FIELDS) == 6
    assert EVENT_CANARY not in repr(raw) + repr(grouped)
    assert all(len(value.text) <= 256 for row in (raw, grouped) for value in row.values)
    assert event_rows((), EventOptions()) == ()
    resource = event_resource()
    state = EventSourceState(
        ResourceScope(SessionIdentity("owned", 1), resource, "team"),
        3,
        CollectionState(),
        ViewStatus.LIVE,
        AT,
    )
    assert state.snapshot_seen_at is AT and state.scope.resource is resource


@pytest.mark.parametrize(
    "changes",
    [
        {"group": "wrong"},
        {"version": "v2"},
        {"name": "pods"},
        {"kind": "Pod"},
        {"namespaced": False},
    ],
)
def test_exact_source_and_captured_identity_guards(changes):
    with pytest.raises(AppError):
        event_fact(replace(event_resource(), **changes), event_record())
    for changes in [
        {"uid": None},
        {"namespace": None},
        {"name": "contradiction"},
        {"resource_version": "wrong"},
    ]:
        with pytest.raises(AppError):
            event_fact(event_resource(), replace(event_record(), **changes))


@pytest.mark.parametrize(
    "changes", [{"grouped": 1}, {"warnings_only": "yes"}, {"members": "query"}]
)
def test_options_require_closed_typed_choices(changes):
    with pytest.raises(AppError):
        EventOptions(**changes)


def test_fact_membership_and_byte_bounds_cannot_silently_drop_members():
    value = fact()
    with pytest.raises(AppError, match="count"):
        group_events((value,) * (MAX_EVENT_FACTS + 1), EventOptions())
    large = fact(
        type="x" * 8000,
        reason="y" * 8000,
        reportingController="z" * 8000,
        reportingInstance="w" * 8000,
    )
    assert len(repr(large).encode()) < MAX_EVENT_FACT_BYTES
    with pytest.raises(AppError, match="byte"):
        group_events(tuple(replace(large, uid=str(index)) for index in range(600)), EventOptions())


def test_captured_record_cannot_smuggle_contradictory_type_or_metadata_contents():
    source = event_record()
    for field, value in (("kind", "Pod"), ("apiVersion", "v2"), ("metadata", None)):
        raw = event_manifest()
        raw[field] = value
        record = ResourceRecord(
            source.name,
            source.uid,
            source.namespace,
            source.resource_version,
            source.created_at,
            json.dumps(raw).encode(),
        )
        with pytest.raises(AppError):
            event_fact(event_resource(), record)


def test_oversized_record_is_rejected_before_manifest_decoding():
    source = event_record()
    record = ResourceRecord(
        source.name,
        source.uid,
        source.namespace,
        source.resource_version,
        source.created_at,
        b"x" * (64 * 1024 * 1024 + 1),
    )
    with pytest.raises(AppError, match="complete supported Event"):
        event_fact(event_resource(), record)


@pytest.mark.parametrize("modern", [False, True])
def test_metadata_only_events_keep_real_identity_with_unknown_body_and_occurrences(modern):
    resource = event_resource(modern=modern)
    assert event_descriptor_supported(resource)
    raw = event_manifest(modern=modern)
    record = metadata_record(
        resource,
        {
            "apiVersion": "meta.k8s.io/v1",
            "kind": "PartialObjectMetadata",
            "metadata": raw["metadata"],
        },
    )
    result = event_fact(resource, record)
    assert (result.uid, result.name, result.namespace) == (
        record.uid,
        record.name,
        record.namespace,
    )
    assert result.regarding is result.event_type is result.reason is result.reporter is None
    assert result.count is result.first_at is result.last_at is None
    assert result.count_origin == result.last_origin == "unknown" and result.notices
    assert event_rows((result,), EventOptions())[0].uid == record.uid
    assert event_rows((result,), EventOptions(warnings_only=True)) == ()
    assert "warning-only" in result.notices[0]
    assert len(group_events((result, replace(result, uid="second")), EventOptions())) == 2
    with pytest.raises(AppError):
        event_fact(resource, replace(record, name="different"))
    # A compact marker cannot make contradictory full-object type fields valid.
    with pytest.raises(AppError):
        event_fact(replace(resource, version="v2"), record)


def test_supported_descriptor_does_not_accept_integer_scope_as_true():
    assert not event_descriptor_supported(replace(event_resource(), namespaced=1))
