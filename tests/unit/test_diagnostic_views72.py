"""Diagnostics route/store/history boundaries preserve scope and exact session identity."""

import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest

from kuberich.domain.cluster_diagnostics import (
    DiagnosticBookmark,
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticStatus,
    diagnose_record,
)
from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.metrics import MetricsSnapshot
from kuberich.domain.navigation import NavigationHistory, NavigationState
from kuberich.domain.pulse import PulseScope
from kuberich.domain.resources import CollectionState
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_actions import TABLE_ACTIONS, ViewState, action_available
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ResourceScope, ResourceSelection, ViewStatus, ViewStore
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.errors import AppError
from kuberich.services.diagnostic_workspace import DiagnosticWorkspace
from tests.support.authorization import auth_request
from tests.support.diagnostic_native import NOW, PODS, record, ref, snapshot, source
from tests.support.watches import snapshot as resource_snapshot
from tests.unit.test_views import relationship_request


def diagnostic_store(
    header="team", *, root=None, collection="team", state=ConnectionState.CONNECTED
):
    session = SessionIdentity("synthetic", 1)
    store = ViewStore()
    revision = store.begin(
        session.context, SessionObservation(state, "Owned connection", session, header)
    )
    request = DiagnosticRequest(DiagnosticScope(session, collection, root), 1)
    return store, revision, request


def test_route_is_immutable_non_resource_and_rejects_a_fabricated_resource_selection():
    route = ViewRoute.diagnostics()
    assert route.kind is ViewKind.DIAGNOSTICS
    assert route.display_key == "diagnostics" and route.selection is route.resource_name is None
    with pytest.raises(FrozenInstanceError):
        route.kind = ViewKind.PODS
    for selection in [
        ResourceSelection(),
        ResourceSelection("diagnostics"),
        ResourceSelection("widgets", "synthetic.test", server_columns=True),
    ]:
        with pytest.raises(AppError, match="no API resource selection"):
            ViewRoute(ViewKind.DIAGNOSTICS, selection)
    with pytest.raises(AppError, match="known view kind"):
        ViewRoute("diagnostics")
    with pytest.raises(AppError, match="canonical resource selection"):
        ViewRoute(ViewKind.DIAGNOSTICS, object())


@pytest.mark.parametrize("header", [None, "header-a", "root-b"])
@pytest.mark.parametrize("state", [ConnectionState.CONNECTED, ConnectionState.LIMITED])
def test_root_collection_namespace_is_independent_from_header_namespace(header, state):
    root = ref(namespace="root-b")
    store, revision, request = diagnostic_store(header, root=root, collection="root-b", state=state)
    assert store.bind_diagnostics(revision, request)
    observation = store.observation
    assert observation.connection.namespace == header
    assert observation.diagnostics.request.scope.namespace == "root-b"
    assert observation.diagnostics.request.scope.root == root
    assert observation.status is ViewStatus.LOADING
    assert observation.message == "Diagnostics · Collecting evidence"
    assert (
        observation.scope
        is observation.snapshot
        is observation.metrics
        is observation.authorization
        is observation.relationships
        is observation.pulse
        is None
    )


@pytest.mark.parametrize(
    "header,collection", [(None, "team"), ("team", None), ("header-a", "root-b")]
)
def test_overview_collection_must_match_the_current_header(header, collection):
    store, revision, request = diagnostic_store(header, collection=collection)
    initial = store.observation
    with pytest.raises(AppError, match="active connection"):
        store.bind_diagnostics(revision, request)
    assert store.observation is initial


@pytest.mark.parametrize("difference", ["connection", "generation", "context", "unusable"])
def test_rebind_rejects_stale_full_session_or_unusable_connection(difference):
    store, revision, request = diagnostic_store()
    session = request.scope.session
    if difference == "connection":
        session = SessionIdentity(session.context, session.generation)
    elif difference == "generation":
        session = replace(session, generation=session.generation + 1)
    elif difference == "context":
        session = replace(session, context="other")
    else:
        store.connected(
            revision, replace(store.observation.connection, state=ConnectionState.AUTH_ERROR)
        )
    candidate = replace(request, scope=replace(request.scope, session=session))
    with pytest.raises(AppError, match="active connection"):
        store.bind_diagnostics(revision, candidate)


def test_bind_apply_guards_revision_request_and_current_client_session_without_changing_data():
    store, revision, request = diagnostic_store()
    initial = store.observation
    value = snapshot(request)
    assert not store.bind_diagnostics(revision - 1, request)
    assert not store.apply_diagnostics(revision, value)
    assert store.observation is initial
    assert store.bind_diagnostics(revision, request)
    bound = store.observation
    assert not store.apply_diagnostics(revision - 1, value)
    assert not store.apply_diagnostics(
        revision, replace(value, request=replace(request, revision=2))
    )
    assert not store.apply_diagnostics(
        revision,
        replace(
            value,
            request=replace(
                request, scope=replace(request.scope, session=SessionIdentity("synthetic", 1))
            ),
        ),
    )
    assert store.observation is bound
    assert store.apply_diagnostics(revision, value)
    current = store.observation
    assert current.status is ViewStatus.LIVE
    store.connected(
        revision, replace(current.connection, identity=replace(request.scope.session, generation=2))
    )
    assert not store.apply_diagnostics(revision, value)
    store.connected(revision, replace(current.connection, identity=SessionIdentity("synthetic", 1)))
    assert not store.apply_diagnostics(revision, value)
    store.connected(revision, replace(current.connection, state=ConnectionState.AUTH_ERROR))
    assert not store.apply_diagnostics(revision, value)


@pytest.mark.parametrize(
    "outcome",
    [
        "loading",
        "no-sources",
        "empty",
        "findings",
        "partial",
        "incomplete",
        "forbidden",
        "cancelled",
    ],
)
def test_diagnostic_messages_report_observations_without_claiming_health(outcome):
    store, revision, request = diagnostic_store()
    assert store.bind_diagnostics(revision, request)
    value = snapshot(request)
    if outcome == "loading":
        value = replace(value, collecting=True)
        expected = "Diagnostics · Collecting evidence"
    elif outcome == "no-sources":
        value = replace(value, sources=())
        expected = "Diagnostics · No source evidence available"
    elif outcome == "findings":
        findings = diagnose_record(
            PODS, record(status={"conditions": [{"type": "Ready", "status": "False"}]}), NOW
        )
        value = replace(value, findings=findings)
        expected = "Diagnostics · Findings: 1"
    else:
        expected = "Diagnostics · No failure evidence found in the collected sources"
        if outcome != "empty":
            status = {
                "partial": DiagnosticStatus.PARTIAL,
                "forbidden": DiagnosticStatus.FORBIDDEN,
                "cancelled": DiagnosticStatus.CANCELLED,
                "incomplete": DiagnosticStatus.READY,
            }[outcome]
            value = replace(
                value,
                sources=(
                    replace(
                        source(status=status),
                        collection=CollectionState(False, True)
                        if outcome == "incomplete"
                        else None,
                    ),
                ),
            )
            expected += " · partial/unavailable evidence"
    assert store.apply_diagnostics(revision, value)
    assert store.observation.message == expected
    assert store.observation.status is (ViewStatus.LOADING if value.collecting else ViewStatus.LIVE)
    assert "healthy" not in store.observation.message.casefold()


@pytest.mark.parametrize("other", ["resource", "pulse", "relationships", "authorization"])
def test_diagnostic_binding_and_other_native_modes_retire_each_others_observations(other):
    store, revision, request = diagnostic_store()
    connection = store.observation.connection

    def bind_other():
        if other == "resource":
            scope = ResourceScope(request.scope.session, resource_snapshot().resource, "team")
            assert store.bind(revision, scope)
            assert store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, resource_snapshot()))
            store.observation = replace(store.observation, metrics=MetricsSnapshot())
        elif other == "pulse":
            assert store.bind_pulse(revision, PulseScope(request.scope.session, "team"))
        elif other == "relationships":
            assert store.bind_relationships(revision, relationship_request(connection))
        else:
            assert store.bind_authorization(
                revision, replace(auth_request(), session=request.scope.session)
            )

    bind_other()
    assert store.bind_diagnostics(revision, request)
    view = store.observation
    assert (
        view.scope
        is view.snapshot
        is view.metrics
        is view.pulse
        is view.relationships
        is view.authorization
        is None
    )
    assert store.apply_diagnostics(revision, snapshot(request))
    bind_other()
    assert store.observation.diagnostics is None
    assert not store.apply_diagnostics(revision, snapshot(request))


def test_new_connection_intent_and_disconnect_clear_diagnostics_before_recollection():
    store, revision, request = diagnostic_store()
    assert store.bind_diagnostics(revision, request)
    new_revision = store.begin("other")
    assert store.observation.diagnostics is None and new_revision > revision
    assert not store.apply_diagnostics(revision, snapshot(request))
    store.disconnect()
    assert (
        store.observation.diagnostics is None
        and store.observation.status is ViewStatus.DISCONNECTED
    )


@pytest.mark.asyncio
async def test_cancel_result_requires_explicit_new_request_binding_before_publication():
    store, revision, initial = diagnostic_store()
    workspace = DiagnosticWorkspace()
    request = workspace.prepare(initial.scope)
    assert store.bind_diagnostics(revision, request)
    entered = asyncio.Event()

    async def collect(request, publish):
        publish(
            snapshot(request, sources=(source(status=DiagnosticStatus.LOADING),), collecting=True)
        )
        entered.set()
        await asyncio.Event().wait()
        return snapshot(request)

    workspace.start(request, collect, lambda value: store.apply_diagnostics(revision, value))
    await entered.wait()
    cancelled = await workspace.cancel()
    assert (
        cancelled.request != request and cancelled.sources[0].status is DiagnosticStatus.CANCELLED
    )
    assert not store.apply_diagnostics(revision, cancelled)
    assert store.bind_diagnostics(revision, cancelled.request)
    assert store.apply_diagnostics(revision, cancelled)
    assert not store.apply_diagnostics(revision, snapshot(request))
    assert "partial/unavailable evidence" in store.observation.message


def test_history_restores_header_root_selection_and_viewport_without_carrying_report_bytes():
    bookmark = DiagnosticBookmark("root-b", ref(namespace="root-b"))
    diagnostics = NavigationState(
        "synthetic",
        "header-a",
        resource="diagnostics",
        diagnostics=bookmark,
        query="literal [red] filter",
        column="severity",
        descending=True,
        selected="finding-key",
        index=4,
        x=9,
        y=21,
        top="source-key",
        top_offset=2,
    )
    opened = replace(
        diagnostics,
        resource="pods",
        diagnostics=None,
        namespace="root-b",
        expected_uid="opened-uid",
    )
    history = NavigationHistory()
    history.visit(diagnostics)
    restored = history.move(opened)
    assert restored == diagnostics and restored.namespace == "header-a"
    assert restored.diagnostics.root.namespace == "root-b"
    assert restored.diagnostics.namespace == "root-b"
    assert restored.selected == "finding-key" and restored.top_offset == 2
    assert not hasattr(restored.diagnostics, "selected") and not hasattr(
        restored.diagnostics, "findings"
    )
    assert history.move(restored, forward=True) == opened


@pytest.mark.parametrize(
    "action", sorted(TABLE_ACTIONS | {"views", "retry", "annotate", "cleanup_pods"})
)
def test_diagnostic_rows_offer_navigation_and_explicit_open_without_resource_effects(action):
    allowed = action in {
        "focus_filter",
        "focus_command",
        "history_back",
        "history_forward",
        "open_relationship",
        "retry",
    }
    assert action_available(action, ViewState("diagnostics")) is allowed
    if action in TABLE_ACTIONS:
        assert not action_available(action, ViewState("diagnostics", modal=True))
        assert not action_available(action, ViewState("diagnostics", typing=True))


@pytest.mark.parametrize(
    "resource",
    [
        "pods",
        "deployments",
        "replicasets",
        "statefulsets",
        "daemonsets",
        "jobs",
        "cronjobs",
        "replicationcontrollers",
    ],
)
def test_diagnose_action_requires_an_actual_supported_workload_view(resource):
    assert action_available("diagnose", ViewState(resource))
    assert not action_available("diagnose", ViewState(resource, generic=True))
    assert not action_available("diagnose", ViewState(resource, modal=True))
    assert not action_available("diagnose", ViewState(resource, typing=True))
