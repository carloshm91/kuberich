"""Connection requests and safe session observations, independent of SDK/widgets."""

import re
from dataclasses import dataclass, field
from enum import Enum, auto

from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument


def namespace_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
        raise AppError("Namespace must be a Kubernetes DNS label of at most 63 characters.")
    return value


def request_duration(value: str) -> float:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(ms|s|m|h)?", value)
    if match is None:
        raise AppError("Request timeout must be seconds or a duration with ms/s/m/h.")
    seconds = float(match[1]) * {None: 1, "ms": 0.001, "s": 1, "m": 60, "h": 3600}[match[2]]
    if not 0.1 <= seconds <= 3600:
        raise AppError("Request timeout must be finite and between 0.1 and 3600 seconds.")
    return seconds


@dataclass(frozen=True)
class ConnectionRequest:
    kubeconfig: str | None = None
    context: str | None = None
    namespace: str | None = None
    all_namespaces: bool = False
    timeout: float = 10.0
    overrides: ConnectionOverrides = field(default_factory=ConnectionOverrides)

    def __post_init__(self) -> None:
        if not isinstance(self.overrides, ConnectionOverrides):
            raise AppError("Connection overrides must be a validated immutable value.")
        for value in (self.kubeconfig, self.context):
            if value is not None:
                validate_argument(value)
        if self.namespace is not None:
            namespace_name(self.namespace)
        if type(self.all_namespaces) is not bool:
            raise AppError("All-namespaces must be true or false.")
        if self.namespace is not None and self.all_namespaces:
            raise AppError("--namespace and --all-namespaces are mutually exclusive.")
        if type(self.timeout) not in {float, int} or not 0.1 <= self.timeout <= 3600:
            raise AppError("Request timeout must be finite and between 0.1 and 3600 seconds.")


class ConnectionState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    LIMITED = auto()
    CONFIG_ERROR = auto()
    AUTH_ERROR = auto()
    TLS_ERROR = auto()
    TIMEOUT = auto()
    UNREACHABLE = auto()
    API_ERROR = auto()


DEFAULT_CONNECTION = ConnectionRequest()


class ConnectionProblem(Exception):
    """Messages are application-owned; never wrap raw helper/API exception values."""

    def __init__(self, state: ConnectionState, message: str) -> None:
        super().__init__(message)
        self.state = state


class HttpProblem(ConnectionProblem):
    """Carry an HTTP status without retaining the server body or credentials."""

    def __init__(self, status: int, *, retry_after: float | None = None) -> None:
        state = (
            ConnectionState.AUTH_ERROR
            if status == 401
            else ConnectionState.LIMITED
            if status == 403
            else ConnectionState.API_ERROR
        )
        message = (
            "The API rejected credentials (401). Complete provider login and retry."
            if status == 401
            else f"API read failed (HTTP {status}). Check access and retry."
        )
        super().__init__(state, message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class SessionObservation:
    state: ConnectionState = ConnectionState.DISCONNECTED
    message: str = "No kubeconfig found. Use --kubeconfig or configure KUBECONFIG."
    identity: SessionIdentity | None = None
    namespace: str | None = None
    namespaces: tuple[str, ...] = ()
    insecure: bool = False
