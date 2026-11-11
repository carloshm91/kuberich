"""Reviewed single-backend identity, readiness, selector and port changes fail closed."""

from copy import deepcopy
from dataclasses import replace

import pytest

from kuberich.domain.benchmark_targets import (
    BenchmarkBackend,
    ServiceEndpoint,
    backend_matches,
    backend_port,
    captured_object,
    pod_ports,
    port_number,
    ready_pod,
    service_endpoints,
)
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

SESSION = SessionIdentity("owned", 1)
POD_TARGET = ResourceTarget(SESSION, "", "pods", "team", "backend", "pod-uid")
SERVICE_TARGET = ResourceTarget(SESSION, "", "services", "team", "owned", "service-uid")
POD = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": "backend",
        "uid": "pod-uid",
        "namespace": "team",
        "labels": {"app": "owned"},
    },
    "spec": {"containers": [{"name": "web", "ports": [{"name": "http", "containerPort": 8080}]}]},
    "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
}
SERVICE = {
    "apiVersion": "v1",
    "kind": "Service",
    "metadata": {"name": "owned", "uid": "service-uid", "namespace": "team"},
    "spec": {"selector": {"app": "owned"}, "ports": [{"port": 80, "targetPort": "http"}]},
}


@pytest.mark.parametrize("value", [True, False, None, "80", 0, -1, 65536, 2.5])
def test_ports_require_positive_bounded_integer(value):
    with pytest.raises(AppError):
        port_number(value)


def test_exact_ready_backend_and_tcp_numeric_or_named_ports():
    assert port_number(65535) == 65535
    assert captured_object(POD_TARGET, POD) == POD["spec"]
    assert ready_pod(POD_TARGET, POD) == POD["spec"]
    assert pod_ports(POD_TARGET, POD) == (("http", 8080),)
    selector, endpoints = service_endpoints(SERVICE_TARGET, SERVICE)
    assert selector.requirements[0].values == ("owned",) and endpoints == (
        ServiceEndpoint(80, "http"),
    )
    assert backend_port(endpoints[0], POD_TARGET, POD) == 8080
    assert backend_port(ServiceEndpoint(80, 9090), POD_TARGET, POD) == 9090
    backend_matches(BenchmarkBackend(SERVICE_TARGET, POD_TARGET, 80, 8080), SERVICE, POD)
    backend_matches(BenchmarkBackend(None, POD_TARGET, None, 8080), None, POD)
    numeric = deepcopy(SERVICE)
    numeric["spec"]["ports"] = [
        {"port": 80},
        {"port": 81, "targetPort": 8081, "protocol": "TCP"},
        {"port": 53, "protocol": "UDP"},
    ]
    assert service_endpoints(SERVICE_TARGET, numeric)[1] == (
        ServiceEndpoint(80, 80),
        ServiceEndpoint(81, 8081),
    )
    absent = deepcopy(POD)
    absent["spec"]["containers"] = [{"name": "no-declared-ports"}]
    assert pod_ports(POD_TARGET, absent) == ()
    udp = deepcopy(POD)
    udp["spec"]["containers"][0]["ports"].append({"containerPort": 53, "protocol": "UDP"})
    assert pod_ports(POD_TARGET, udp) == (("http", 8080),)
    unnamed = deepcopy(POD)
    unnamed["spec"]["containers"][0]["ports"] = [{"containerPort": 8080}]
    assert pod_ports(POD_TARGET, unnamed) == (("", 8080),)


@pytest.mark.parametrize(
    "target",
    [
        replace(POD_TARGET, group="apps"),
        replace(POD_TARGET, resource="deployments"),
        replace(POD_TARGET, namespace=None),
    ],
)
def test_only_exact_namespaced_core_identity_is_accepted(target):
    with pytest.raises(AppError):
        captured_object(target, POD)


@pytest.mark.parametrize("field,value", [("apiVersion", "v2"), ("kind", "Service")])
def test_wrong_descriptor_refused(field, value):
    pod = deepcopy(POD)
    pod[field] = value
    with pytest.raises(AppError):
        captured_object(POD_TARGET, pod)


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "other"),
        ("namespace", "other"),
        ("uid", "replacement"),
        ("deletionTimestamp", "2026-11-10T00:00:00Z"),
    ],
)
def test_replacement_termination_and_scope_refused(field, value):
    pod = deepcopy(POD)
    pod["metadata"][field] = value
    with pytest.raises(AppError):
        captured_object(POD_TARGET, pod)


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "ExternalName"},
        {"selector": {}},
        {"selector": {"app": "owned"}, "ports": None},
        {"selector": {"app": "owned"}, "ports": []},
        {"selector": {"app": "owned"}, "ports": [{"port": 80}] * 65},
        {"selector": {"app": "owned"}, "ports": [{"port": 53, "protocol": "UDP"}]},
        {"selector": {"app": "owned"}, "ports": [{"port": 80}, {"port": 80}]},
        {"selector": {"app": "owned"}, "ports": [{"port": 80, "targetPort": True}]},
        *(
            {"selector": {"app": "owned"}, "ports": [{"port": 80, "targetPort": value}]}
            for value in ("", "x" * 16, "bad/name")
        ),
    ],
)
def test_unsupported_or_ambiguous_service_route_refused(spec):
    service = deepcopy(SERVICE)
    service["spec"] = spec
    with pytest.raises(AppError):
        service_endpoints(SERVICE_TARGET, service)


def test_pod_is_not_service_and_service_is_not_ready_pod():
    with pytest.raises(AppError):
        service_endpoints(POD_TARGET, POD)
    with pytest.raises(AppError):
        ready_pod(SERVICE_TARGET, SERVICE)


@pytest.mark.parametrize(
    "status",
    [
        {"phase": "Pending", "conditions": []},
        {"phase": "Running", "conditions": None},
        {"phase": "Running", "conditions": [{}] * 129},
        {"phase": "Running", "conditions": []},
        {
            "phase": "Running",
            "conditions": [
                None,
                {"type": "Other", "status": "True"},
                {"type": "Ready", "status": "False"},
            ],
        },
    ],
)
def test_nonready_backend_refused(status):
    pod = deepcopy(POD)
    pod["status"] = status
    with pytest.raises(AppError):
        ready_pod(POD_TARGET, pod)


@pytest.mark.parametrize(
    "containers",
    [
        None,
        [],
        [{}] * 65,
        [{"ports": None}],
        [{"ports": [{}] * 65}],
        [{"ports": [{"containerPort": 8080, "name": 1}]}],
        [{"ports": [{"containerPort": 8080, "name": "x" * 16}]}],
        [{"ports": [{"containerPort": 8080}] * 64}] * 3,
    ],
)
def test_pod_port_declarations_are_bounded(containers):
    pod = deepcopy(POD)
    pod["spec"]["containers"] = containers
    with pytest.raises(AppError):
        pod_ports(POD_TARGET, pod)


@pytest.mark.parametrize(
    "ports",
    [[], [{"name": "http", "containerPort": 8080}, {"name": "http", "containerPort": 9090}]],
)
def test_named_backend_requires_one_numeric_destination(ports):
    pod = deepcopy(POD)
    pod["spec"]["containers"][0]["ports"] = ports
    with pytest.raises(AppError):
        backend_port(ServiceEndpoint(80, "http"), POD_TARGET, pod)


@pytest.mark.parametrize(
    "backend,service,pod",
    [
        (BenchmarkBackend(None, POD_TARGET, 80, 8080), None, POD),
        (BenchmarkBackend(None, POD_TARGET, None, 9999), None, POD),
        (BenchmarkBackend(SERVICE_TARGET, POD_TARGET, 80, 8080), None, POD),
        (
            BenchmarkBackend(SERVICE_TARGET, POD_TARGET, 80, 8080),
            {**SERVICE, "spec": {**SERVICE["spec"], "selector": {"app": "changed"}}},
            POD,
        ),
        (BenchmarkBackend(SERVICE_TARGET, POD_TARGET, 81, 8080), SERVICE, POD),
        (BenchmarkBackend(SERVICE_TARGET, POD_TARGET, 80, 9090), SERVICE, POD),
    ],
)
def test_reviewed_backend_must_still_match_service_port_and_labels(backend, service, pod):
    with pytest.raises(AppError):
        backend_matches(backend, service, pod)
