"""Bounded TCP mappings, explicit kubectl scope and real readiness observations."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from ipaddress import ip_address
from pathlib import Path

from kuberich.domain.connections import namespace_name
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, capture_command
from kuberich.domain.resources import ResourceRecord, api_segment, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError

MAX_MAPPINGS = 8


def suggested_port(resource: str, manifest: Mapping[str, object]) -> int:
    """Suggest the first declared TCP port; explicit operator intent still wins."""
    specification = manifest.get("spec")
    if not isinstance(specification, dict):
        return 8080
    ports = specification.get("ports")
    key = "port"
    if resource == "pods":
        containers = specification.get("containers")
        if (
            not isinstance(containers, list)
            or not containers
            or not isinstance(containers[0], dict)
        ):
            return 8080
        ports, key = containers[0].get("ports"), "containerPort"
    if isinstance(ports, list):
        for port in ports:
            if isinstance(port, dict):
                value = port.get(key)
                if (
                    type(value) is int
                    and 1 <= value <= 65535
                    and port.get("protocol", "TCP") == "TCP"
                ):
                    return value
    return 8080


class ForwardState(Enum):
    STARTING = auto()
    READY = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class PortMapping:
    local: int
    remote: int

    def __post_init__(self) -> None:
        if (
            type(self.local) is not int
            or type(self.remote) is not int
            or not 0 <= self.local <= 65535
            or not 1 <= self.remote <= 65535
        ):
            raise AppError("TCP ports must be 1-65535; local 0 requests an available port.")

    @property
    def argument(self) -> str:
        return f"{self.local}:{self.remote}"


def validate_mappings(mappings: tuple[PortMapping, ...]) -> tuple[PortMapping, ...]:
    if not isinstance(mappings, tuple) or not 1 <= len(mappings) <= MAX_MAPPINGS:
        raise AppError("Specify one to eight TCP port mappings.")
    if not all(isinstance(mapping, PortMapping) for mapping in mappings):
        raise AppError("Port mappings must be validated TCP ports.")
    explicit = [mapping.local for mapping in mappings if mapping.local]
    if len(explicit) != len(set(explicit)) or len(mappings) != len(set(mappings)):
        raise AppError("Port mappings must have distinct explicit local ports and no duplicates.")
    return mappings


def parse_mappings(text: str) -> tuple[PortMapping, ...]:
    if not isinstance(text, str) or len(text) > 256:
        raise AppError("Port mappings require bounded local:remote text.")
    mappings = []
    for item in text.split(","):
        match = re.fullmatch(r"([0-9]{0,5}):([0-9]{1,5})", item.strip())
        if match is None:
            raise AppError("Use comma-separated local:remote TCP ports; :remote chooses a port.")
        mappings.append(PortMapping(int(match[1] or "0"), int(match[2])))
    return validate_mappings(tuple(mappings))


def bind_address(value: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or "%" in value:
        raise AppError("Bind address must be one literal IPv4 or IPv6 address.")
    try:
        address = ip_address(value)
    except ValueError:
        raise AppError("Bind address must be one literal IPv4 or IPv6 address.") from None
    if address.is_multicast:
        raise AppError("Port-forward cannot bind a multicast address.")
    return str(address)


def validate_forward_target(target: ResourceTarget) -> None:
    if (
        target.group
        or target.resource not in {"pods", "services"}
        or target.namespace is None
        or target.container is not None
    ):
        raise AppError("Port-forward requires a captured namespaced pod or Service.")
    api_segment(target.name)
    namespace_name(target.namespace)


def verify_forward_target(target: ResourceTarget, record: ResourceRecord) -> None:
    validate_forward_target(target)
    target.require_current(target.session, uid=record.uid or "")
    manifest = record.manifest
    if (
        record.name != target.name
        or record.namespace != target.namespace
        or manifest.get("apiVersion", "v1") != "v1"
        or manifest.get("kind", "Pod" if target.resource == "pods" else "Service")
        != ("Pod" if target.resource == "pods" else "Service")
    ):
        raise AppError("Port-forward response does not match the captured resource.")
    if resource_object(manifest.get("metadata")).get("deletionTimestamp") is not None:
        raise AppError("Port-forward target is being deleted.")
    if target.resource == "pods" and resource_object(manifest.get("status", {})).get("phase") in {
        "Succeeded",
        "Failed",
    }:
        raise AppError("Port-forward target pod has finished.")


def forward_command(
    target: ResourceTarget,
    path: Path,
    mappings: tuple[PortMapping, ...],
    address: str,
    *,
    environment: Mapping[str, str],
    directory: Path,
    executable: str = "kubectl",
) -> ProcessCommand:
    validate_forward_target(target)
    validate_mappings(mappings)
    address = bind_address(address)
    if not isinstance(path, Path) or not path.is_absolute():
        raise AppError("Port-forward requires an explicit absolute kubeconfig.")
    return capture_command(
        (
            executable,
            f"--kubeconfig={path}",
            f"--context={target.session.context}",
            f"--namespace={target.namespace}",
            "port-forward",
            f"--address={address}",
            "--pod-running-timeout=10s",
            f"{'pod' if target.resource == 'pods' else 'service'}/{target.name}",
            *(mapping.argument for mapping in mappings),
        ),
        environment={**environment, "KUBECONFIG": str(path)},
        directory=directory,
        mode=ProcessMode.BACKGROUND,
        purpose=ProcessPurpose.PORT_FORWARD,
        target=target,
    )


@dataclass(frozen=True)
class BoundPort:
    local: int
    remote: int


_READY = re.compile(rb"Forwarding from (\[[0-9a-fA-F:]+\]|[0-9.]+):([0-9]{1,5}) -> ([0-9]{1,5})")


class Readiness:
    """Bound line framing and accept only listeners requested by this process.

    Service output reports its selected pod's targetPort. Keep observed remote
    ports distinct from the requested Service ports rather than guessing them.
    """

    def __init__(self, mappings: tuple[PortMapping, ...], address: str, *, pod: bool) -> None:
        self.mappings = validate_mappings(mappings)
        self.address = bind_address(address)
        self.pod = pod
        self.pending = bytearray()
        self.ports: tuple[BoundPort, ...] = ()

    @property
    def ready(self) -> bool:
        return len(self.ports) == len(self.mappings)

    def feed(self, chunk: bytes) -> None:
        if len(chunk) > 65536:
            raise AppError("Port-forward emitted an excessive output burst.")
        for part in chunk.splitlines(keepends=True):
            self.pending.extend(part)
            if len(self.pending) > 4096:
                raise AppError("Port-forward emitted an oversized readiness line.")
            if not self.pending.endswith(b"\n"):
                continue
            line = bytes(self.pending).removesuffix(b"\n").removesuffix(b"\r")
            self.pending.clear()
            if not line.startswith(b"Forwarding from"):
                continue
            match = _READY.fullmatch(line)
            if match is None or bind_address(match[1].decode().strip("[]")) != self.address:
                raise AppError("Port-forward reported an unexpected listener.")
            bound = BoundPort(int(match[2]), int(match[3]))
            PortMapping(bound.local, bound.remote)
            if bound.local == 0 or any(port.local == bound.local for port in self.ports):
                raise AppError("Port-forward reported an invalid or duplicate listener.")
            explicit = {mapping.local: mapping.remote for mapping in self.mappings if mapping.local}
            dynamic = [mapping for mapping in self.mappings if not mapping.local]
            seen_dynamic = [port for port in self.ports if port.local not in explicit]
            if bound.local not in explicit and len(seen_dynamic) >= len(dynamic):
                raise AppError("Port-forward reported an unrequested local port.")
            if self.pod:
                expected = (
                    {explicit[bound.local]}
                    if bound.local in explicit
                    else {mapping.remote for mapping in dynamic}
                )
                if bound.remote not in expected:
                    raise AppError("Port-forward reported an unrequested pod port.")
                if bound.local not in explicit and any(
                    port.remote == bound.remote for port in seen_dynamic
                ):
                    raise AppError("Port-forward repeated a dynamically requested pod port.")
            self.ports = (*self.ports, bound)
