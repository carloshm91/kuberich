"""An idle Event watch is not a new sample and clock ownership retains no payload."""

import gc
import weakref
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from kuberich.domain.resources import CollectionState, ResourceSnapshot
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceScope, ViewObservation, ViewStatus
from kuberich.ui.event_source import EventSourceClock
from tests.support.events import event_resource

CORE = event_resource(modern=False)


def observation():
    scope = ResourceScope(SessionIdentity("owned", 1), CORE, "team")
    snapshot = ResourceSnapshot(CORE, "team", "source-1", ())
    return ViewObservation(revision=4, scope=scope, snapshot=snapshot, status=ViewStatus.LIVE)


def test_repaints_filters_and_quiet_watch_status_changes_preserve_actual_snapshot_time():
    now = datetime(2026, 11, 6, tzinfo=UTC)
    source = EventSourceClock(lambda: now)
    view = observation()
    first = source.capture(view)
    assert first.snapshot_seen_at == now
    now += timedelta(days=1)
    stale = source.capture(replace(view, status=ViewStatus.STALE))
    assert stale.snapshot_seen_at == first.snapshot_seen_at and stale.status is ViewStatus.STALE
    assert source.capture(view) == first
    updated = replace(view.snapshot, resource_version="source-2", collection=CollectionState(False))
    second = source.capture(replace(view, snapshot=updated))
    assert second.snapshot_seen_at == now and not second.collection.complete
    now += timedelta(minutes=1)
    switched = source.capture(
        replace(view, scope=replace(view.scope, session=SessionIdentity("owned", 2)))
    )
    assert switched.snapshot_seen_at == now


@pytest.mark.parametrize("missing", ["scope", "snapshot", "descriptor", "api", "namespace"])
def test_missing_or_inconsistent_sources_reset_the_anchor(missing):
    view = observation()
    source = EventSourceClock()
    assert source.capture(view) is not None
    if missing == "scope":
        view = replace(view, scope=None)
    elif missing == "snapshot":
        view = replace(view, snapshot=None)
    elif missing == "descriptor":
        view = replace(view, scope=replace(view.scope, resource=replace(CORE, version="v99")))
    elif missing == "api":
        view = replace(view, snapshot=replace(view.snapshot, resource=replace(CORE, version="v99")))
    else:
        view = replace(view, snapshot=replace(view.snapshot, namespace="other"))
    assert source.capture(view) is None
    assert source.capture(observation()) is not None


def test_anchor_does_not_keep_an_old_snapshot_or_its_payload_alive():
    view = observation()
    reference = weakref.ref(view.snapshot)
    source = EventSourceClock()
    state = source.capture(view)
    del view
    gc.collect()
    assert reference() is None
    assert state.scope.resource == CORE
    source.reset()
