"""Offline configuration bounds for explicit privileged node diagnostics."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from kuberich.config.node_shell import (
    NodeShellResources,
    NodeShellSettings,
    node_shell_from,
    parse_node_shell,
    serialize_node_shell,
)
from kuberich.config.schema import parse_document
from kuberich.errors import AppError

IMAGE = "registry.example.test:5000/tools/node:v1@sha256:" + "a" * 64


def test_disabled_legacy_configuration_and_explicit_round_trip() -> None:
    old = parse_document({"schema_version": 1, "unrelated": "kept"})
    settings = node_shell_from(old)
    assert not settings.enabled and settings.image is None and settings.namespace is None
    assert settings.requests == NodeShellResources("10m", "32Mi")
    assert settings.limits == NodeShellResources("250m", "128Mi")
    assert (settings.startup_timeout_seconds, settings.session_timeout_seconds) == (60, 3600)
    raw = {
        "enabled": True,
        "namespace": "diagnostics",
        "image": IMAGE,
        "requests": {"cpu": "100m", "memory": "64Mi"},
        "limits": {"cpu": "1", "memory": "1Gi"},
    }
    document = parse_document({"schema_version": 1, "node_shell": raw, "future": 7})
    assert document.unknown == {"future": 7}
    assert document.to_mapping()["node_shell"] == raw
    enabled = node_shell_from(document)
    assert enabled.enabled and enabled.namespace == "diagnostics" and enabled.image == IMAGE
    assert enabled.requests.to_mapping() == raw["requests"]
    assert parse_node_shell(serialize_node_shell(enabled)) == enabled
    assert enabled.to_mapping() == serialize_node_shell(enabled)
    assert parse_node_shell({}) == settings
    with pytest.raises(FrozenInstanceError):
        enabled.enabled = False  # type: ignore[misc]


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "yes",
        {"extra": 1},
        {"schema_version": True},
        {"schema_version": 2},
        {"enabled": 1},
        {"enabled": "yes"},
        {"enabled": True},
        {"enabled": True, "image": IMAGE},
        {"enabled": True, "namespace": "default"},
    ],
)
def test_invalid_extensions_are_not_silently_enabled(raw: object) -> None:
    with pytest.raises(AppError):
        parse_node_shell(raw)


@pytest.mark.parametrize(
    "image",
    [
        True,
        7,
        "",
        "alpine",
        "alpine:latest",
        "https://r/x@sha256:" + "a" * 64,
        "x@sha256:" + "a" * 63,
        "x@sha256:" + "z" * 64,
        "x@sha256:" + "a" * 64 + "\n",
        "x\x1b@sha256:" + "a" * 64,
        "-x@sha256:" + "a" * 64,
        "x//y@sha256:" + "a" * 64,
        "x" * 513 + "@sha256:" + "a" * 64,
    ],
)
def test_image_requires_one_exact_digest_reference(image: Any) -> None:
    with pytest.raises(AppError):
        NodeShellSettings(image=image)


@pytest.mark.parametrize("namespace", [True, 7, "", "UPPER", "has.dot", "a" * 64, "x\n"])
def test_namespace_requires_an_explicit_dns_label(namespace: Any) -> None:
    with pytest.raises(AppError):
        NodeShellSettings(namespace=namespace)


@pytest.mark.parametrize(
    "key,value",
    [
        ("cpu", "0"),
        ("cpu", "-1"),
        ("cpu", "8.001"),
        ("cpu", True),
        ("cpu", "\x1b1"),
        ("cpu", "inf"),
        ("cpu", "1e999"),
        ("memory", "0"),
        ("memory", "-1Mi"),
        ("memory", "8193Mi"),
        ("memory", None),
        ("memory", "1Gi\n"),
    ],
)
def test_resource_bounds_reject_invalid_quantities(key: str, value: Any) -> None:
    values = {"cpu": "1", "memory": "1Gi", key: value}
    with pytest.raises(AppError):
        NodeShellResources(**values)


@pytest.mark.parametrize(
    "key,value",
    [
        ("requests", {}),
        ("limits", {"cpu": "1"}),
        ("requests", {"cpu": "1", "memory": "1Gi", "gpu": "1"}),
        ("limits", []),
        ("requests", {"cpu": "1", "memory": "64Mi"}),
        ("limits", {"cpu": "1m", "memory": "16Mi"}),
        ("startup_timeout_seconds", True),
        ("startup_timeout_seconds", 4),
        ("startup_timeout_seconds", 301),
        ("startup_timeout_seconds", 5.0),
        ("session_timeout_seconds", False),
        ("session_timeout_seconds", 59),
        ("session_timeout_seconds", 3601),
        ("session_timeout_seconds", "60"),
    ],
)
def test_settings_reject_wrong_resource_shapes_order_and_timeouts(key: str, value: Any) -> None:
    with pytest.raises(AppError):
        parse_node_shell({key: value})


def test_resource_constructor_types_and_both_request_orderings() -> None:
    with pytest.raises(AppError):
        NodeShellSettings(requests={"cpu": "1", "memory": "1Gi"})  # type: ignore[arg-type]
    with pytest.raises(AppError):
        NodeShellSettings(limits=None)  # type: ignore[arg-type]
    with pytest.raises(AppError):
        NodeShellSettings(requests=NodeShellResources("10m", "256Mi"))
    maximum = NodeShellResources("8", "8Gi")
    assert (
        parse_node_shell(
            {
                "requests": maximum.to_mapping(),
                "limits": maximum.to_mapping(),
                "startup_timeout_seconds": 5,
                "session_timeout_seconds": 60,
            }
        ).limits
        == maximum
    )
    assert NodeShellSettings(startup_timeout_seconds=300).startup_timeout_seconds == 300
