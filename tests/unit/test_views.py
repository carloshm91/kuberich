"""View identity, cache invalidation and visible recovery decisions."""

from dataclasses import replace

import pytest

from kuberich.domain.connections import ConnectionProblem, ConnectionState, SessionObservation
from kuberich.domain.pulse import PulseScope
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipRef,
    RelationshipRequest,
    RelationshipRow,
    RelationshipScope,
    RelationshipSnapshot,
    RelationshipSource,
    RelationshipStatus,
)
from kuberich.domain.resources import CollectionState, api_resource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.views import ResourceScope, ResourceSelection, ViewStatus, ViewStore
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.errors import AppError
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


def relationship_request(connection, *, root_namespace="team", resource=None):
    resource = resource or snapshot().resource
    root = ResourceTarget(
        connection.identity, resource.group, resource.name, root_namespace, "root", "root-uid"
    )
    scope = RelationshipScope(root, resource, connection.namespace, RelationshipMode.XRAY)
    return RelationshipRequest(scope, 1, frozenset())


def relationship_row(request, status=RelationshipStatus.READY):
    root, resource = request.scope.root, request.scope.resource
    ref = RelationshipRef(
        resource.api_version, resource.kind, root.namespace, root.name, root.uid, resource
    )
    return RelationshipRow((), ref, None, None, None, status, root.uid, (), True)


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
    from kuberich.domain.connections import HttpProblem

    store, revision, scope = bound_view()
    try:
        raise HttpProblem(429, retry_after=17)
    except HttpProblem as problem:
        assert store.apply(revision, scope, SyncUpdate(SyncStatus.RETRYING, problem=problem))
        copied = store.observation.problem
        assert isinstance(copied, HttpProblem) and copied is not problem
        assert copied.status == 429 and copied.retry_after == 17
        assert copied.__traceback__ is copied.__context__ is copied.__cause__ is None


@pytest.mark.parametrize("selected_namespace", [None, "team", "other"])
def test_graph_binds_the_captured_object_namespace_independently_from_selected_scan_scope(
    selected_namespace,
):
    store, _, _ = bound_view()
    connection = replace(store.observation.connection, namespace=selected_namespace)
    revision = store.begin("owned", connection)
    request = relationship_request(connection)
    assert request.scope.namespace == selected_namespace and request.scope.root.namespace == "team"
    assert store.bind_relationships(revision, request)
    assert store.observation.scope is store.observation.snapshot is store.observation.pulse is None
    assert store.observation.metrics is store.observation.problem is None
    assert store.observation.relationships.request == request
    assert store.observation.status is ViewStatus.LOADING
    assert store.observation.message == "xray relationships · Loading references"


@pytest.mark.parametrize(
    "change",
    [
        "client",
        "generation",
        "connection",
        "selected_namespace",
        "resource",
        "group",
        "root_namespace",
    ],
)
def test_graph_binding_rejects_current_roots_outside_their_connection_or_descriptor(change):
    store, revision, _ = bound_view()
    connection = store.observation.connection
    request = relationship_request(connection)
    scope = request.scope
    if change == "client":
        scope = replace(scope, root=replace(scope.root, session=SessionIdentity("owned", 1)))
    elif change == "generation":
        scope = replace(
            scope, root=replace(scope.root, session=replace(scope.root.session, generation=2))
        )
    elif change == "connection":
        store.connected(revision, replace(connection, state=ConnectionState.AUTH_ERROR))
    elif change == "selected_namespace":
        scope = replace(scope, namespace="other")
    elif change == "resource":
        scope = replace(scope, resource=replace(scope.resource, name="services"))
    elif change == "group":
        scope = replace(scope, resource=replace(scope.resource, group="example.test"))
    else:
        scope = replace(scope, root=replace(scope.root, namespace=None))
    with pytest.raises(AppError, match="active connection"):
        store.bind_relationships(revision, replace(request, scope=scope))
    assert store.observation.relationships is None


@pytest.mark.parametrize("namespace", ["team", "INVALID"])
def test_graph_binding_validates_the_actual_descriptor_namespace_path(namespace):
    store, revision, _ = bound_view()
    resource = (
        api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
        if namespace == "team"
        else snapshot().resource
    )
    request = relationship_request(
        store.observation.connection, root_namespace=namespace, resource=resource
    )
    with pytest.raises(AppError):
        store.bind_relationships(revision, request)
    assert store.observation.relationships is None


def test_cluster_graph_root_keeps_the_selected_namespace_for_related_pod_scans():
    store, revision, _ = bound_view()
    resource = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    request = relationship_request(
        store.observation.connection, root_namespace=None, resource=resource
    )
    assert store.bind_relationships(revision, request)
    assert store.observation.relationships.request.scope.root.namespace is None
    assert store.observation.relationships.request.scope.namespace == "team"


@pytest.mark.parametrize(
    "change", ["request_revision", "expansion", "root_uid", "session", "namespace", "descriptor"]
)
def test_graph_publication_requires_the_exact_current_request(change):
    store, revision, _ = bound_view()
    request = relationship_request(store.observation.connection)
    published = RelationshipSnapshot(request, (relationship_row(request),), (), 1, None)
    assert not store.bind_relationships(revision - 1, request)
    assert not store.apply_relationships(revision, published)
    assert store.bind_relationships(revision, request)
    assert not store.apply_relationships(revision - 1, published)
    if change == "request_revision":
        other = replace(request, revision=2)
    elif change == "expansion":
        other = replace(request, expanded=frozenset({()}))
    else:
        scope = request.scope
        if change == "root_uid":
            scope = replace(scope, root=replace(scope.root, uid="replacement-uid"))
        elif change == "session":
            scope = replace(scope, root=replace(scope.root, session=SessionIdentity("owned", 1)))
        elif change == "namespace":
            scope = replace(scope, namespace=None)
        else:
            scope = replace(scope, resource=replace(scope.resource, version="v2"))
        other = replace(request, scope=scope)
    assert not store.apply_relationships(revision, replace(published, request=other))
    assert not store.observation.relationships.rows
    assert store.apply_relationships(revision, published)
    assert store.observation.relationships is published
    assert store.observation.status is ViewStatus.LIVE
    assert store.observation.message == "xray relationships · Observed references"
    next_revision = store.begin("owned", store.observation.connection)
    assert next_revision > revision and store.observation.relationships is None
    assert not store.apply_relationships(revision, published)


@pytest.mark.parametrize("destination", ["resource", "pulse"])
def test_binding_another_current_route_retires_the_graph_publication(destination):
    store, revision, scope = bound_view()
    request = relationship_request(store.observation.connection)
    assert store.bind_relationships(revision, request)
    published = RelationshipSnapshot(request, (relationship_row(request),), (), 1, None)
    assert store.apply_relationships(revision, published)
    if destination == "resource":
        assert store.bind(revision, scope)
        assert store.observation.scope == scope
    else:
        assert store.bind_pulse(revision, PulseScope(scope.session, scope.namespace))
        assert store.observation.pulse is not None
    assert store.observation.relationships is None
    assert not store.apply_relationships(revision, published)


@pytest.mark.parametrize("loading", ["row", "source"])
def test_graph_loading_message_includes_pending_sources_with_an_already_observed_root(loading):
    store, revision, _ = bound_view()
    request = relationship_request(store.observation.connection)
    assert store.bind_relationships(revision, request)
    source = RelationshipSource(
        "pods",
        "team",
        RelationshipStatus.LOADING if loading == "source" else RelationshipStatus.READY,
        CollectionState(),
        "1",
        "",
    )
    root = relationship_row(
        request, RelationshipStatus.LOADING if loading == "row" else RelationshipStatus.READY
    )
    assert store.apply_relationships(
        revision, RelationshipSnapshot(request, (root,), (source,), 1, None)
    )
    assert store.observation.status is ViewStatus.LOADING
    assert "Loading references" in store.observation.message
    assert "incomplete/unavailable evidence" in store.observation.message


@pytest.mark.parametrize(
    "cause", ["forbidden", "partial_collection", "replaced", "cycle", "exact_get"]
)
def test_graph_message_distinguishes_incomplete_evidence_from_cycles_and_observed_exact_gets(cause):
    store, revision, _ = bound_view()
    request = relationship_request(store.observation.connection)
    request = replace(request, scope=replace(request.scope, mode=RelationshipMode.USED_BY))
    assert store.bind_relationships(revision, request)
    source = RelationshipSource(
        "pods",
        "team",
        RelationshipStatus.FORBIDDEN if cause == "forbidden" else RelationshipStatus.READY,
        CollectionState(complete=False, pages=1) if cause == "partial_collection" else None,
        None,
        "",
    )
    status = (
        RelationshipStatus.REPLACED
        if cause == "replaced"
        else RelationshipStatus.CYCLE
        if cause == "cycle"
        else RelationshipStatus.READY
    )
    assert store.apply_relationships(
        revision,
        RelationshipSnapshot(request, (relationship_row(request, status),), (source,), 1, None),
    )
    assert store.observation.status is ViewStatus.LIVE
    message = store.observation.message
    assert "usedby relationships · Observed references" in message
    assert ("incomplete/unavailable evidence" in message) == (
        cause in {"forbidden", "partial_collection", "replaced"}
    )
    assert "unused" not in message
