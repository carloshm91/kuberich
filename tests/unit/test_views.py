"""View identity, cache invalidation and visible recovery decisions."""

from dataclasses import replace

import pytest

from kubetrol.domain.connections import ConnectionProblem, ConnectionState, SessionObservation
from kubetrol.domain.resources import api_resource
from kubetrol.domain.targets import SessionIdentity
from kubetrol.domain.views import ResourceScope, ResourceSelection, ViewStatus, ViewStore
from kubetrol.domain.watches import SyncStatus, SyncUpdate
from kubetrol.errors import AppError
from tests.support.resources import descriptor, item
from tests.support.watches import snapshot


def bound_view():
    store = ViewStore()
    revision = store.begin("owned")
    connection = SessionObservation(
        ConnectionState.CONNECTED, "Connected", SessionIdentity("owned", 1), "team"
    )
    assert store.connected(revision, connection)
    scope = ResourceScope(connection.identity, snapshot().resource, "team")
    assert store.bind(revision, scope)
    return store, revision, scope


@pytest.mark.parametrize(
    "selection",
    [ResourceSelection(), ResourceSelection("po"), ResourceSelection("deployments", "apps", "v1")],
)
def test_resource_selection_is_original_validated_query(selection):
    assert selection.name and selection.group in {"", "apps"}


@pytest.mark.parametrize("kwargs", [{"name": "pods/log"}, {"group": "BAD"}, {"version": "v1/"}])
def test_invalid_selection_fails_before_transport(kwargs):
    with pytest.raises(AppError):
        ResourceSelection(**kwargs)


def test_scope_validates_namespaced_and_cluster_paths():
    session = SessionIdentity("owned", 1)
    with pytest.raises(AppError):
        ResourceScope(session, snapshot().resource, "INVALID")
    cluster = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    with pytest.raises(AppError):
        ResourceScope(session, cluster, "team")
    assert ResourceScope(session, cluster, None).namespace is None


@pytest.mark.parametrize("status", list(SyncStatus))
@pytest.mark.parametrize("has_snapshot", [False, True])
def test_current_updates_map_to_explicit_state_and_never_fake_an_empty_snapshot(
    status, has_snapshot
):
    store, revision, scope = bound_view()
    value = snapshot(item()) if has_snapshot else None
    problem = (
        ConnectionProblem(ConnectionState.UNREACHABLE, "Owned network failure")
        if status in {SyncStatus.RETRYING, SyncStatus.RELISTING, SyncStatus.FAILED}
        else None
    )
    assert store.apply(revision, scope, SyncUpdate(status, value, problem=problem))
    view = store.observation
    assert view.snapshot is value
    assert (
        (str(view.problem), view.problem.state) == (str(problem), problem.state)
        if problem
        else view.problem is None
    )
    assert (
        view.status
        is {
            SyncStatus.LOADING: ViewStatus.LOADING,
            SyncStatus.SNAPSHOT: ViewStatus.LOADING,
            SyncStatus.LIVE: ViewStatus.LIVE,
            SyncStatus.RETRYING: ViewStatus.STALE,
            SyncStatus.RELISTING: ViewStatus.RELISTING,
            SyncStatus.FAILED: ViewStatus.FAILED,
        }[status]
    )
    if problem:
        assert str(problem) in view.message
        assert ("Stale resource data" in view.message) == (
            has_snapshot and status is not SyncStatus.RELISTING
        )
    else:
        assert "1 pods" in view.message if has_snapshot else view.message == "Loading pods"


def test_switch_clears_snapshot_immediately_and_rejects_all_old_results():
    store, revision, scope = bound_view()
    value = snapshot(item())
    assert store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, value))
    previous = store.observation
    newer = store.begin("different")
    assert newer > revision and store.observation.snapshot is None
    assert store.observation.status is ViewStatus.CONNECTING
    assert "Connecting" in store.observation.message
    assert not store.connected(revision, previous.connection)
    assert not store.bind(revision, scope)
    assert not store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, value))
    assert not store.fail(revision, ConnectionProblem(ConnectionState.AUTH_ERROR, "Old failure"))
    assert store.observation.context == "different" and previous.snapshot is value
    store.disconnect()
    assert store.observation.context is None and store.observation.scope is None
    assert store.observation.status is ViewStatus.DISCONNECTED
    assert "Disconnected" in store.observation.message


@pytest.mark.parametrize("change", ["client", "generation", "namespace", "resource"])
def test_same_context_late_resource_or_client_identity_is_rejected(change):
    store, revision, scope = bound_view()
    if change == "client":
        old = replace(scope, session=SessionIdentity("owned", scope.session.generation))
    elif change == "generation":
        old = replace(scope, session=replace(scope.session, generation=2))
    elif change == "namespace":
        old = replace(scope, namespace="default")
    else:
        old = replace(scope, resource=api_resource("v1", descriptor("services", kind="Service")))
    assert not store.apply(revision, old, SyncUpdate(SyncStatus.LIVE, snapshot(item())))
    assert store.observation.snapshot is None


@pytest.mark.parametrize("change", ["client", "namespace", "connection_state"])
def test_current_binding_refuses_a_scope_outside_the_actual_connection(change):
    store, revision, scope = bound_view()
    if change == "client":
        scope = replace(scope, session=SessionIdentity("owned", 1))
    elif change == "namespace":
        scope = replace(scope, namespace="default")
    else:
        store.connected(
            revision, replace(store.observation.connection, state=ConnectionState.AUTH_ERROR)
        )
    with pytest.raises(AppError, match="active connection"):
        store.bind(revision, scope)


@pytest.mark.parametrize("change", ["resource", "namespace"])
def test_current_snapshot_must_match_its_captured_scope(change):
    store, revision, scope = bound_view()
    value = snapshot(item())
    value = replace(
        value,
        **{change: "other" if change == "namespace" else replace(scope.resource, name="services")},
    )
    with pytest.raises(AppError, match="captured scope"):
        store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, value))
    assert store.observation.snapshot is None


@pytest.mark.parametrize("identity", [None, SessionIdentity("wrong", 1)])
def test_current_connection_cannot_supply_another_context(identity):
    store = ViewStore()
    revision = store.begin("owned")
    with pytest.raises(AppError, match="active context"):
        store.connected(revision, SessionObservation(identity=identity))


def test_cluster_scope_limited_access_and_scope_only_switches():
    store, _, scope = bound_view()
    connection = replace(store.observation.connection, state=ConnectionState.LIMITED)
    revision = store.begin("owned", connection)
    assert store.observation.status is ViewStatus.LOADING
    assert "Loading resource discovery" in store.observation.message
    assert store.connected(revision, connection)
    cluster = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    assert store.bind(revision, ResourceScope(scope.session, cluster, None))
    assert store.observation.scope.namespace is None


def test_connection_and_discovery_failures_remain_distinct_and_can_keep_last_snapshot():
    store, revision, scope = bound_view()
    assert store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, snapshot(item())))
    problem = ConnectionProblem(ConnectionState.LIMITED, "Owned permission failure")
    assert store.fail(revision, problem)
    assert store.observation.status is ViewStatus.FAILED and store.observation.snapshot
    assert "Stale resource data" in store.observation.message
    revision = store.begin("owned")
    connection = SessionObservation(
        ConnectionState.AUTH_ERROR, "Owned login failure", scope.session
    )
    assert store.connected(revision, connection)
    assert store.observation.status is ViewStatus.FAILED
    assert store.observation.message == connection.message


def test_published_http_failure_copies_only_safe_fields_without_transport_frames():
    from kubetrol.domain.connections import HttpProblem

    store, revision, scope = bound_view()
    try:
        raise HttpProblem(429, retry_after=17)
    except HttpProblem as problem:
        assert store.apply(revision, scope, SyncUpdate(SyncStatus.RETRYING, problem=problem))
        copied = store.observation.problem
        assert isinstance(copied, HttpProblem) and copied is not problem
        assert copied.status == 429 and copied.retry_after == 17
        assert copied.__traceback__ is copied.__context__ is copied.__cause__ is None
