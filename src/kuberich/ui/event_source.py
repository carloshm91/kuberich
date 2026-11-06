"""Timestamp one actual Events snapshot without retaining its payload."""

import weakref
from collections.abc import Callable
from datetime import UTC, datetime

from kuberich.domain.events import EventSourceState, event_descriptor_supported
from kuberich.domain.resources import ResourceSnapshot
from kuberich.domain.views import ResourceScope, ViewObservation


class EventSourceClock:
    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        self._snapshot: weakref.ReferenceType[ResourceSnapshot] | None = None
        self._scope: ResourceScope | None = None
        self._seen_at: datetime | None = None

    def reset(self) -> None:
        self._snapshot = None
        self._scope = None
        self._seen_at = None

    def capture(self, view: ViewObservation) -> EventSourceState | None:
        scope, snapshot = view.scope, view.snapshot
        if (
            scope is None
            or snapshot is None
            or not event_descriptor_supported(scope.resource)
            or scope.resource != snapshot.resource
            or scope.namespace != snapshot.namespace
        ):
            self.reset()
            return None
        if self._snapshot is None or self._snapshot() is not snapshot or self._scope != scope:
            self._snapshot = weakref.ref(snapshot)
            self._scope = scope
            self._seen_at = self.clock()
        assert self._seen_at is not None
        return EventSourceState(
            scope, view.revision, snapshot.collection, view.status, self._seen_at
        )
