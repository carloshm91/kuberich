"""Immutable semantic snapshot of the root application workspace."""

from __future__ import annotations

from dataclasses import dataclass

from kuberich.domain.connections import ConnectionState
from kuberich.domain.views import ResourceScope, ViewObservation, ViewStatus


@dataclass(frozen=True, slots=True)
class AppState:
    """Frozen read-only snapshot of the root workspace view, scope, selection and status.

    ``context``, ``namespace`` and ``scope`` reflect the underlying active or connecting
    workspace observation even when the root table temporarily displays ``contexts`` or
    ``namespaces`` selection views.
    """

    view_kind: str = "pods"
    context: str | None = None
    namespace: str | None = None
    scope: ResourceScope | None = None
    selected: str | None = None
    connection: ConnectionState = ConnectionState.DISCONNECTED
    status: ViewStatus = ViewStatus.DISCONNECTED


def app_state(
    view_kind: str,
    observation: ViewObservation,
    selected: str | None = None,
) -> AppState:
    """Project a fresh immutable :class:`AppState` from the current view and observation."""
    connecting = observation.status is ViewStatus.CONNECTING
    connection = ConnectionState.CONNECTING if connecting else observation.connection.state
    namespace = (
        None if observation.context is None or connecting else observation.connection.namespace
    )
    return AppState(
        view_kind=view_kind,
        context=observation.context,
        namespace=namespace,
        scope=observation.scope,
        selected=selected,
        connection=connection,
        status=observation.status,
    )
