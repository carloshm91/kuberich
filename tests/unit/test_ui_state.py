"""Frozen semantic application state snapshot and unmounted command routing."""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest

from kuberich.config.catalog import Entry, KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionProblem, ConnectionState, SessionObservation
from kuberich.domain.resources import api_resource
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewObservation, ViewStatus, ViewStore
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.ui.app import KubeRichApp
from kuberich.ui.state import AppState, app_state
from tests.support.resources import descriptor, item
from tests.support.watches import snapshot


def test_app_state_defaults_and_immutability() -> None:
    state = AppState()
    assert state.view_kind == "pods"
    assert state.context is None
    assert state.namespace is None
    assert state.scope is None
    assert state.selected is None
    assert state.connection is ConnectionState.DISCONNECTED
    assert state.status is ViewStatus.DISCONNECTED

    with pytest.raises(FrozenInstanceError):
        state.view_kind = "namespaces"  # type: ignore[misc]


def test_app_state_maps_disconnected_connecting_and_connected_observations() -> None:
    store = ViewStore()
    disconnected = app_state("pods", store.observation)
    assert disconnected == AppState(
        view_kind="pods",
        context=None,
        namespace=None,
        scope=None,
        selected=None,
        connection=ConnectionState.DISCONNECTED,
        status=ViewStatus.DISCONNECTED,
    )

    revision = store.begin("owned")
    connecting = app_state("namespaces", store.observation, selected="ns-team")
    assert connecting == AppState(
        view_kind="namespaces",
        context="owned",
        namespace=None,
        scope=None,
        selected="ns-team",
        connection=ConnectionState.CONNECTING,
        status=ViewStatus.CONNECTING,
    )

    identity = SessionIdentity("owned", 1)
    connection = SessionObservation(
        ConnectionState.CONNECTED,
        "Connected",
        identity,
        "team",
    )
    assert store.connected(revision, connection)
    scope = ResourceScope(identity, snapshot().resource, "team")
    assert store.bind(revision, scope)
    assert store.apply(revision, scope, SyncUpdate(SyncStatus.LIVE, snapshot(item())))

    live = app_state("pods", store.observation, selected="pod-uid-1")
    assert live == AppState(
        view_kind="pods",
        context="owned",
        namespace="team",
        scope=scope,
        selected="pod-uid-1",
        connection=ConnectionState.CONNECTED,
        status=ViewStatus.LIVE,
    )
    assert disconnected != connecting
    assert connecting != live


def test_app_state_preserves_cluster_scope_and_failure_states() -> None:
    identity = SessionIdentity("prod", 2)
    nodes = api_resource("v1", descriptor("nodes", namespaced=False, kind="Node"))
    scope = ResourceScope(identity, nodes, None)
    observation = ViewObservation(
        revision=3,
        context="prod",
        connection=SessionObservation(
            ConnectionState.LIMITED,
            "Namespace list forbidden",
            identity,
            None,
        ),
        scope=scope,
        status=ViewStatus.FAILED,
        problem=ConnectionProblem(ConnectionState.LIMITED, "403 Forbidden"),
    )
    state = app_state("nodes", observation, selected="node-1")
    assert state.view_kind == "nodes"
    assert state.context == "prod"
    assert state.namespace is None
    assert state.scope == scope
    assert state.selected == "node-1"
    assert state.connection is ConnectionState.LIMITED
    assert state.status is ViewStatus.FAILED


@pytest.mark.asyncio
async def test_unmounted_app_state_is_lazy_non_mutating_and_ignores_unmounted_run_command(
    tmp_path,
) -> None:
    env = {"KUBECONFIG": str(tmp_path / "custom-config"), "TMUX": "1"}
    work_dir = tmp_path / "workspace"
    work_dir.mkdir()
    catalog = KubeCatalog(
        current="owned",
        contexts={"owned": Entry({"cluster": "owned", "user": "owned"}, tmp_path)},
    )
    app = KubeRichApp(
        Settings(),
        logging.getLogger("kuberich.test.state"),
        catalog=catalog,
        environment=env,
        directory=work_dir,
    )
    env["KUBECONFIG"] = str(tmp_path / "mutated-later")

    first = app.state
    second = app.state
    assert first == second
    assert first is not second
    assert first == AppState(
        view_kind="pods",
        context=None,
        namespace=None,
        scope=None,
        selected=None,
        connection=ConnectionState.DISCONNECTED,
        status=ViewStatus.DISCONNECTED,
    )
    assert app.interactions.history.entries == []

    await app.run_command("ctx")
    after_ctx = app.state
    assert after_ctx == first
    assert after_ctx is not first
    assert app.interactions.history.entries == []
