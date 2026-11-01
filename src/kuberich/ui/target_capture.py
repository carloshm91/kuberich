"""Capture one resource identity through narrow session and selection observations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ViewObservation, ViewStatus


@dataclass(frozen=True)
class TargetSelection:
    route: ViewRoute
    uid: str | None
    modal: bool = False


class CapturedResource[T](NamedTuple):
    client: T
    resource: ApiResource
    record: ResourceRecord
    target: ResourceTarget
    current: Callable[[], bool]


class TargetCapture[T]:
    def __init__(
        self,
        observe: Callable[[], ViewObservation],
        client: Callable[[], T | None],
        selection: Callable[[], TargetSelection],
        notice: Callable[[str], None],
        status: Callable[[str], None],
    ) -> None:
        self.observe, self.client, self.selection = observe, client, selection
        self.notice, self.status = notice, status

    def capture(self, uid: str | None = None) -> CapturedResource[T] | None:
        selected = self.selection()
        if selected.modal:
            return None
        if selected.route.kind is ViewKind.CONTEXTS:
            self.notice("Contexts are local configuration. Enter connects to the selected context.")
            return None
        view = self.observe()
        scope, snapshot, client = view.scope, view.snapshot, self.client()
        uid = uid if uid is not None else selected.uid
        if scope is None or snapshot is None or client is None or uid is None:
            self.notice("Select a connected resource before opening a viewer.")
            return None
        record = next((item for item in snapshot.items if item.uid == uid), None)
        if record is None:
            self.status("The selected target is stale; select the resource again.")
            return None
        target = ResourceTarget(
            scope.session,
            scope.resource.group,
            scope.resource.name,
            record.namespace,
            record.name,
            uid,
        )
        checked_snapshot, present, revision = snapshot, True, view.revision

        def current() -> bool:
            nonlocal checked_snapshot, present
            observation = self.observe()
            if (
                self.client() is not client
                or observation.scope != scope
                or observation.revision != revision
                or observation.snapshot is None
                or observation.status is ViewStatus.FAILED
            ):
                return False
            # A snapshot is immutable. Cache both presence and absence for that
            # exact observation while checking scope/client on every read.
            if observation.snapshot is not checked_snapshot:
                checked_snapshot = observation.snapshot
                present = any(item.uid == target.uid for item in checked_snapshot.items)
            return present

        return CapturedResource(client, scope.resource, record, target, current)
