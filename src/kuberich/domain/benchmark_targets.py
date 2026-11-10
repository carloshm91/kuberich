"""Exact single-backend HTTP captures, independently of widgets and SDK models."""

from collections.abc import Mapping
from dataclasses import dataclass

from kuberich.domain.relationships import (
    RelationshipSelector,
    selector_matches,
    structured_selector,
)
from kuberich.domain.resources import resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError


@dataclass(frozen=True, slots=True)
class BenchmarkBackend:
    service: ResourceTarget | None
    pod: ResourceTarget
    service_port: int | None
    pod_port: int


@dataclass(frozen=True, slots=True)
class ServiceEndpoint:
    port: int
    target_port: int | str


def port_number(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise AppError("Benchmark ports must be integers from 1 to 65535.")
    return value


def captured_object(target: ResourceTarget, payload: Mapping[str, object]) -> dict[str, object]:
    """Validate identity on every fresh read; names never authorize replacements."""
    if (
        target.group != ""
        or target.resource not in {"services", "pods"}
        or target.namespace is None
        or payload.get("apiVersion") != "v1"
        or payload.get("kind") != ("Service" if target.resource == "services" else "Pod")
    ):
        raise AppError("Benchmarks require a captured namespaced core Service or Pod.")
    metadata = resource_object(payload.get("metadata"))
    if (
        metadata.get("name") != target.name
        or metadata.get("namespace") != target.namespace
        or metadata.get("uid") != target.uid
        or metadata.get("deletionTimestamp") is not None
    ):
        raise AppError("The benchmark target was deleted, replaced or is terminating.")
    return resource_object(payload.get("spec"))


def service_endpoints(
    target: ResourceTarget, payload: Mapping[str, object]
) -> tuple[RelationshipSelector, tuple[ServiceEndpoint, ...]]:
    spec = captured_object(target, payload)
    if target.resource != "services" or spec.get("type") == "ExternalName":
        raise AppError("Benchmarks require a selector-backed Service; ExternalName is unsupported.")
    selector = structured_selector(spec.get("selector"), direct=True, empty_matches=False)
    if not selector.requirements:
        raise AppError("Selectorless Services cannot identify a benchmark backend.")
    ports = spec.get("ports")
    if not isinstance(ports, list) or not 1 <= len(ports) <= 64:
        raise AppError("Benchmark Service ports are missing or exceed the bounded selection.")
    result = []
    for value in ports:
        item = resource_object(value)
        if item.get("protocol", "TCP") != "TCP":
            continue
        port = port_number(item.get("port"))
        remote = item.get("targetPort", port)
        if not isinstance(remote, str):
            remote = port_number(remote)
        elif not remote or len(remote) > 15 or not all(c.isalnum() or c == "-" for c in remote):
            raise AppError("Invalid named benchmark backend port.")
        result.append(ServiceEndpoint(port, remote))
    if not result or len({item.port for item in result}) != len(result):
        raise AppError("Benchmark Service requires unambiguous TCP ports.")
    return selector, tuple(result)


def ready_pod(target: ResourceTarget, payload: Mapping[str, object]) -> dict[str, object]:
    spec = captured_object(target, payload)
    status = resource_object(payload.get("status"))
    conditions = status.get("conditions")
    if (
        target.resource != "pods"
        or status.get("phase") != "Running"
        or not isinstance(conditions, list)
        or len(conditions) > 128
        or not any(
            isinstance(condition, dict)
            and condition.get("type") == "Ready"
            and condition.get("status") == "True"
            for condition in conditions
        )
    ):
        raise AppError("Select a Running, Ready and nonterminating benchmark Pod.")
    return spec


def pod_ports(target: ResourceTarget, payload: Mapping[str, object]) -> tuple[tuple[str, int], ...]:
    spec = ready_pod(target, payload)
    containers = spec.get("containers")
    if not isinstance(containers, list) or not 1 <= len(containers) <= 64:
        raise AppError("Benchmark Pod containers are missing or exceed their bound.")
    result = []
    for value in containers:
        ports = resource_object(value).get("ports", [])
        if not isinstance(ports, list) or len(ports) > 64:
            raise AppError("Benchmark Pod ports exceed their bound.")
        for raw in ports:
            item = resource_object(raw)
            if item.get("protocol", "TCP") == "TCP":
                name = item.get("name", "")
                if not isinstance(name, str) or len(name) > 15:
                    raise AppError("Invalid benchmark Pod port name.")
                result.append((name, port_number(item.get("containerPort"))))
                if len(result) > 128:
                    raise AppError("Benchmark Pod ports exceed their bound.")
    return tuple(result)


def backend_port(
    endpoint: ServiceEndpoint, target: ResourceTarget, payload: Mapping[str, object]
) -> int:
    ports = pod_ports(target, payload)
    if isinstance(endpoint.target_port, int):
        return endpoint.target_port
    matches = {number for name, number in ports if name == endpoint.target_port}
    if len(matches) != 1:
        raise AppError("Named benchmark backend port is absent or ambiguous; review the Service.")
    return next(iter(matches))


def backend_matches(
    backend: BenchmarkBackend,
    service: Mapping[str, object] | None,
    pod: Mapping[str, object],
) -> None:
    ready_pod(backend.pod, pod)
    if backend.service is None:
        if backend.service_port is not None or backend.pod_port not in {
            number for _, number in pod_ports(backend.pod, pod)
        }:
            raise AppError("The reviewed benchmark Pod port changed.")
        return
    if service is None:
        raise AppError("The reviewed benchmark Service is unavailable.")
    selector, ports = service_endpoints(backend.service, service)
    labels = resource_object(resource_object(pod.get("metadata")).get("labels", {}))
    if not selector_matches(selector, labels):
        raise AppError("The reviewed Pod no longer matches the Service selector.")
    endpoint = next((port for port in ports if port.port == backend.service_port), None)
    if endpoint is None or backend_port(endpoint, backend.pod, pod) != backend.pod_port:
        raise AppError("The reviewed benchmark Service/backend port changed.")
