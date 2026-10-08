"""Opaque checkpoints, stable UID state, bounds and retry classification."""

from dataclasses import replace

import pytest

from kuberich.domain import watches
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.resources import ResourceSnapshot, api_resource, resource_record
from kuberich.domain.watches import (
    EventType,
    Recovery,
    WatchEvent,
    WatchState,
    recovery,
    retry_delay,
    watch_event,
)
from kuberich.errors import AppError
from tests.support.resources import descriptor, item, pod_resource
from tests.support.watches import bookmark, error_event, event, snapshot


def test_all_events_bookmarks_and_duplicate_replays_preserve_opaque_checkpoint() -> None:
    state = WatchState(snapshot())
    added = watch_event(pod_resource(), event(version="z-last"), "team")
    assert state.apply(added)
    assert not state.apply(added)
    modified = watch_event(pod_resource(), event("MODIFIED", version="a-next"), "team")
    assert state.apply(modified)
    assert state.snapshot.items[0].resource_version == "a-next"
    assert state.apply(watch_event(pod_resource(), bookmark("bookmark-opaque")))
    assert state.resource_version == "bookmark-opaque"
    assert not state.apply(added)
    assert not state.apply(watch_event(pod_resource(), bookmark("a-next")))
    assert not state.apply(watch_event(pod_resource(), event("ADDED", version="a-next"), "team"))
    assert state.resource_version == "bookmark-opaque"
    deletion = watch_event(pod_resource(), event("DELETED", version="delete-version"))
    assert state.apply(deletion) and state.snapshot.items == ()
    assert not state.apply(deletion)
    missing = watch_event(pod_resource(), event("DELETED", "missing", "unknown-delete"))
    assert state.apply(missing) and state.snapshot.items == ()
    assert not state.apply(watch_event(pod_resource(), bookmark("unknown-delete")))


def test_initial_item_replay_does_not_rewind_collection_version() -> None:
    state = WatchState(snapshot(item()))
    replay = watch_event(pod_resource(), event(version="opaque/object"))
    assert not state.apply(replay)
    assert state.resource_version == "opaque-snapshot"
    assert state.apply(watch_event(pod_resource(), bookmark("bookmark")))
    assert not state.apply(watch_event(pod_resource(), bookmark("bookmark")))


def test_recreated_name_replaces_old_uid_and_late_delete_cannot_remove_new_resource() -> None:
    state = WatchState(snapshot(item(uid="old")))
    assert state.apply(watch_event(pod_resource(), event(uid="new", version="new-uid")))
    assert [(record.name, record.uid) for record in state.snapshot.items] == [("one", "new")]
    assert state.apply(
        watch_event(pod_resource(), event("DELETED", uid="old", version="old-deletion"))
    )
    assert state.snapshot.items[0].uid == "new"
    assert state.apply(
        watch_event(pod_resource(), event("MODIFIED", uid="new", version="modified"))
    )
    assert state.snapshot.items[0].uid == "new"


def test_same_uid_cannot_change_name_and_prior_snapshots_remain_immutable() -> None:
    state = WatchState(snapshot(item(uid="fixed")))
    before = state.snapshot
    with pytest.raises(AppError, match="UID identity"):
        state.apply(watch_event(pod_resource(), event(name="changed", uid="fixed")))
    assert state.snapshot == before
    assert state.apply(watch_event(pod_resource(), event(uid="fixed", version="changed")))
    assert before.items[0].resource_version == "opaque/object"
    assert state.snapshot.items[0].resource_version == "changed"


@pytest.mark.parametrize("limit", ["items", "bytes"])
def test_state_limit_rejection_is_atomic(monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    state = WatchState(snapshot(item()))
    before = state.snapshot
    if limit == "items":
        monkeypatch.setattr(watches, "MAX_RESOURCE_ITEMS", 1)
    else:
        monkeypatch.setattr(watches, "MAX_RESOURCE_BYTES", 1)
    with pytest.raises(AppError, match="limit"):
        state.apply(watch_event(pod_resource(), event(name="second")))
    assert state.snapshot == before


def test_replay_memory_and_repeated_recreation_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(watches, "MAX_RECENT_EVENTS", 2)
    state = WatchState(snapshot())
    for number in range(10):
        assert state.apply(
            watch_event(pod_resource(), event(uid=f"uid-{number}", version=f"rv-{number}"))
        )
    assert len(state.snapshot.items) == 1 and state.snapshot.items[0].uid == "uid-9"
    assert len(state._events) <= 2 and len(state._versions) <= 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"object": {}},
        {"type": {}, "object": {}},
        {"type": "UNKNOWN", "object": {}},
        {"type": "ERROR", "object": {"kind": "Wrong", "code": 410}},
        {"type": "ERROR", "object": {"code": True}},
        {"type": "ERROR", "object": {"code": 200}},
        {"type": "ERROR", "object": {"code": 600}},
        {"type": "ERROR", "object": {"code": 429, "details": {"retryAfterSeconds": -1}}},
        {"type": "ERROR", "object": {"code": 429, "details": {"retryAfterSeconds": "1"}}},
        {"type": "BOOKMARK", "object": {"kind": "Wrong"}},
        {"type": "BOOKMARK", "object": {"apiVersion": "apps/v1"}},
        {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": ""}}},
        {"type": "BOOKMARK", "object": {"metadata": {"resourceVersion": "opaque\nprivate"}}},
    ],
)
def test_malformed_frames_never_become_events(payload: object) -> None:
    with pytest.raises(AppError):
        watch_event(pod_resource(), payload)


@pytest.mark.parametrize("field", ["uid", "resourceVersion"])
def test_unversioned_nonwatch_records_cannot_be_watch_events(field: str) -> None:
    unwatchable = api_resource("v1", {**descriptor(), "verbs": ["list"]})
    payload = event()
    del payload["object"]["metadata"][field]
    with pytest.raises(AppError, match="UID and resourceVersion"):
        watch_event(unwatchable, payload)


@pytest.mark.parametrize("delay", [None, 3, 999999])
def test_error_event_retains_only_safe_status_and_bounded_delay(delay: int | None) -> None:
    with pytest.raises(HttpProblem) as error:
        watch_event(pod_resource(), error_event(410, delay))
    assert error.value.status == 410
    assert error.value.retry_after == (None if delay is None else min(delay, 300))
    assert "opaque-sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "variation",
    [
        "verb",
        "collection_version",
        "zero_version",
        "uid",
        "item_version",
        "duplicate_uid",
        "duplicate_name",
        "scope",
        "cluster_scope",
    ],
)
def test_invalid_initial_state_is_rejected(variation: str) -> None:
    value = snapshot(item())
    record = value.items[0]
    if variation == "verb":
        value = replace(value, resource=replace(value.resource, verbs=frozenset({"list"})))
    elif variation == "collection_version":
        value = replace(value, resource_version=None)
    elif variation == "zero_version":
        value = replace(value, resource_version="0")
    elif variation == "uid":
        value = replace(value, items=(replace(record, uid=None),))
    elif variation == "item_version":
        value = replace(value, items=(replace(record, resource_version=None),))
    elif variation == "duplicate_uid":
        value = replace(value, items=(record, record))
    elif variation == "duplicate_name":
        value = replace(value, items=(record, replace(record, uid="other")))
    elif variation == "scope":
        value = replace(value, items=(replace(record, namespace="other"),))
    else:
        value = replace(value, resource=replace(value.resource, namespaced=False))
    with pytest.raises(AppError):
        WatchState(value)


@pytest.mark.parametrize(
    "record", [None, replace(resource_record(pod_resource(), item()), uid=None)]
)
def test_event_requires_a_concrete_identity(record) -> None:
    state = WatchState(snapshot())
    with pytest.raises(AppError, match="concrete UID"):
        state.apply(WatchEvent(EventType.ADDED, "version", record))


def test_cluster_and_all_namespace_collections_preserve_scope() -> None:
    pods = pod_resource()
    all_scopes = ResourceSnapshot(pods, None, "opaque", (resource_record(pods, item()),))
    state = WatchState(all_scopes)
    assert state.apply(watch_event(pods, event(name="other", namespace="second")))
    assert {record.namespace for record in state.snapshot.items} == {"team", "second"}
    nodes = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    state = WatchState(ResourceSnapshot(nodes, None, "opaque", ()))
    assert state.apply(watch_event(nodes, event(namespace=None)))
    assert state.snapshot.items[0].namespace is None


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_only_transient_http_statuses_retry(status: int) -> None:
    assert recovery(HttpProblem(status)) is Recovery.RETRY


@pytest.mark.parametrize("status", [401, 403, 404, 400, 302, 501])
def test_auth_permissions_missing_resource_and_other_statuses_stop(status: int) -> None:
    assert recovery(HttpProblem(status)) is Recovery.STOP


@pytest.mark.parametrize("state", list(ConnectionState))
def test_transport_recovery_is_explicit(state: ConnectionState) -> None:
    assert recovery(ConnectionProblem(state, "owned")) is (
        Recovery.RETRY
        if state in {ConnectionState.TIMEOUT, ConnectionState.UNREACHABLE}
        else Recovery.STOP
    )
    assert recovery(HttpProblem(410)) is Recovery.RELIST


def test_exponential_jitter_stays_bounded_and_honors_server_minimum() -> None:
    assert [retry_delay(number, 0.5) for number in range(4)] == [0.25, 0.5, 1.0, 2.0]
    assert retry_delay(0, 0) == 0.2
    assert retry_delay(0, 1) == pytest.approx(0.3)
    assert retry_delay(1000000, 1) == 30
    assert retry_delay(0, 0.5, 300) == 300


@pytest.mark.parametrize(
    "values",
    [
        (True, 0.5, 0),
        (-1, 0.5, 0),
        (1.5, 0.5, 0),
        (0, -1, 0),
        (0, 2, 0),
        (0, float("nan"), 0),
        (0, 0.5, -1),
        (0, 0.5, 301),
        (0, 0.5, float("nan")),
    ],
)
def test_invalid_retry_inputs_fail_closed(values) -> None:
    with pytest.raises(AppError):
        retry_delay(*values)
