"""TCP intent, process argv, observed readiness and immutable UID contracts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.domain.port_forwards import (
    BoundPort,
    PortMapping,
    Readiness,
    bind_address,
    forward_command,
    parse_mappings,
    suggested_port,
    validate_forward_target,
    validate_mappings,
    verify_forward_target,
)
from kuberich.domain.processes import ProcessMode, ProcessPurpose
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "resource,spec,expected",
    [
        ("services", None, 8080),
        ("services", {}, 8080),
        ("services", {"ports": "invalid"}, 8080),
        (
            "services",
            {
                "ports": [
                    None,
                    {},
                    {"port": True},
                    {"port": 0},
                    {"port": 65536},
                    {"port": 53, "protocol": "UDP"},
                    {"port": 443},
                ]
            },
            443,
        ),
        ("services", {"ports": [{"port": 80, "protocol": "TCP"}, {"port": 443}]}, 80),
        ("services", {"ports": [{"port": "80"}]}, 8080),
        ("pods", {}, 8080),
        ("pods", {"containers": []}, 8080),
        ("pods", {"containers": [None]}, 8080),
        ("pods", {"containers": [{"ports": [{"containerPort": 9090}]}]}, 9090),
        ("pods", {"containers": [{}, {"ports": [{"containerPort": 80}]}]}, 8080),
    ],
)
def test_suggestion_is_a_tcp_hint_not_a_mutation_or_implicit_mapping(resource, spec, expected):
    assert suggested_port(resource, {"spec": spec}) == expected


def target(**changes):
    values = dict(
        session=SessionIdentity("owned", 1),
        group="",
        resource="pods",
        namespace="team",
        name="web",
        uid="web-uid",
    )
    return ResourceTarget(**{**values, **changes})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("8080:80", ((8080, 80),)),
        (":80, 0:443", ((0, 80), (0, 443))),
        ("65535:65535", ((65535, 65535),)),
    ],
)
def test_literal_mapping_intent_and_available_port(text, expected):
    mappings = parse_mappings(text)
    assert tuple((m.local, m.remote) for m in mappings) == expected
    assert parse_mappings(",".join(m.argument for m in mappings)) == mappings


@pytest.mark.parametrize(
    "text",
    [
        None,
        "x" * 257,
        "",
        "80",
        "1:0",
        "-1:80",
        "65536:80",
        "1:65536",
        "1:http",
        "1:80;echo secret",
        "\u0661:80",
        "1:80,1:443",
        ":80,:80",
        ",".join(f"{n}:80" for n in range(1, 10)),
    ],
)
def test_invalid_mappings_cannot_become_process_arguments(text):
    with pytest.raises(AppError):
        parse_mappings(text)


@pytest.mark.parametrize(
    "values", [(True, 80), (1, False), (-1, 80), (1, 0), (65536, 80), (1, 65536)]
)
def test_port_ranges_and_types(values):
    with pytest.raises(AppError):
        PortMapping(*values)


@pytest.mark.parametrize("values", [(), [], (80,), (PortMapping(1, 80),) * 9])
def test_explicit_validated_collection(values):
    with pytest.raises(AppError):
        validate_mappings(values)


@pytest.mark.parametrize(
    "address", [None, "x" * 65, "localhost", "127.0.0.1,::1", "fe80::1%eth0", "224.0.0.1"]
)
def test_invalid_or_multicast_bind(address):
    with pytest.raises(AppError):
        bind_address(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "0.0.0.0", "192.0.2.1"])
def test_literal_bind_addresses(address):
    assert bind_address(address) == address


@pytest.mark.parametrize(
    "change",
    [
        dict(group="other"),
        dict(resource="secrets"),
        dict(namespace=None),
        dict(container="app"),
        dict(name="bad/name"),
        dict(namespace="bad space"),
    ],
)
def test_captured_target_scope(change):
    with pytest.raises(AppError):
        validate_forward_target(target(**change))


@pytest.mark.parametrize("resource", ["pods", "services"])
def test_explicit_argv_and_environment_are_frozen(tmp_path, resource):
    selected = target(resource=resource)
    env = {"PATH": "/owned", "KUBECONFIG": "wrong-ambient"}
    command = forward_command(
        selected,
        tmp_path / "private.json",
        parse_mappings(":80,8443:443"),
        "127.0.0.1",
        environment=env,
        directory=tmp_path,
    )
    env["PATH"] = "changed"
    assert command.argv == (
        "kubectl",
        f"--kubeconfig={tmp_path}/private.json",
        "--context=owned",
        "--namespace=team",
        "port-forward",
        "--address=127.0.0.1",
        "--pod-running-timeout=10s",
        f"{'pod' if resource == 'pods' else 'service'}/web",
        "0:80",
        "8443:443",
    )
    assert dict(command.environment) == {"PATH": "/owned", "KUBECONFIG": f"{tmp_path}/private.json"}
    assert command.target == selected and command.mode is ProcessMode.BACKGROUND
    assert command.purpose is ProcessPurpose.PORT_FORWARD
    with pytest.raises(AppError):
        forward_command(
            selected,
            Path("relative"),
            parse_mappings("1:80"),
            "::1",
            environment={},
            directory=tmp_path,
        )


def record(selected, **fields):
    value = {
        "apiVersion": "v1",
        "kind": "Pod" if selected.resource == "pods" else "Service",
        "metadata": {"name": selected.name, "namespace": selected.namespace, "uid": selected.uid},
        "status": {"phase": "Running"},
    }
    value.update(fields)
    return resource_record(
        ApiResource("", "v1", selected.resource, value["kind"], True, frozenset({"get"})),
        value,
        selected.namespace,
    )


@pytest.mark.parametrize("resource", ["pods", "services"])
def test_live_target_is_not_replaced_or_finished(resource):
    selected = target(resource=resource)
    item = record(selected)
    verify_forward_target(selected, item)
    for altered in (
        replace(item, uid="replacement"),
        replace(item, name="other"),
        replace(item, namespace="other"),
    ):
        with pytest.raises(AppError):
            verify_forward_target(selected, altered)
    with pytest.raises(AppError, match="deleted"):
        verify_forward_target(
            selected,
            record(
                selected,
                metadata={
                    "name": "web",
                    "namespace": "team",
                    "uid": "web-uid",
                    "deletionTimestamp": "2026-10-08T00:00:00Z",
                },
            ),
        )
    if resource == "pods":
        for phase in ("Succeeded", "Failed"):
            with pytest.raises(AppError, match="finished"):
                verify_forward_target(selected, record(selected, status={"phase": phase}))
    for field, value in [("apiVersion", "apps/v1"), ("kind", "Secret")]:
        payload = item.manifest
        payload[field] = value
        with pytest.raises(AppError, match="match"):
            verify_forward_target(selected, replace(item, _manifest=json.dumps(payload).encode()))


@pytest.mark.parametrize("pod", [True, False])
def test_chunked_readiness_reports_only_requested_live_listener_intent(pod):
    parser = Readiness(parse_mappings("8080:80,:443"), "127.0.0.1", pod=pod)
    assert not parser.ready
    parser.feed(b"warning: private ignored\nForwarding from 127.")
    parser.feed(b"0.0.1:8080 -> " + (b"80" if pod else b"8000") + b"\r\n")
    assert not parser.ready
    parser.feed(b"Forwarding from 127.0.0.1:32123 -> " + (b"443" if pod else b"8443") + b"\n")
    assert parser.ready and parser.ports[0].local == 8080 and parser.ports[1].local == 32123
    parser.feed(b"Handling connection for 8080\n")
    assert parser.ready and not parser.pending


def test_ipv6_readiness_is_canonical_and_not_a_hostname():
    parser = Readiness(parse_mappings(":80"), "::1", pod=True)
    parser.feed(b"Forwarding from [0:0:0:0:0:0:0:1]:30200 -> 80\n")
    assert parser.ports == (BoundPort(30200, 80),)


@pytest.mark.parametrize(
    "output",
    [
        b"Forwarding from malformed\n",
        b"Forwarding from 0.0.0.0:8080 -> 80\n",
        b"Forwarding from 127.0.0.1:0 -> 80\n",
        b"Forwarding from 127.0.0.1:65536 -> 80\n",
        b"Forwarding from 127.0.0.1:8080 -> 0\n",
        b"Forwarding from 127.0.0.1:8080 -> 443\n",
        b"Forwarding from 127.0.0.1:8081 -> 80\n",
        b"x" * 4097,
        b"\n" * 65537,
    ],
)
def test_unrequested_malformed_or_unbounded_readiness_fails(output):
    parser = Readiness(parse_mappings("8080:80"), "127.0.0.1", pod=True)
    with pytest.raises(AppError):
        parser.feed(output)


def test_duplicate_and_repeated_dynamic_pod_listener_are_rejected():
    parser = Readiness(parse_mappings(":80,:443"), "127.0.0.1", pod=True)
    parser.feed(b"Forwarding from 127.0.0.1:30001 -> 80\n")
    with pytest.raises(AppError, match="duplicate"):
        parser.feed(b"Forwarding from 127.0.0.1:30001 -> 443\n")
    with pytest.raises(AppError, match="repeated"):
        parser.feed(b"Forwarding from 127.0.0.1:30002 -> 80\n")
