"""Helm observations remain local, generation-bound and honest after failed refreshes."""

from dataclasses import replace

import pytest

from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.helm import (
    HelmDriver,
    HelmList,
    HelmProblem,
    HelmRelease,
    HelmReleaseKey,
    HelmRequest,
    HelmScope,
    HelmSnapshot,
)
from kuberich.domain.pulse import PulseScope
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewStatus, ViewStore
from kuberich.errors import AppError
from tests.support.watches import snapshot


def connected(namespace="team"):
    store = ViewStore()
    connection = SessionObservation(
        ConnectionState.CONNECTED, "Connected", SessionIdentity("owned", 1), namespace
    )
    revision = store.begin("owned", connection)
    request = HelmRequest(HelmScope(connection.identity, namespace, HelmDriver.SECRET), 1)
    return store, revision, request


def listing(complete=True):
    release = HelmRelease(
        HelmReleaseKey("team", "demo"), 1, "deployed", "owned-0.1.0", "1", "2026-11-09T00:00:00Z"
    )
    return HelmList((release,), complete)


@pytest.mark.parametrize("namespace", ["team", None])
def test_native_helm_has_no_resource_authority_or_pod_data(namespace):
    store, revision, request = connected(namespace)
    assert store.bind_helm(revision, request)
    observation = store.observation
    assert observation.scope is observation.snapshot is observation.metrics is None
    assert observation.helm.request == request
    assert observation.status is ViewStatus.LOADING
    assert observation.message == "Helm · Loading releases"
    result = HelmSnapshot(request, listing(), False, None)
    assert store.apply_helm(revision, result)
    assert store.observation.helm is result
    assert store.observation.status is ViewStatus.LIVE
    assert store.observation.message == "Helm · 1 releases"


@pytest.mark.parametrize("with_rows", [False, True])
def test_failed_optional_tool_read_is_feature_local_and_retained_rows_are_stale(with_rows):
    store, revision, request = connected()
    store.bind_helm(revision, request)
    problem = HelmProblem("missing-tool", "Install a supported Helm CLI to use this view.")
    result = HelmSnapshot(request, listing() if with_rows else None, False, problem)
    assert store.apply_helm(revision, result)
    assert store.observation.problem is None
    assert store.observation.connection.state is ConnectionState.CONNECTED
    assert store.observation.status is (ViewStatus.STALE if with_rows else ViewStatus.LIVE)
    assert ("Stale releases" in store.observation.message) is with_rows
    assert ("Helm unavailable" in store.observation.message) is (not with_rows)
    assert str(problem) in store.observation.message


@pytest.mark.parametrize(
    "data, message",
    [
        (None, "No release data available"),
        (HelmList((), True), "0 releases"),
        (listing(False), "INCOMPLETE"),
    ],
)
def test_empty_missing_and_bounded_collections_are_distinct(data, message):
    store, revision, request = connected()
    store.bind_helm(revision, request)
    store.apply_helm(revision, HelmSnapshot(request, data, False, None))
    assert message in store.observation.message


@pytest.mark.parametrize(
    "change", ["revision", "request", "identity", "namespace", "state", "route"]
)
def test_late_results_cannot_repopulate_an_obsolete_or_different_view(change):
    store, revision, request = connected()
    store.bind_helm(revision, request)
    result = HelmSnapshot(request, listing(), False, None)
    if change == "revision":
        store.begin("owned", store.observation.connection)
    elif change == "request":
        result = replace(result, request=replace(request, generation=2))
    elif change == "identity":
        store.connected(
            revision, replace(store.observation.connection, identity=SessionIdentity("owned", 2))
        )
    elif change == "namespace":
        store.connected(revision, replace(store.observation.connection, namespace=None))
    elif change == "state":
        store.connected(
            revision, replace(store.observation.connection, state=ConnectionState.AUTH_ERROR)
        )
    else:
        store.bind_pulse(revision, PulseScope(request.scope.session, "team"))
    before = store.observation
    assert not store.apply_helm(revision, result)
    assert store.observation is before


@pytest.mark.parametrize("change", ["revision", "identity", "namespace", "state"])
def test_binding_requires_a_current_usable_header_scope(change):
    store, revision, request = connected()
    if change == "revision":
        assert not store.bind_helm(revision + 1, request)
        return
    if change == "identity":
        request = replace(
            request, scope=replace(request.scope, session=SessionIdentity("owned", 2))
        )
    elif change == "namespace":
        request = replace(request, scope=replace(request.scope, namespace=None))
    else:
        store.connected(
            revision, replace(store.observation.connection, state=ConnectionState.API_ERROR)
        )
    with pytest.raises(AppError, match="Helm scope"):
        store.bind_helm(revision, request)
    assert store.observation.helm is None


def test_resource_route_departure_drops_helm_data_and_failed_results():
    store, revision, request = connected()
    store.bind_helm(revision, request)
    store.apply_helm(revision, HelmSnapshot(request, listing(), False, None))
    store.bind(revision, ResourceScope(request.scope.session, snapshot().resource, "team"))
    assert store.observation.helm is None
    assert not store.apply_helm(revision, HelmSnapshot(request, listing(), False, None))
