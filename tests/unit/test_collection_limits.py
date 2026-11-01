"""Retained UID ownership stays bounded, live and explicitly incomplete."""

from dataclasses import replace

import pytest

from kuberich.domain import watches
from kuberich.domain.resources import CollectionState, ResourceSnapshot
from kuberich.domain.tables import TableDecoder
from kuberich.domain.views import ViewStatus
from kuberich.domain.watches import SyncStatus, SyncUpdate, WatchState, watch_event
from tests.support.resources import item, pod_resource
from tests.support.tables import custom_item, custom_resource, server_table
from tests.support.watches import event, snapshot
from tests.unit.test_views import bound_view


def test_item_limit_keeps_watching_retained_rows_and_never_claims_completeness(monkeypatch):
    monkeypatch.setattr(watches, "MAX_RESOURCE_ITEMS", 2)
    state = WatchState(snapshot(item("one"), item("two")))
    assert state.apply(watch_event(pod_resource(), event(name="three", version="limit")))
    limited = state.snapshot
    assert [row.name for row in limited.items] == ["one", "two"]
    assert limited.collection.limited and not limited.collection.complete
    assert state.apply(watch_event(pod_resource(), event("MODIFIED", "one", "modified")))
    assert state.snapshot.items[0].resource_version == "modified"
    assert state.apply(watch_event(pod_resource(), event("DELETED", "two", "deleted")))
    assert state.apply(watch_event(pod_resource(), event(name="four", version="admitted")))
    assert [row.name for row in state.snapshot.items] == ["one", "four"]
    assert not state.snapshot.collection.complete
    assert limited.items[0].resource_version == "opaque/object"
    assert WatchState(snapshot(item("one"))).snapshot.collection.complete


@pytest.mark.parametrize("replacement", [False, True])
def test_oversized_newer_record_drops_the_old_target_instead_of_retaining_stale_bytes(
    monkeypatch, replacement
):
    initial = snapshot(item())
    monkeypatch.setattr(watches, "MAX_RESOURCE_BYTES", initial.items[0].size_bytes + 20)
    state = WatchState(initial)
    update = event(
        "MODIFIED", uid="replacement" if replacement else "owned-one", version="new-large"
    )
    update["object"]["spec"]["payload"] = "x" * 100
    assert state.apply(watch_event(pod_resource(), update))
    assert state.snapshot.items == ()
    assert state.snapshot.collection.retained_bytes == 0
    assert state.snapshot.collection.limited and not state.snapshot.collection.complete
    assert state.resource_version == "new-large"
    assert state.apply(watch_event(pod_resource(), event(name="small", version="small-new")))
    assert len(state.snapshot.items) == 1 and not state.snapshot.collection.complete


def test_incomplete_initial_list_remains_incomplete_after_bookmarks_updates_and_deletions():
    original = snapshot(item())
    original = replace(
        original, collection=CollectionState(False, True, 4, original.items[0].size_bytes)
    )
    state = WatchState(original)
    assert state.apply(watch_event(pod_resource(), event("MODIFIED", version="changed")))
    assert state.apply(watch_event(pod_resource(), event("DELETED", version="gone")))
    assert state.snapshot.items == ()
    assert state.snapshot.collection == CollectionState(False, True, 4, 0)


@pytest.mark.parametrize("limited", [False, True])
def test_view_reports_partial_page_progress_or_retained_limit_without_a_false_total(limited):
    store, revision, scope = bound_view()
    value = replace(snapshot(item()), collection=CollectionState(False, limited, 3, 100))
    assert store.apply(revision, scope, SyncUpdate(SyncStatus.LOADING, value))
    view = store.observation
    assert view.status is ViewStatus.LOADING and "INCOMPLETE" in view.message
    assert "1 retained pods" in view.message
    assert ("limit reached" if limited else "loading page 3") in view.message


def test_metadata_only_table_watch_keeps_real_partial_objects_and_typed_server_cells():
    resource = custom_resource()
    obj = custom_item()
    obj = {
        "apiVersion": "meta.k8s.io/v1",
        "kind": "PartialObjectMetadata",
        "metadata": obj["metadata"],
    }
    decoder = TableDecoder(resource, "team", metadata_only=True)
    records = decoder.records(server_table(obj))
    state = WatchState(ResourceSnapshot(resource, "team", "collection", records, decoder.columns))
    assert records[0].metadata_only and records[0].server.cells == ("one", 3, True)
    obj["metadata"]["resourceVersion"] = "updated"
    value = server_table(obj, headers=False)
    value["rows"][0]["cells"][1] = 7
    assert state.apply(decoder.event({"type": "MODIFIED", "object": value}))
    current = state.snapshot.items[0]
    assert current.metadata_only and current.server.cells[1] == 7
    assert current.manifest["kind"] == "PartialObjectMetadata" and "spec" not in current.manifest
