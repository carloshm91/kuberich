"""Bounded sticky identity evidence for an already admitted Pod log read."""

from weakref import ReferenceType, ref

from kuberich.domain.resources import ResourceSnapshot
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import USABLE_CONNECTIONS, ResourceScope, ViewObservation, ViewStatus
from kuberich.domain.watches import EventType, WatchEvent
from kuberich.errors import AppError


class LogReadState:
    def __init__(self, scope: ResourceScope, revision: int, target: ResourceTarget) -> None:
        resource = scope.resource
        if (
            (resource.group, resource.version, resource.name, resource.kind, resource.namespaced)
            != ("", "v1", "pods", "Pod", True)
            or target.session != scope.session
            or (target.group, target.resource) != ("", "pods")
            or not target.uid
            or not target.namespace
            or (scope.namespace is not None and target.namespace != scope.namespace)
        ):
            raise AppError("A log read requires one captured Pod identity and resource scope.")
        self.scope, self.revision, self.target = scope, revision, target
        self._valid = True
        self._relisting = self._unknown = self._present = False
        self._anchor: ReferenceType[ResourceSnapshot] | None = None

    @property
    def current(self) -> bool:
        return self._valid

    @property
    def membership_unknown(self) -> bool:
        return self._valid and self._unknown

    def invalidate(self) -> None:
        self._valid = self._unknown = self._present = self._relisting = False
        self._anchor = None

    def observe(self, view: ViewObservation, *, event: WatchEvent | None = None) -> None:
        if not self._valid:
            return
        if (
            view.scope != self.scope
            or view.revision != self.revision
            or view.connection.identity != self.target.session
            or view.connection.state not in USABLE_CONNECTIONS
            or view.status is ViewStatus.FAILED
        ):
            self.invalidate()
            return
        record = event.record if event is not None else None
        same_name = record is not None and (record.namespace, record.name) == (
            self.target.namespace,
            self.target.name,
        )
        same_uid = record is not None and record.uid == self.target.uid
        if record is not None and (
            (
                same_uid
                and ((event is not None and event.type is EventType.DELETED) or not same_name)
            )
            or (
                same_name
                and not same_uid
                and event is not None
                and event.type is not EventType.DELETED
            )
        ):
            self.invalidate()
            return
        snapshot = view.snapshot
        if snapshot is None:
            self._anchor = None
            if view.status is ViewStatus.RELISTING:
                self._relisting = True
            if self._relisting and view.status in {
                ViewStatus.RELISTING,
                ViewStatus.LOADING,
                ViewStatus.STALE,
            }:
                self._unknown = True
            else:
                self.invalidate()
            return
        if snapshot.resource != self.scope.resource or snapshot.namespace != self.scope.namespace:
            self.invalidate()
            return
        if (
            event is not None
            and not same_name
            and not same_uid
            and self._present
            and not self._relisting
            and view.status is ViewStatus.LIVE
            and not snapshot.collection.limited
        ):
            # Accepted WatchState events cannot evict a different UID/name.
            # Keep only a weak identity anchor for metrics-only publications.
            self._anchor = ref(snapshot)
            return
        if self._anchor is None or self._anchor() is not snapshot:
            self._anchor = ref(snapshot)
            self._present = False
            for item in snapshot.items:
                identity = (item.namespace, item.name) == (self.target.namespace, self.target.name)
                if item.uid == self.target.uid:
                    if not identity:
                        self.invalidate()
                        return
                    self._present = True
                elif identity:
                    self.invalidate()
                    return
        if self._present:
            self._unknown = False
            if snapshot.collection.complete or view.status is ViewStatus.LIVE:
                self._relisting = False
        elif (
            self._relisting
            and view.status is ViewStatus.LOADING
            and not snapshot.collection.complete
            and not snapshot.collection.limited
        ):
            self._unknown = True
        else:
            self.invalidate()
