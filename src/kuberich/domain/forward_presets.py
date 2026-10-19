"""Literal, bounded forward presets resolved against one captured resource."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from kuberich.domain.port_forwards import PortMapping, bind_address, validate_mappings
from kuberich.domain.resources import resource_object
from kuberich.errors import AppError

ANNOTATIONS = ("k9scli.io/auto-port-forwards", "k9scli.io/port-forwards")


class ForwardTransport(StrEnum):
    AUTO = "auto"
    WEBSOCKET = "websocket"
    SPDY = "spdy"


def transport_environment(
    environment: Mapping[str, str], transport: ForwardTransport
) -> dict[str, str]:
    if not isinstance(transport, ForwardTransport):
        raise AppError("Forward transport must be auto, websocket or spdy.")
    result = dict(environment)
    if transport is not ForwardTransport.AUTO:
        result["KUBECTL_PORT_FORWARD_WEBSOCKETS"] = (
            "true" if transport is ForwardTransport.WEBSOCKET else "false"
        )
    return result


def mapping_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or re.fullmatch(r"[a-zA-Z0-9_:, .-]+", value, re.ASCII) is None
    ):
        raise AppError("Use bounded comma-separated local:remote or container::local:remote ports.")
    return value


def _remote_port(
    value: str, resource: str, manifest: Mapping[str, object], container: str | None
) -> int:
    if resource not in {"pods", "services"}:
        raise AppError("Named ports require a captured pod or Service.")
    if resource == "services" and container is not None:
        raise AppError("Service mappings cannot select a container.")
    spec = resource_object(manifest.get("spec", {}))
    entries: list[object] = []
    if resource == "pods":
        containers = spec.get("containers", [])
        if not isinstance(containers, list):
            raise AppError("The captured pod has invalid container declarations.")
        selected = [
            item
            for item in containers
            if isinstance(item, dict) and (container is None or item.get("name") == container)
        ]
        if container is not None and len(selected) != 1:
            raise AppError("Select an existing, unambiguous regular container.")
        for item in selected:
            ports = item.get("ports", [])
            if isinstance(ports, list):
                entries.extend(ports)
        key = "containerPort"
    else:
        ports = spec.get("ports", [])
        if isinstance(ports, list):
            entries.extend(ports)
        key = "port"
    if re.fullmatch(r"[0-9]{1,5}", value, re.ASCII):
        return PortMapping(0, int(value)).remote
    if (
        len(value) > 15
        or re.fullmatch(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", value, re.ASCII) is None
        or not any("a" <= char <= "z" for char in value)
    ):
        raise AppError(
            "Use local:remote; remote must be a TCP number or a declared Kubernetes port name."
        )
    found = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == value]
    if len(found) != 1 or found[0].get("protocol", "TCP") != "TCP":
        raise AppError("Named TCP port is missing, ambiguous or uses an unsupported protocol.")
    number = found[0].get(key)
    if type(number) is not int:
        raise AppError("The declared TCP port must be a numeric port.")
    return PortMapping(0, number).remote


def resolve_mappings(
    text: str, resource: str, manifest: Mapping[str, object], *, annotation: bool = False
) -> tuple[PortMapping, ...]:
    mappings = []
    for item in mapping_text(text).split(","):
        container = None
        item = item.strip()
        if "::" in item:
            container, item = item.split("::", 1)
            if re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", container) is None:
                raise AppError("Forward container must be a valid regular container name.")
        if annotation and resource == "pods" and container is None:
            raise AppError("Pod forward annotations require container::port mappings.")
        parts = item.split(":")
        if len(parts) > 2:
            raise AppError("Use container::local:remote or local:remote port mappings.")
        remote = _remote_port(parts[-1], resource, manifest, container)
        local = parts[0] if len(parts) == 2 else str(remote)
        if re.fullmatch(r"[0-9]{0,5}", local, re.ASCII) is None:
            raise AppError("Local TCP port must be numeric; use 0 for an available port.")
        mappings.append(PortMapping(int(local or "0"), remote))
    return validate_mappings(tuple(mappings))


@dataclass(frozen=True)
class ForwardPreset:
    name: str
    ports: str
    address: str = "127.0.0.1"
    transport: ForwardTransport = ForwardTransport.AUTO
    retries: int = 0
    intent: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or re.fullmatch(r"[a-zA-Z][\w-]{0,63}", self.name, re.ASCII) is None
        ):
            raise AppError("Forward preset name must contain 1-64 ASCII identifier characters.")
        mapping_text(self.ports)
        if self.intent is not None:
            mapping_text(self.intent)
        bind_address(self.address)
        transport_environment({}, self.transport)
        if type(self.retries) is not int or not 0 <= self.retries <= 3:
            raise AppError("Forward retries must be an integer from 0 to 3.")


def annotation_preset(
    manifest: Mapping[str, object], resource: str
) -> tuple[ForwardPreset, bool] | None:
    metadata = resource_object(manifest.get("metadata", {}))
    raw = metadata.get("annotations")
    annotations = resource_object({} if raw is None else raw)
    for name in ANNOTATIONS:
        if name in annotations:
            text = mapping_text(annotations[name])
            # Freeze resolved numeric mappings before the operator reviews them.
            ports = resolve_mappings(text, resource, manifest, annotation=True)
            return ForwardPreset(
                "annotation", ",".join(port.argument for port in ports), intent=text
            ), name == ANNOTATIONS[0]
    return None
