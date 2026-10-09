"""Generation-bound resource observations, independent of transport and widgets."""

from dataclasses import dataclass, field, replace
from enum import Enum, auto

from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionState,
    HttpProblem,
    SessionObservation,
)
from kuberich.domain.resources import ApiResource, ResourceSnapshot, api_segment
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.errors import AppError

USABLE_CONNECTIONS = frozenset({ConnectionState.CONNECTED, ConnectionState.LIMITED})


@dataclass(frozen=True)
class ResourceSelection:
    name: str = "pods"
    group: str = ""
    version: str | None = None
    server_columns: bool = False

    def __post_init__(self) -> None:
        api_segment(self.name)
        if self.group:
            api_segment(self.group)
        if self.version is not None:
            api_segment(self.version)
        if type(self.server_columns) is not bool:
            raise AppError("Server-column selection must be boolean.")


@dataclass(frozen=True)
class ResourceScope:
    session: SessionIdentity
    resource: ApiResource
    namespace: str | None

    def __post_init__(self) -> None:
        self.resource.path(self.namespace)


class ViewStatus(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    LOADING = auto()
    LIVE = auto()
    STALE = auto()
    RELISTING = auto()
    FAILED = auto()


@dataclass(frozen=True, repr=False)
class ViewObservation:
    revision: int = 0
    context: str | None = None
    connection: SessionObservation = field(default_factory=SessionObservation)
    scope: ResourceScope | None = None
    status: ViewStatus = ViewStatus.DISCONNECTED
    snapshot: ResourceSnapshot | None = None
    problem: ConnectionProblem | None = None

    @property
    def message(self) -> str:
        if self.status is ViewStatus.DISCONNECTED:
            return "Disconnected · No resource data"
        if self.status is ViewStatus.CONNECTING:
            return "Connecting · :ctx contexts · Ctrl+Q quit"
        if self.problem is not None:
            prefix = (
                "Stale resource data" if self.snapshot is not None else "Resource data unavailable"
            )
            action = " · Reconnecting" if self.status is ViewStatus.STALE else ""
            if self.status is ViewStatus.RELISTING:
                prefix = "Resource version expired · Reloading snapshot"
            return f"{prefix}{action} · {self.problem}"
        if self.status is ViewStatus.FAILED:
            return self.connection.message
        if self.scope is None:
            return "Loading resource discovery."
        if self.snapshot is None:
            return f"Loading {self.scope.resource.name}"
        count = len(self.snapshot.items)
        phase = "Live" if self.status is ViewStatus.LIVE else "Starting live updates"
        return f"{phase} · {count} {self.scope.resource.name}"


_SYNC_STATUSES = {
    SyncStatus.LOADING: ViewStatus.LOADING,
    SyncStatus.SNAPSHOT: ViewStatus.LOADING,
    SyncStatus.LIVE: ViewStatus.LIVE,
    SyncStatus.RETRYING: ViewStatus.STALE,
    SyncStatus.RELISTING: ViewStatus.RELISTING,
    SyncStatus.FAILED: ViewStatus.FAILED,
}


def _owned_problem(problem: ConnectionProblem | None) -> ConnectionProblem | None:
    # Long-lived UI state must not retain transport traceback frames and clients.
    if isinstance(problem, HttpProblem):
        return HttpProblem(problem.status, retry_after=problem.retry_after)
    if problem is not None:
        return ConnectionProblem(problem.state, str(problem))
    return None


class ViewStore:
    """One active snapshot; switching invalidates it before any cleanup await."""

    def __init__(self) -> None:
        self.observation = ViewObservation()

    def begin(self, context: str, connection: SessionObservation | None = None) -> int:
        revision = self.observation.revision + 1
        self.observation = ViewObservation(
            revision,
            context,
            connection if connection is not None else SessionObservation(),
            status=ViewStatus.LOADING if connection is not None else ViewStatus.CONNECTING,
        )
        return revision

    def connected(self, revision: int, connection: SessionObservation) -> bool:
        if revision != self.observation.revision:
            return False
        if connection.identity is None or connection.identity.context != self.observation.context:
            raise AppError("Connection observation does not belong to the active context.")
        self.observation = replace(
            self.observation,
            connection=connection,
            status=ViewStatus.LOADING
            if connection.state in USABLE_CONNECTIONS
            else ViewStatus.FAILED,
        )
        return True

    def bind(self, revision: int, scope: ResourceScope) -> bool:
        if revision != self.observation.revision:
            return False
        connection = self.observation.connection
        namespace = connection.namespace if scope.resource.namespaced else None
        if (
            connection.state not in USABLE_CONNECTIONS
            or connection.identity != scope.session
            or namespace != scope.namespace
        ):
            raise AppError("Resource scope does not belong to the active connection.")
        self.observation = replace(self.observation, scope=scope)
        return True

    def apply(self, revision: int, scope: ResourceScope, update: SyncUpdate) -> bool:
        if revision != self.observation.revision or scope != self.observation.scope:
            return False
        snapshot = update.snapshot
        if snapshot is not None and (
            snapshot.resource != scope.resource or snapshot.namespace != scope.namespace
        ):
            raise AppError("Resource snapshot does not belong to its captured scope.")
        self.observation = replace(
            self.observation,
            status=_SYNC_STATUSES[update.status],
            snapshot=snapshot,
            problem=_owned_problem(update.problem),
        )
        return True

    def fail(self, revision: int, problem: ConnectionProblem) -> bool:
        if revision != self.observation.revision:
            return False
        self.observation = replace(
            self.observation, status=ViewStatus.FAILED, problem=_owned_problem(problem)
        )
        return True

    def disconnect(self) -> None:
        self.observation = ViewObservation(self.observation.revision + 1)
