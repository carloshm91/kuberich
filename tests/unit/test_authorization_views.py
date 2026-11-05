"""Request isolation and visible authorization states in the critical ViewStore."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.authorization import (
    AccessReview,
    AuthorizationSnapshot,
    EvidenceStatus,
    IdentityReview,
    RbacSnapshot,
    ReviewDecision,
    RulesReview,
)
from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.pulse import PulseScope
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewStatus, ViewStore
from kuberich.errors import AppError
from tests.support.authorization import auth_request
from tests.support.resources import pod_resource
from tests.unit.test_views import relationship_request


def connected_store():
    request = auth_request()
    store = ViewStore()
    revision = store.begin(request.session.context)
    store.connected(
        revision,
        SessionObservation(ConnectionState.CONNECTED, "Connected", request.session, "other"),
    )
    return store, revision, request


def test_request_scope_is_independent_from_header_and_previous_views_are_cleared():
    store, revision, request = connected_store()
    assert store.bind_authorization(revision, request)
    observation = store.observation
    assert observation.authorization.request == request
    assert observation.connection.namespace == "other"
    assert observation.status is ViewStatus.LOADING
    assert (
        observation.scope
        is observation.snapshot
        is observation.pulse
        is observation.relationships
        is observation.metrics
        is None
    )
    assert observation.message == "Authorization · Collecting current evidence"
    complete = replace(observation.authorization, collecting=False)
    assert store.apply_authorization(revision, complete)
    assert store.observation.status is ViewStatus.LIVE
    assert store.observation.message == "Authorization · Observed evidence"
    review = AccessReview(
        request, ReviewDecision.UNKNOWN, EvidenceStatus.FORBIDDEN, "Unknown", (), datetime.now(UTC)
    )
    assert store.apply_authorization(revision, replace(complete, review=review))
    assert store.observation.message == "Authorization review · unknown · forbidden"


def test_stale_bind_apply_and_unbound_apply_do_not_change_current_observation():
    store, revision, request = connected_store()
    initial = store.observation
    snapshot = AuthorizationSnapshot(request, None, None, None, None, None, False)
    assert not store.bind_authorization(revision - 1, request)
    assert not store.apply_authorization(revision, snapshot)
    assert store.observation is initial
    assert store.bind_authorization(revision, request)
    bound = store.observation
    assert not store.apply_authorization(revision - 1, snapshot)
    assert not store.apply_authorization(
        revision, replace(snapshot, request=replace(request, revision=2))
    )
    assert store.observation is bound
    store.disconnect()
    assert store.observation.authorization is None


@pytest.mark.parametrize(
    "state,identity",
    [
        (ConnectionState.AUTH_ERROR, None),
        (ConnectionState.CONNECTED, SessionIdentity("obsolete", 9)),
    ],
)
def test_invalid_connection_cannot_bind_authorization(state, identity):
    store, revision, request = connected_store()
    store.observation = replace(
        store.observation,
        connection=replace(store.observation.connection, state=state, identity=identity),
    )
    with pytest.raises(AppError):
        store.bind_authorization(revision, request)


@pytest.mark.parametrize("evidence", ["identity", "review", "rules", "rbac"])
def test_each_nested_evidence_record_must_belong_to_exact_bound_request(evidence):
    store, revision, request = connected_store()
    store.bind_authorization(revision, request)
    other = replace(request, revision=2)
    now = datetime.now(UTC)
    values = {
        "identity": IdentityReview(other, None, EvidenceStatus.FORBIDDEN, (), now),
        "review": AccessReview(
            other, ReviewDecision.UNKNOWN, EvidenceStatus.FAILED, "Unknown", (), now
        ),
        "rules": RulesReview(other, (), True, EvidenceStatus.UNAVAILABLE, (), now),
        "rbac": RbacSnapshot(other, (), (), (), (), 0, now),
    }
    with pytest.raises(AppError):
        store.apply_authorization(
            revision, replace(store.observation.authorization, **{evidence: values[evidence]})
        )
    owned = replace(values[evidence], request=request)
    assert store.apply_authorization(
        revision, replace(store.observation.authorization, **{evidence: owned})
    )


@pytest.mark.parametrize("view", ["resource", "pulse", "relationships"])
def test_every_native_binding_retires_authorization(view):
    store, revision, request = connected_store()
    store.bind_authorization(revision, request)
    connection = store.observation.connection
    if view == "resource":
        assert store.bind(
            revision, ResourceScope(request.session, pod_resource(), connection.namespace)
        )
    elif view == "pulse":
        assert store.bind_pulse(revision, PulseScope(request.session, connection.namespace))
    else:
        assert store.bind_relationships(
            revision, relationship_request(connection, root_namespace="other")
        )
    assert store.observation.authorization is None


def test_new_begin_removes_completed_answer_even_before_connection_ready():
    store, revision, request = connected_store()
    store.bind_authorization(revision, request)
    store.begin("new")
    assert store.observation.authorization is None


def test_resource_binding_keeps_its_existing_explicit_boolean_column_boundary():
    from kuberich.domain.views import ResourceSelection

    with pytest.raises(AppError, match="boolean"):
        ResourceSelection(server_columns=1)
