"""Untrusted annotations cannot grant listener permission or select ambiguous ports."""

from dataclasses import replace

import pytest

from kuberich.config.forwarding import ForwardPreferences, forwarding_from, parse_forwarding
from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.domain.forward_presets import (
    ANNOTATIONS,
    ForwardPreset,
    ForwardTransport,
    annotation_preset,
    mapping_text,
    resolve_mappings,
    transport_environment,
)
from kuberich.domain.port_forwards import PortMapping
from kuberich.errors import AppError


def pod():
    return {
        "spec": {
            "containers": [
                {
                    "name": "web",
                    "ports": [
                        {"name": "http", "containerPort": 8080},
                        {"name": "dns", "containerPort": 53, "protocol": "UDP"},
                    ],
                },
                {"name": "metrics", "ports": [{"name": "metrics", "containerPort": 9090}]},
            ]
        }
    }


@pytest.mark.parametrize(
    "text,expected",
    [
        ("web::http", [(8080, 8080)]),
        ("web::8081:http,metrics::0:metrics", [(8081, 8080), (0, 9090)]),
        (":http,9091:metrics", [(0, 8080), (9091, 9090)]),
        ("web:::http", [(0, 8080)]),
        ("0:65535", [(0, 65535)]),
        ("9090", [(9090, 9090)]),
    ],
)
def test_names_and_container_scopes_resolve_to_explicit_numeric_tcp(text, expected):
    result = resolve_mappings(text, "pods", pod())
    assert [(item.local, item.remote) for item in result] == expected
    assert all(isinstance(item, PortMapping) for item in result)


def test_services_use_service_port_not_target_port_and_do_not_need_a_container():
    manifest = {"spec": {"ports": [{"name": "http", "port": 80, "targetPort": 8080}]}}
    assert resolve_mappings("8081:http", "services", manifest) == (PortMapping(8081, 80),)
    manifest["metadata"] = {"annotations": {ANNOTATIONS[1]: "0:http"}}
    assert annotation_preset(manifest, "services")[0].ports == "0:80"


@pytest.mark.parametrize(
    "text", [None, "", "a" * 2049, "web::80\n", "$(command)", "1:80;evil", "\x1b[31m", "端口"]
)
def test_mapping_input_is_bounded_literal_text(text):
    with pytest.raises(AppError):
        mapping_text(text)


@pytest.mark.parametrize(
    "text",
    [
        "bad name::80",
        "-web::80",
        "web-::80",
        "web::1:2:3",
        "-1:http",
        "65536:http",
        "1:0",
        "1:65536",
        "1:missing",
        "1:dns",
        "1:123456",
        "1:a" + "b" * 15,
        "1:UPPER",
        "1:-http",
        "1:123456789012345",
        "1:80,1:81",
        ":http,:http",
        ",".join(f"{i + 1}:80" for i in range(9)),
        "gone::80",
    ],
)
def test_invalid_missing_udp_and_colliding_mappings_never_become_argv(text):
    with pytest.raises(AppError):
        resolve_mappings(text, "pods", pod())


@pytest.mark.parametrize(
    "manifest",
    [
        {"spec": {"containers": False}},
        {"spec": {"containers": [None, {"name": "other"}]}},
        {"spec": {"containers": [{"name": "web"}, {"name": "web"}]}},
    ],
)
def test_container_selection_rejects_malformed_missing_and_duplicate_identity(manifest):
    with pytest.raises(AppError):
        resolve_mappings("web::80", "pods", manifest)


def test_named_ports_are_not_guessed_across_containers_or_malformed_declarations():
    value = pod()
    value["spec"]["containers"].append(
        {"name": "other", "ports": [{"name": "http", "containerPort": 8080}]}
    )
    with pytest.raises(AppError, match="ambiguous"):
        resolve_mappings(":http", "pods", value)
    assert resolve_mappings("web:::http", "pods", value) == (PortMapping(0, 8080),)
    for resource, value in [
        (
            "pods",
            {
                "spec": {
                    "containers": [
                        None,
                        {},
                        {"ports": "invalid"},
                        {"ports": [None, {}, {"name": "http", "containerPort": "80"}]},
                    ]
                }
            },
        ),
        ("services", {"spec": {"ports": "invalid"}}),
        ("services", {}),
    ]:
        with pytest.raises(AppError):
            resolve_mappings(":http", resource, value)
    with pytest.raises(AppError):
        resolve_mappings("80", "deployments", {})
    with pytest.raises(AppError):
        resolve_mappings("web::80", "services", {})


def test_annotations_prefer_explicit_auto_key_but_return_no_authorization():
    value = pod()
    assert annotation_preset(value, "pods") is None
    for key, automatic in [(ANNOTATIONS[1], False), (ANNOTATIONS[0], True)]:
        value["metadata"] = {"annotations": {key: "web::0:http,metrics::9091:metrics"}}
        preset, flag = annotation_preset(value, "pods")
        assert (
            preset
            == ForwardPreset(
                "annotation", "0:8080,9091:9090", intent="web::0:http,metrics::9091:metrics"
            )
            and flag is automatic
        )
    value["metadata"]["annotations"][ANNOTATIONS[1]] = "invalid"
    assert annotation_preset(value, "pods")[1] is True
    value["metadata"] = {"annotations": {ANNOTATIONS[0]: "80"}}
    with pytest.raises(AppError, match="container"):
        annotation_preset(value, "pods")
    value["metadata"]["annotations"][ANNOTATIONS[0]] = False
    with pytest.raises(AppError):
        annotation_preset(value, "pods")


@pytest.mark.parametrize(
    "mode,flag",
    [
        (ForwardTransport.AUTO, "false"),
        (ForwardTransport.WEBSOCKET, "true"),
        (ForwardTransport.SPDY, "false"),
    ],
)
def test_transport_only_changes_child_flag_and_preserves_captured_environment(mode, flag):
    environment = {"PATH": "/owned", "KUBECTL_PORT_FORWARD_WEBSOCKETS": "false"}
    assert transport_environment(environment, mode) == {
        **environment,
        "KUBECTL_PORT_FORWARD_WEBSOCKETS": flag,
    }
    assert environment["KUBECTL_PORT_FORWARD_WEBSOCKETS"] == "false"
    assert transport_environment({}, ForwardTransport.AUTO) == {}
    with pytest.raises(AppError):
        transport_environment({}, "spdy")


@pytest.mark.parametrize(
    "change",
    [
        {"name": None},
        {"name": "-bad"},
        {"name": "a" * 65},
        {"ports": None},
        {"intent": "bad\nintent"},
        {"address": "localhost"},
        {"transport": "spdy"},
        {"retries": True},
        {"retries": -1},
        {"retries": 4},
        {"retries": "1"},
    ],
)
def test_local_preset_values_cannot_smuggle_permissions_or_unbounded_retries(change):
    with pytest.raises(AppError):
        replace(ForwardPreset("web", ":http"), **change)


def test_versioned_local_preferences_are_explicit_and_context_replacement_is_exact():
    value = {
        "schema_version": 1,
        "auto_annotations": True,
        "presets": {"web": {"ports": ":http", "transport": "websocket", "retries": 3}},
        "contexts": {
            "production": {
                "auto_annotations": False,
                "presets": {"other": {"ports": "8081:80", "address": "::1"}},
            }
        },
    }
    document = parse_document({"schema_version": 1, "forwarding": value})
    assert not document.unknown
    assert document.to_mapping()["forwarding"] == value
    prefs = forwarding_from(document)
    assert prefs.auto_annotations and prefs.presets[0].retries == 3
    assert prefs.presets[0].transport is ForwardTransport.WEBSOCKET
    assert not prefs.for_context("production").auto_annotations
    assert prefs.for_context("production").presets[0].address == "::1"
    assert prefs.for_context("production-copy") is prefs
    assert forwarding_from(ConfigDocument()) == ForwardPreferences()
    assert parse_forwarding({}) == ForwardPreferences()


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unknown": True},
        {"schema_version": True},
        {"schema_version": 2},
        {"auto_annotations": "true"},
        {"presets": []},
        {"presets": {f"p{i}": {"ports": "80"} for i in range(33)}},
        {"presets": {"manual": {"ports": "80"}}},
        {"presets": {"annotation": {"ports": "80"}}},
        {"presets": {"bad": None}},
        {"presets": {"bad": {"ports": "80", "execute": "evil"}}},
        {"presets": {"bad": {"ports": "80", "transport": "udp"}}},
        {"presets": {"bad": {"ports": "80", "transport": {}}}},
        {"contexts": False},
        {"contexts": {str(i): {} for i in range(129)}},
        {"contexts": {"": {}}},
        {"contexts": {"x" * 254: {}}},
        {"contexts": {"bad\x1b": {}}},
        {"contexts": {1: {}}},
        {"contexts": {"owned": {"contexts": {}}}},
        {"contexts": {"owned": {"schema_version": 1}}},
    ],
)
def test_invalid_local_optin_or_preset_contract_fails_closed(value):
    with pytest.raises(AppError):
        parse_forwarding(value)
