"""Explicit, offline configuration for the fixed privileged diagnostic profile."""

import re
from dataclasses import dataclass, field

from kuberich.config.schema import ConfigDocument
from kuberich.domain.connections import namespace_name
from kuberich.domain.quantities import parse_quantity
from kuberich.errors import AppError

_IMAGE = re.compile(
    r"(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?"
    r"(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?@sha256:[a-fA-F0-9]{64}"
)


@dataclass(frozen=True, slots=True)
class NodeShellResources:
    cpu: str = "10m"
    memory: str = "32Mi"

    def __post_init__(self) -> None:
        for value, maximum in ((self.cpu, 8), (self.memory, 8 * 1024**3)):
            quantity = parse_quantity(value)
            if quantity is None or not 0 < quantity <= maximum:
                raise AppError(
                    "Node-shell resources require positive CPU <= 8 and memory <= 8 GiB."
                )

    def to_mapping(self) -> dict[str, str]:
        return {"cpu": self.cpu, "memory": self.memory}


@dataclass(frozen=True, slots=True)
class NodeShellSettings:
    enabled: bool = False
    image: str | None = None
    namespace: str | None = None
    requests: NodeShellResources = field(default_factory=NodeShellResources)
    limits: NodeShellResources = field(default_factory=lambda: NodeShellResources("250m", "128Mi"))
    startup_timeout_seconds: int = 60
    session_timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AppError("node_shell.enabled must be true or false.")
        if self.image is not None and (
            not isinstance(self.image, str)
            or len(self.image) > 512
            or _IMAGE.fullmatch(self.image) is None
        ):
            raise AppError(
                "Node-shell image must be one explicit image ending in @sha256:<64 hex digits>."
            )
        if self.namespace is not None:
            if not isinstance(self.namespace, str):
                raise AppError("Node-shell namespace must be a Kubernetes namespace name.")
            namespace_name(self.namespace)
        if self.enabled and (self.image is None or self.namespace is None):
            raise AppError("Enabled node shell requires an explicit image and existing namespace.")
        if not isinstance(self.requests, NodeShellResources) or not isinstance(
            self.limits, NodeShellResources
        ):
            raise AppError("Node-shell requests and limits require CPU and memory quantities.")
        for key in ("cpu", "memory"):
            request = parse_quantity(getattr(self.requests, key))
            limit = parse_quantity(getattr(self.limits, key))
            assert request is not None and limit is not None
            if request > limit:
                raise AppError("Node-shell requests cannot exceed limits.")
        for value, minimum, maximum in (
            (self.startup_timeout_seconds, 5, 300),
            (self.session_timeout_seconds, 60, 3600),
        ):
            if type(value) is not int or not minimum <= value <= maximum:
                raise AppError(
                    "Node-shell startup must be 5-300 seconds and session 60-3600 seconds."
                )

    def to_mapping(self) -> dict[str, object]:
        return serialize_node_shell(self)


def _resources(value: object) -> NodeShellResources:
    if not isinstance(value, dict) or set(value) != {"cpu", "memory"}:
        raise AppError("Node-shell resource mappings require exactly cpu and memory.")
    return NodeShellResources(value["cpu"], value["memory"])


def parse_node_shell(value: object) -> NodeShellSettings:
    if not isinstance(value, dict) or value.keys() - {
        "schema_version",
        "enabled",
        "image",
        "namespace",
        "requests",
        "limits",
        "startup_timeout_seconds",
        "session_timeout_seconds",
    }:
        raise AppError("Invalid node_shell configuration fields.")
    version = value.get("schema_version", 1)
    if type(version) is not int or version != 1:
        raise AppError("node_shell.schema_version must be 1.")
    defaults = NodeShellSettings()
    return NodeShellSettings(
        enabled=value.get("enabled", False),
        image=value.get("image"),
        namespace=value.get("namespace"),
        requests=_resources(value["requests"]) if "requests" in value else defaults.requests,
        limits=_resources(value["limits"]) if "limits" in value else defaults.limits,
        startup_timeout_seconds=value.get("startup_timeout_seconds", 60),
        session_timeout_seconds=value.get("session_timeout_seconds", 3600),
    )


def serialize_node_shell(settings: NodeShellSettings) -> dict[str, object]:
    return {
        "schema_version": 1,
        "enabled": settings.enabled,
        "image": settings.image,
        "namespace": settings.namespace,
        "requests": settings.requests.to_mapping(),
        "limits": settings.limits.to_mapping(),
        "startup_timeout_seconds": settings.startup_timeout_seconds,
        "session_timeout_seconds": settings.session_timeout_seconds,
    }


def node_shell_from(document: ConfigDocument) -> NodeShellSettings:
    return (
        parse_node_shell(document.extensions["node_shell"])
        if "node_shell" in document.extensions
        else NodeShellSettings()
    )
