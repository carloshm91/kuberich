"""Immutable selection captures; guards reject a different client session or object."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from kubetrol.errors import AppError
from kubetrol.security.arguments import validate_argument


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Create once per owned client, including when the same context is reopened."""

    context: str
    generation: int
    connection_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        validate_argument(self.context)
        if type(self.generation) is not int or self.generation < 0:
            raise AppError("Session generation must be a nonnegative integer.")
        if not isinstance(self.connection_id, UUID):
            raise AppError("Session connection identity must be a UUID.")


@dataclass(frozen=True, slots=True)
class ResourceTarget:
    """Capture before awaiting; namespace=None denotes a cluster-scoped resource."""

    session: SessionIdentity
    group: str
    resource: str
    namespace: str | None
    name: str
    uid: str
    container: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionIdentity):
            raise AppError("A target requires an explicit client session identity.")
        if self.group != "":
            validate_argument(self.group)
        for value in (self.resource, self.name, self.uid):
            validate_argument(value)
        for optional_value in (self.namespace, self.container):
            if optional_value is not None:
                validate_argument(optional_value)
        if self.resource.startswith("-") or self.name.startswith("-"):
            raise AppError("Resource identifiers cannot be command options.")

    def require_current(self, session: SessionIdentity, *, uid: str) -> None:
        """A client switch or same-name recreation invalidates the captured target.

        Services must additionally bind requests to that owned client, enforce
        read-only/RBAC policy and use API UID/version preconditions for writes.
        This local guard cannot close a server-side time-of-check race by itself.
        """
        if session != self.session or uid != self.uid:
            raise AppError("The selected target is stale; select the resource again.")
