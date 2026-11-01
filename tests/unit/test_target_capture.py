"""Captured viewers cannot follow client replacement or a recreated resource UID."""

from dataclasses import replace

import pytest

from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import ResourceSnapshot, resource_record
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ResourceScope, ResourceSelection, ViewObservation, ViewStatus
from kuberich.domain.watches import WatchState, watch_event
from kuberich.ui.target_capture import TargetCapture, TargetSelection
from tests.support.pods import pod, snapshot
from tests.support.tables import custom_item, custom_resource
from tests.support.watches import event


class OwnedWorkspace:
    def __init__(self):
        data = snapshot(pod("alpha"), pod("beta"))
        self.view = ViewObservation(
            revision=3,
            context="owned",
            scope=ResourceScope(SessionIdentity("owned", 1), data.resource, "team"),
            snapshot=data,
            status=ViewStatus.LIVE,
        )
        self.client = object()
        self.selected = TargetSelection(ViewRoute.pods(), "owned-alpha")
        self.notices, self.statuses = [], []
        self.capture = TargetCapture(
            lambda: self.view,
            lambda: self.client,
            lambda: self.selected,
            self.notices.append,
            self.statuses.append,
        )


def test_capture_refuses_a_changed_server_query_and_a_retained_uid_evicted_for_size(monkeypatch):
    from kuberich.domain import watches

    workspace = OwnedWorkspace()
    captured = workspace.capture.capture()
    original_scope = workspace.view.scope
    workspace.view = replace(
        workspace.view, scope=replace(original_scope, query=ResourceQuery("app=api"))
    )
    assert not captured.current()
    workspace.view = replace(workspace.view, scope=original_scope)
    state = WatchState(workspace.view.snapshot)
    monkeypatch.setattr(
        watches, "MAX_RESOURCE_BYTES", state.snapshot.collection.retained_bytes + 10
    )
    newer = event("MODIFIED", "alpha", "large", uid="owned-alpha")
    newer["object"]["spec"]["payload"] = "x" * 10_000
    assert state.apply(watch_event(original_scope.resource, newer, "team"))
    workspace.view = replace(workspace.view, snapshot=state.snapshot)
    assert not captured.current()
    assert {record.uid for record in state.snapshot.items} == {"owned-beta"}
    assert not state.snapshot.collection.complete


@pytest.mark.parametrize(
    "blocked", ["modal", "contexts", "scope", "snapshot", "client", "uid", "stale"]
)
def test_target_capture_preserves_the_existing_local_missing_and_stale_notices(blocked):
    workspace = OwnedWorkspace()
    if blocked == "modal":
        workspace.selected = replace(workspace.selected, modal=True)
    elif blocked == "contexts":
        workspace.selected = replace(workspace.selected, route=ViewRoute.contexts())
    elif blocked in {"scope", "snapshot"}:
        workspace.view = replace(workspace.view, **{blocked: None})
    elif blocked == "client":
        workspace.client = None
    else:
        workspace.selected = replace(
            workspace.selected, uid=None if blocked == "uid" else "replaced"
        )
    assert workspace.capture.capture() is None
    if blocked == "modal":
        assert workspace.notices == workspace.statuses == []
    elif blocked == "contexts":
        assert workspace.notices == [
            "Contexts are local configuration. Enter connects to the selected context."
        ]
    elif blocked == "stale":
        assert workspace.statuses == ["The selected target is stale; select the resource again."]
    else:
        assert workspace.notices == ["Select a connected resource before opening a viewer."]


@pytest.mark.parametrize("change", ["client", "scope", "revision", "snapshot", "failed"])
def test_captured_target_refuses_every_prior_session_scope_and_revision(change):
    workspace = OwnedWorkspace()
    captured = workspace.capture.capture()
    assert captured.current()
    assert (
        captured.client is workspace.client and captured.resource == workspace.view.scope.resource
    )
    if change == "client":
        workspace.client = object()
    elif change == "scope":
        workspace.view = replace(
            workspace.view, scope=replace(workspace.view.scope, namespace="other")
        )
    elif change == "revision":
        workspace.view = replace(workspace.view, revision=4)
    elif change == "snapshot":
        workspace.view = replace(workspace.view, snapshot=None)
    else:
        workspace.view = replace(workspace.view, status=ViewStatus.FAILED)
    assert not captured.current()


def test_explicit_uid_and_snapshot_membership_remain_captured_and_are_cached_per_snapshot():
    workspace = OwnedWorkspace()
    captured = workspace.capture.capture("owned-beta")
    assert captured.target.uid == captured.record.uid == "owned-beta"
    assert captured.target.name == "beta" and captured.current()

    class CountedRecords(tuple):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    records = CountedRecords(workspace.view.snapshot.items)
    workspace.view = replace(
        workspace.view, snapshot=replace(workspace.view.snapshot, items=records)
    )
    assert captured.current() and captured.current() and records.iterations == 1
    absent = CountedRecords((workspace.view.snapshot.items[0],))
    workspace.view = replace(
        workspace.view, snapshot=replace(workspace.view.snapshot, items=absent)
    )
    assert not captured.current() and not captured.current() and absent.iterations == 1
    workspace.view = replace(
        workspace.view, snapshot=replace(workspace.view.snapshot, items=records)
    )
    assert captured.current() and records.iterations == 2
    workspace.client = object()
    assert not captured.current() and records.iterations == 2


def test_a_custom_resource_named_contexts_remains_an_api_capture():
    workspace = OwnedWorkspace()
    resource = custom_resource(name="contexts")
    record = resource_record(resource, custom_item("alpha", uid="owned-alpha"), "team")
    workspace.view = replace(
        workspace.view,
        scope=replace(workspace.view.scope, resource=resource),
        snapshot=ResourceSnapshot(resource, "team", "owned", (record,)),
    )
    workspace.selected = replace(
        workspace.selected,
        route=ViewRoute.custom(
            ResourceSelection("contexts", "owned.example.test", server_columns=True)
        ),
    )
    captured = workspace.capture.capture()
    assert captured is not None and captured.current()
    assert workspace.notices == workspace.statuses == []
