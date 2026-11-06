"""Owned cooperative decoding, exact source identity and retained-fact budgets."""

import asyncio
import gc
import threading
import weakref
from dataclasses import replace
from datetime import datetime

import pytest

from kuberich.domain.curated_navigation import AllResources, LabelsMatch, ResolvedCollectionBookmark
from kuberich.domain.events import (
    MAX_EVENT_FACT_BYTES,
    MAX_EVENT_FACTS,
    EventGroupMembers,
    EventGroupRow,
    EventObjectRow,
    EventOptions,
    event_fact,
    group_key,
)
from kuberich.domain.relationships import structured_selector
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState, resource_record
from kuberich.domain.views import ViewStatus
from kuberich.errors import AppError
from kuberich.services.events import EventProjection
from tests.support.events import EVENT_CANARY, event_record, event_snapshot, event_source


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_facts": 0},
        {"max_facts": MAX_EVENT_FACTS + 1},
        {"max_facts": True},
        {"max_bytes": 0},
        {"max_bytes": MAX_EVENT_FACT_BYTES + 1},
        {"max_bytes": 1.5},
    ],
)
def test_projection_rejects_nonpositive_or_above_hard_budgets(kwargs):
    with pytest.raises(AppError, match="budgets"):
        EventProjection(**kwargs)


@pytest.mark.asyncio
async def test_incremental_facts_options_deletion_and_source_generation(monkeypatch):
    calls = []

    def observe(resource, record):
        calls.append(record)
        return event_fact(resource, record)

    monkeypatch.setattr("kuberich.services.events.event_fact", observe)
    first, other = event_record(), event_record(uid="event-b", reason="Scheduled", type="Normal")
    snapshot = event_snapshot(first, other)
    source = event_source(snapshot)
    owner = EventProjection()
    initial = await owner.project(snapshot, source, EventOptions())
    assert len(initial.rows) == owner.cached_count == 2
    assert owner.accounted_bytes > 0 and owner.operation_count == 0
    assert initial.source is source and not initial.limited
    grouped = await owner.project(snapshot, source, EventOptions(grouped=True, warnings_only=True))
    assert len(grouped.rows) == 1 and isinstance(grouped.rows[0], EventGroupRow)
    assert len(calls) == 2
    assert EVENT_CANARY not in repr(initial) + repr(grouped)
    changed = event_record(series={"count": 9, "lastObservedTime": "2026-11-06T12:01:30Z"})
    update = replace(snapshot, items=(changed,))
    result = await owner.project(update, source, EventOptions())
    assert isinstance(result.rows[0], EventObjectRow) and result.rows[0].fact.count == 9
    assert owner.cached_count == 1 and len(calls) == 3
    await owner.project(update, event_source(update, generation=2), EventOptions())
    assert len(calls) == 4
    empty = await owner.project(None, None, EventOptions())
    assert empty.rows == () and not empty.limited and not empty.notices
    assert owner.cached_count == owner.accounted_bytes == 0
    await owner.retire()


@pytest.mark.asyncio
async def test_cache_has_no_strong_record_payload_and_rejects_dead_identity_reuse():
    record = event_record()
    reference = weakref.ref(record)
    snapshot = event_snapshot(record)
    source = event_source(snapshot)
    owner = EventProjection()
    original = await owner.project(snapshot, source, EventOptions())
    del record, snapshot
    gc.collect()
    assert reference() is None and owner.cached_count == 1
    replacement = event_record(series={"count": 4, "lastObservedTime": "2026-11-06T12:01:00Z"})
    result = await owner.project(event_snapshot(replacement), source, EventOptions())
    assert isinstance(result.rows[0], EventObjectRow)
    assert result.rows[0].fact is not original.rows[0].fact
    assert result.rows[0].fact.count == 4
    await owner.retire()
    assert owner.accounted_bytes == owner.cached_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["none", "resource", "namespace", "collection", "time", "unsupported"]
)
async def test_inconsistent_source_rejects_old_cache_and_never_projects(change):
    snapshot = event_snapshot(event_record())
    source = event_source(snapshot)
    owner = EventProjection()
    assert (await owner.project(snapshot, source, EventOptions())).rows
    if change == "none":
        source = None
    elif change == "resource":
        source = replace(
            source, scope=replace(source.scope, resource=replace(snapshot.resource, version="v2"))
        )
    elif change == "namespace":
        source = replace(source, scope=replace(source.scope, namespace="other"))
    elif change == "collection":
        source = replace(source, collection=CollectionState(complete=False))
    elif change == "time":
        source = replace(source, snapshot_seen_at=datetime(2026, 11, 6))
    else:
        snapshot = replace(snapshot, resource=replace(snapshot.resource, kind="Other"))
        source = event_source(snapshot)
    result = await owner.project(snapshot, source, EventOptions())
    assert result.rows == () and result.limited
    assert "source identity" in " ".join(result.notices)
    assert owner.cached_count == owner.accounted_bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ViewStatus.STALE, ViewStatus.RELISTING, ViewStatus.FAILED])
async def test_partial_source_and_unknown_warning_omissions_keep_honest_status(status):
    snapshot = replace(
        event_snapshot(event_record(type=None)),
        collection=CollectionState(complete=False, limited=True, pages=2),
    )
    source = event_source(snapshot, status=status)
    result = await EventProjection().project(snapshot, source, EventOptions(warnings_only=True))
    assert not result.rows and result.limited and result.source is source
    assert "unknown type" in " ".join(result.notices)
    assert "retained subset" in " ".join(result.notices)
    assert status.name.lower() in " ".join(result.notices)


@pytest.mark.asyncio
async def test_fact_limits_invalid_identity_and_duplicate_uid_replacements():
    records = tuple(event_record(uid=f"event-{index}") for index in range(3))
    snapshot = event_snapshot(*records)
    owner = EventProjection(max_facts=2)
    result = await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert len(result.rows) == owner.cached_count == 2 and result.limited
    assert "omitted 1" in " ".join(result.notices)
    owner = EventProjection(max_bytes=100)
    result = await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert not result.rows and result.limited and owner.accounted_bytes == 0
    broken = replace(records[0], uid="contradictory")
    wrong_namespace = event_record(uid="wrong-ns", namespace="other")
    snapshot = event_snapshot(broken, wrong_namespace, records[1])
    owner = EventProjection()
    result = await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert len(result.rows) == 1 and result.limited
    assert "Omitted 2" in " ".join(result.notices)
    # A malformed later record for the same actual UID cannot leave old values visible.
    snapshot = event_snapshot(records[0], replace(records[0], name="contradictory"))
    result = await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert not result.rows and owner.cached_count == owner.accounted_bytes == 0
    updated = event_record(uid="event-0", series={"count": 11})
    snapshot = event_snapshot(records[0], updated)
    result = await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert len(result.rows) == 1 and result.rows[0].fact.count == 11


@pytest.mark.asyncio
async def test_over_budget_duplicate_never_relabels_old_record_as_latest():
    record = event_record()
    snapshot = event_snapshot(record)
    charge = len(repr(event_fact(snapshot.resource, record)).encode()) + 256
    owner = EventProjection(max_bytes=charge)
    larger = event_record(reason="x" * 1000)
    duplicate = event_snapshot(record, larger)
    result = await owner.project(duplicate, event_source(duplicate), EventOptions())
    assert not result.rows and result.limited
    assert owner.cached_count == owner.accounted_bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_owned_thread_drains_before_latest_intent_or_retirement(monkeypatch, cancel):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def held(resource, record):
        calls.append(record.uid)
        if record.uid == "held":
            entered.set()
            assert release.wait(5), "owned decoder gate was not released"
        return event_fact(resource, record)

    monkeypatch.setattr("kuberich.services.events.event_fact", held)
    owner = EventProjection()
    snapshot = event_snapshot(event_record(uid="held"))
    task = asyncio.create_task(owner.project(snapshot, event_source(snapshot), EventOptions()))
    pending = latest = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert owner.operation_count == 1
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            pending = asyncio.create_task(owner.retire())
        else:
            second = event_snapshot(event_record(uid="superseded"))
            third = event_snapshot(event_record(uid="latest"))
            pending = asyncio.create_task(
                owner.project(second, event_source(second), EventOptions())
            )
            await asyncio.sleep(0)
            latest = asyncio.create_task(owner.project(third, event_source(third), EventOptions()))
        await asyncio.sleep(0)
        assert not task.done() and owner.operation_count == 1
    finally:
        release.set()
        outcomes = await asyncio.wait_for(
            asyncio.gather(
                task,
                *(item for item in (pending, latest) if item is not None),
                return_exceptions=True,
            ),
            5,
        )
    assert isinstance(outcomes[0], asyncio.CancelledError)
    if cancel:
        assert owner.cached_count == owner.accounted_bytes == 0
    else:
        assert isinstance(outcomes[1], asyncio.CancelledError)
        assert outcomes[2].rows[0].uid == "latest"
        assert calls == ["held", "latest"]
    assert owner.operation_count == 0
    await owner.retire()


@pytest.mark.asyncio
async def test_unexpected_decoder_failure_surfaces_without_leaking_worker(monkeypatch):
    def fail(*args):
        raise ValueError("owned presentation failure")

    monkeypatch.setattr("kuberich.services.events.event_fact", fail)
    owner = EventProjection()
    snapshot = event_snapshot(event_record())
    with pytest.raises(ValueError, match="presentation failure"):
        await owner.project(snapshot, event_source(snapshot), EventOptions())
    assert owner.operation_count == owner.cached_count == 0
    await owner.retire()


@pytest.mark.asyncio
@pytest.mark.parametrize("superseded", [False, True])
async def test_cancelled_retirement_still_drains_and_never_clears_newer_cache(
    monkeypatch, superseded
):
    entered, release = threading.Event(), threading.Event()

    def held(resource, record):
        if record.uid == "held":
            entered.set()
            assert release.wait(5)
        return event_fact(resource, record)

    monkeypatch.setattr("kuberich.services.events.event_fact", held)
    owner = EventProjection()
    snapshot = event_snapshot(event_record(uid="held"))
    original = asyncio.create_task(owner.project(snapshot, event_source(snapshot), EventOptions()))
    retirement = latest = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        retirement = asyncio.create_task(owner.retire())
        await asyncio.sleep(0)
        retirement.cancel()
        if superseded:
            newer = event_snapshot(event_record(uid="newer"))
            latest = asyncio.create_task(owner.project(newer, event_source(newer), EventOptions()))
        await asyncio.sleep(0)
        assert not retirement.done() and owner.operation_count == 1
    finally:
        release.set()
        outcomes = await asyncio.wait_for(
            asyncio.gather(
                original,
                *(task for task in (retirement, latest) if task is not None),
                return_exceptions=True,
            ),
            5,
        )
    assert all(isinstance(result, asyncio.CancelledError) for result in outcomes[:2])
    assert owner.operation_count == 0
    if superseded:
        assert outcomes[2].rows[0].uid == "newer" and owner.cached_count == 1
    else:
        assert owner.cached_count == owner.accounted_bytes == 0
    await owner.retire()


def labeled(uid, label):
    raw = event_record(uid=uid).manifest
    raw["metadata"]["labels"] = {"app": label}
    return resource_record(event_snapshot().resource, raw)


def bookmarked(snapshot, predicate):
    return ResolvedCollectionBookmark(
        snapshot.resource, snapshot.namespace, predicate, ResourceQuery()
    )


@pytest.mark.asyncio
async def test_bookmark_predicate_runs_in_owned_worker_before_cache_reuse_or_retention(monkeypatch):
    main_thread = threading.get_ident()
    checked, decoded = [], []
    matches = LabelsMatch.matches

    def match(predicate, resource, record):
        assert threading.get_ident() != main_thread
        checked.append(record.uid)
        return matches(predicate, resource, record)

    def decode(resource, record):
        decoded.append(record.uid)
        return event_fact(resource, record)

    monkeypatch.setattr(LabelsMatch, "matches", match)
    monkeypatch.setattr("kuberich.services.events.event_fact", decode)
    first, second = labeled("first", "one"), labeled("second", "two")
    snapshot = event_snapshot(first, second)
    source, owner = event_source(snapshot), EventProjection()
    selected = bookmarked(
        snapshot, LabelsMatch(structured_selector({"matchLabels": {"app": "one"}}))
    )
    result = await owner.project(snapshot, source, EventOptions(), bookmark=selected)
    assert tuple(row.uid for row in result.rows) == ("first",)
    assert owner.cached_count == 1 and decoded == ["first"]
    assert checked == ["first", "second"] and not result.limited
    all_records = bookmarked(snapshot, AllResources())
    result = await owner.project(snapshot, source, EventOptions(), bookmark=all_records)
    assert len(result.rows) == owner.cached_count == 2
    assert decoded == ["first", "second"]
    # Cache reuse cannot skip the new predicate. Only its passing facts survive.
    selected = bookmarked(
        snapshot, LabelsMatch(structured_selector({"matchLabels": {"app": "two"}}))
    )
    result = await owner.project(snapshot, source, EventOptions(), bookmark=selected)
    assert tuple(row.uid for row in result.rows) == ("second",)
    assert owner.cached_count == 1 and decoded == ["first", "second"]
    assert checked == ["first", "second", "first", "second"]
    await owner.retire()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["resource", "namespace", "query"])
async def test_mismatched_bookmark_clears_cache_without_decoding_or_scope_expansion(
    change, monkeypatch
):
    snapshot = event_snapshot(event_record())
    source, owner = event_source(snapshot), EventProjection()
    bookmark = bookmarked(snapshot, AllResources())
    assert (await owner.project(snapshot, source, EventOptions(), bookmark=bookmark)).rows
    if change == "resource":
        bookmark = replace(bookmark, resource=replace(snapshot.resource, version="v9"))
    elif change == "namespace":
        bookmark = replace(bookmark, namespace=None)
    else:
        bookmark = replace(bookmark, query=ResourceQuery(label_selector="app=other"))

    def unexpected(*args):
        pytest.fail("A mismatched bookmark must fail before starting the decoder")

    monkeypatch.setattr("kuberich.services.events.event_fact", unexpected)
    result = await owner.project(snapshot, source, EventOptions(), bookmark=bookmark)
    assert not result.rows and result.limited
    assert "captured collection" in " ".join(result.notices)
    assert owner.cached_count == owner.accounted_bytes == owner.operation_count == 0


@pytest.mark.asyncio
async def test_group_members_bookmark_keeps_exact_object_uid_and_current_members():
    first = event_record(uid="first")
    same_group = event_record(uid="second")
    replacement_object = event_record(uid="other-object", object_uid="recreated-object")
    snapshot = event_snapshot(first, same_group, replacement_object)
    bookmark = bookmarked(
        snapshot, EventGroupMembers(group_key(event_fact(snapshot.resource, first)))
    )
    source, owner = event_source(snapshot), EventProjection()
    grouped = await owner.project(snapshot, source, EventOptions(grouped=True), bookmark=bookmark)
    assert len(grouped.rows) == 1 and isinstance(grouped.rows[0], EventGroupRow)
    assert grouped.rows[0].group.member_uids == ("first", "second")
    # A changed reason is no longer a member despite the same Event UID.
    modified = event_record(uid="first", reason="DifferentReason")
    update = replace(snapshot, items=(modified, same_group, replacement_object))
    raw = await owner.project(update, source, EventOptions(), bookmark=bookmark)
    assert tuple(row.uid for row in raw.rows) == ("second",)
    assert owner.cached_count == 1
    await owner.retire()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_held_bookmark_predicate_drains_before_latest_captured_membership(
    monkeypatch, cancel_first
):
    entered, release = threading.Event(), threading.Event()
    original = LabelsMatch.matches
    hold = [True]

    def match(predicate, resource, record):
        if hold[0]:
            hold[0] = False
            entered.set()
            assert release.wait(5)
        return original(predicate, resource, record)

    monkeypatch.setattr(LabelsMatch, "matches", match)
    snapshot = event_snapshot(labeled("first", "one"), labeled("second", "two"))
    owner, source = EventProjection(), event_source(snapshot)
    one = bookmarked(snapshot, LabelsMatch(structured_selector({"matchLabels": {"app": "one"}})))
    two = bookmarked(snapshot, LabelsMatch(structured_selector({"matchLabels": {"app": "two"}})))
    first = asyncio.create_task(owner.project(snapshot, source, EventOptions(), bookmark=one))
    pending = latest = None
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if cancel_first:
            first.cancel()
        pending = asyncio.create_task(owner.project(snapshot, source, EventOptions(), bookmark=one))
        await asyncio.sleep(0)
        latest = asyncio.create_task(owner.project(snapshot, source, EventOptions(), bookmark=two))
        await asyncio.sleep(0)
        assert owner.operation_count == 1 and not first.done()
    finally:
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(
                first,
                *(task for task in (pending, latest) if task is not None),
                return_exceptions=True,
            ),
            5,
        )
    assert isinstance(results[0], asyncio.CancelledError)
    assert isinstance(results[1], asyncio.CancelledError)
    assert tuple(row.uid for row in results[2].rows) == ("second",)
    assert owner.cached_count == 1 and owner.operation_count == 0
    await owner.retire()
