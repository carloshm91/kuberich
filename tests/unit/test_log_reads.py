"""Live log identity survives unknown relists, never contrary membership evidence."""

import gc
import weakref
from dataclasses import replace

import pytest

from kuberich.domain.connections import ConnectionState, SessionObservation
from kuberich.domain.log_reads import LogReadState
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceScope, ViewObservation, ViewStatus
from kuberich.domain.watches import WatchState, watch_event
from kuberich.errors import AppError
from tests.support.pods import pod, snapshot


def admitted(*, all_namespaces=False):
    data = snapshot(pod("alpha"), pod("beta"))
    namespace = None if all_namespaces else "team"
    data = replace(data, namespace=namespace)
    session = SessionIdentity("log-lab", 3)
    scope = ResourceScope(session, data.resource, namespace)
    target = ResourceTarget(session, "", "pods", "team", "alpha", "owned-alpha")
    view = ViewObservation(
        revision=7,
        context=session.context,
        connection=SessionObservation(ConnectionState.CONNECTED, "Connected", session, namespace),
        scope=scope,
        status=ViewStatus.LIVE,
        snapshot=data,
    )
    state = LogReadState(scope, view.revision, target)
    state.observe(view)
    assert state.current and not state.membership_unknown
    return state, view


def without_target(view, *, complete=True, limited=False):
    return replace(
        view.snapshot,
        items=tuple(item for item in view.snapshot.items if item.uid != "owned-alpha"),
        collection=CollectionState(complete=complete, limited=limited, pages=1),
    )


def resource_event(view, kind, *, name="alpha", uid="owned-alpha", namespace="team"):
    return watch_event(
        view.scope.resource,
        {"type": kind, "object": pod(name, uid=uid, namespace=namespace)},
        view.scope.namespace,
    )


@pytest.mark.parametrize("all_namespaces", [False, True])
def test_relist_retries_and_partial_pages_preserve_an_admitted_identity(all_namespaces):
    state, view = admitted(all_namespaces=all_namespaces)
    for _ in range(3):
        state.observe(replace(view, status=ViewStatus.RELISTING, snapshot=None))
        assert state.current and state.membership_unknown
        for status in (ViewStatus.STALE, ViewStatus.LOADING):
            state.observe(replace(view, status=status, snapshot=None))
            assert state.current and state.membership_unknown
        state.observe(
            replace(view, status=ViewStatus.LOADING, snapshot=without_target(view, complete=False))
        )
        assert state.current and state.membership_unknown
        state.observe(view)
        assert state.current and not state.membership_unknown


@pytest.mark.parametrize("status", [ViewStatus.LIVE, ViewStatus.LOADING, ViewStatus.STALE])
def test_missing_or_incomplete_membership_without_a_relist_is_not_permission(status):
    state, view = admitted()
    state.observe(replace(view, status=status, snapshot=None))
    assert not state.current and not state.membership_unknown
    state.observe(view)
    assert not state.current


@pytest.mark.parametrize("limited", [False, True])
@pytest.mark.parametrize("relisting", [False, True])
def test_complete_or_limited_absence_is_sticky_even_if_a_later_frame_contains_the_uid(
    limited, relisting
):
    state, view = admitted()
    if relisting:
        state.observe(replace(view, status=ViewStatus.RELISTING, snapshot=None))
    state.observe(
        replace(
            view,
            status=ViewStatus.LOADING if relisting else ViewStatus.LIVE,
            snapshot=without_target(view, complete=not limited, limited=limited),
        )
    )
    assert not state.current and not state.membership_unknown
    state.observe(view)
    state.observe(replace(view, status=ViewStatus.RELISTING, snapshot=None))
    assert not state.current and not state.membership_unknown


def test_nonlimited_partial_absence_without_relist_provenance_also_revokes():
    state, view = admitted()
    state.observe(
        replace(view, status=ViewStatus.LOADING, snapshot=without_target(view, complete=False))
    )
    assert not state.current


def test_a_present_identity_in_a_limited_collection_keeps_existing_membership_semantics():
    state, view = admitted()
    limited = replace(view.snapshot, collection=CollectionState(complete=False, limited=True))
    state.observe(replace(view, snapshot=limited))
    assert state.current and not state.membership_unknown


def test_a_present_nonfinal_page_does_not_end_the_refresh_epoch_before_completion():
    state, view = admitted()
    state.observe(replace(view, status=ViewStatus.RELISTING, snapshot=None))
    unfinished = replace(view.snapshot, collection=CollectionState(complete=False, pages=2))
    state.observe(replace(view, status=ViewStatus.LOADING, snapshot=unfinished))
    assert state.current and not state.membership_unknown
    state.observe(replace(view, status=ViewStatus.STALE, snapshot=None))
    assert state.current and state.membership_unknown
    state.observe(view)
    assert state.current and not state.membership_unknown


@pytest.mark.parametrize("contradiction", ["replacement", "name", "namespace"])
def test_contradictory_identity_on_an_early_page_is_terminal(contradiction):
    state, view = admitted(all_namespaces=True)
    state.observe(replace(view, status=ViewStatus.RELISTING, snapshot=None))
    payload = pod(
        "renamed" if contradiction == "name" else "alpha",
        uid="replacement-uid" if contradiction == "replacement" else "owned-alpha",
        namespace="other" if contradiction == "namespace" else "team",
    )
    record = resource_record(view.scope.resource, payload, None)
    data = replace(
        view.snapshot,
        items=(record,),
        collection=CollectionState(complete=False, pages=1),
    )
    state.observe(replace(view, status=ViewStatus.LOADING, snapshot=data))
    assert not state.current and not state.membership_unknown
    state.observe(view)
    assert not state.current


@pytest.mark.parametrize("kind", ["DELETED", "MODIFIED", "ADDED"])
def test_explicit_delete_or_same_name_replacement_cannot_be_hidden_by_coalescing(kind):
    state, view = admitted()
    change = resource_event(view, kind, uid="owned-alpha" if kind == "DELETED" else "new-uid")
    state.observe(view, event=change)
    state.observe(view)
    assert not state.current


def test_same_uid_under_another_namespace_in_an_event_is_inconsistent_identity():
    state, view = admitted(all_namespaces=True)
    state.observe(view, event=resource_event(view, "MODIFIED", namespace="other"))
    assert not state.current


def test_accepted_delete_of_an_old_incarnation_preserves_the_current_uid():
    state, view = admitted()
    change = resource_event(view, "DELETED", uid="old-incarnation-uid")
    watch = WatchState(view.snapshot)
    assert watch.apply(change)
    data = watch.snapshot
    assert any(item.uid == state.target.uid for item in data.items)
    state.observe(replace(view, snapshot=data), event=change)
    assert state.current and not state.membership_unknown


@pytest.mark.parametrize("limited", [False, True])
def test_old_incarnation_delete_does_not_hide_authoritative_absence(limited):
    state, view = admitted()
    state.observe(
        replace(view, snapshot=without_target(view, complete=not limited, limited=limited)),
        event=resource_event(view, "DELETED", uid="old-incarnation-uid"),
    )
    assert not state.current
    state.observe(view)
    assert not state.current


@pytest.mark.parametrize("kind", ["ADDED", "MODIFIED", "DELETED"])
def test_an_unrelated_namespace_or_uid_event_does_not_revoke_the_target(kind):
    state, view = admitted(all_namespaces=True)
    state.observe(view, event=resource_event(view, kind, uid="other-uid", namespace="other"))
    assert state.current
    state.observe(view, event=resource_event(view, kind, name="beta", uid="owned-beta"))
    assert state.current


def test_limited_absence_still_revokes_with_an_unrelated_event_hint():
    state, view = admitted()
    state.observe(
        replace(view, snapshot=without_target(view, complete=False, limited=True)),
        event=resource_event(view, "MODIFIED", name="beta", uid="owned-beta"),
    )
    assert not state.current


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "namespace",
        "query",
        "revision",
        "connection",
        "snapshot-resource",
        "snapshot-namespace",
        "failed",
    ],
)
def test_binding_or_terminal_failure_revokes_before_any_possible_restoration(change):
    state, view = admitted()
    if change == "scope":
        updated = replace(view, scope=None)
    elif change == "namespace":
        updated = replace(view, scope=replace(view.scope, namespace="other"))
    elif change == "query":
        updated = replace(view, scope=replace(view.scope, query=ResourceQuery("app=other")))
    elif change == "revision":
        updated = replace(view, revision=view.revision + 1)
    elif change == "connection":
        updated = replace(
            view, connection=replace(view.connection, identity=SessionIdentity("log-lab", 3))
        )
    elif change == "snapshot-resource":
        updated = replace(
            view,
            snapshot=replace(view.snapshot, resource=replace(view.scope.resource, name="services")),
        )
    elif change == "snapshot-namespace":
        updated = replace(view, snapshot=replace(view.snapshot, namespace="other"))
    else:
        updated = replace(view, status=ViewStatus.FAILED)
    state.observe(updated)
    state.observe(view)
    assert not state.current and not state.membership_unknown


@pytest.mark.parametrize("connection", list(ConnectionState))
def test_only_usable_connection_states_can_keep_a_read(connection):
    state, view = admitted()
    state.observe(replace(view, connection=replace(view.connection, state=connection)))
    assert state.current is (connection in USABLE_CONNECTIONS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("group", "apps"),
        ("version", "v2"),
        ("name", "services"),
        ("kind", "Service"),
        ("namespaced", False),
    ],
)
def test_non_core_pod_descriptors_cannot_admit_a_log_read(field, value):
    state, view = admitted(all_namespaces=True)
    scope = replace(view.scope, resource=replace(view.scope.resource, **{field: value}))
    with pytest.raises(AppError):
        LogReadState(scope, view.revision, state.target)


@pytest.mark.parametrize(
    "field,value",
    [
        ("session", None),
        ("group", "apps"),
        ("resource", "services"),
        ("namespace", None),
        ("namespace", "other"),
    ],
)
def test_captured_target_must_match_the_pod_scope(field, value):
    state, view = admitted()
    target = replace(
        state.target, **{field: SessionIdentity("log-lab", 3) if field == "session" else value}
    )
    with pytest.raises(AppError):
        LogReadState(view.scope, view.revision, target)


def test_republication_and_unrelated_valid_events_do_not_rescan_log_rows():
    class CountedRecords(tuple):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    state, view = admitted()
    records = CountedRecords(view.snapshot.items)
    updated = replace(view, snapshot=replace(view.snapshot, items=records))
    state.observe(updated)
    for _ in range(5):
        state.observe(updated)
        assert state.current
    assert records.iterations == 1
    latest = CountedRecords(view.snapshot.items)
    updated = replace(view, snapshot=replace(view.snapshot, items=latest))
    state.observe(updated, event=resource_event(view, "MODIFIED", name="beta", uid="owned-beta"))
    state.observe(updated)
    assert state.current and latest.iterations == 0


def test_no_resource_collection_is_retained_by_the_read_state():
    state, view = admitted()
    reference = weakref.ref(view.snapshot)
    del view
    gc.collect()
    assert reference() is None
    assert state.current
    state.invalidate()
    state.invalidate()
    assert not state.current and not state.membership_unknown
