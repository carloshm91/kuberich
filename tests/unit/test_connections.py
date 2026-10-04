"""Connection selection validates operator input without loading credentials."""

from dataclasses import replace

import pytest

from kubetrol.domain.connections import ConnectionRequest, namespace_name, request_duration
from kubetrol.errors import AppError


@pytest.mark.parametrize(
    "value,seconds",
    [("10", 10), ("0.1s", 0.1), ("100ms", 0.1), ("2m", 120), ("1h", 3600), ("1.5", 1.5)],
)
def test_timeout_duration_units(value: str, seconds: float) -> None:
    assert request_duration(value) == seconds


@pytest.mark.parametrize(
    "value", ["0", "1ms", "3601", "NaN", "inf", "-1s", "1d", "", "1e5", "9" * 400]
)
def test_unbounded_or_ambiguous_durations_are_rejected(value: str) -> None:
    with pytest.raises(AppError):
        request_duration(value)


@pytest.mark.parametrize("value", ["default", "a", "kube-system", "a" * 63, "one-2"])
def test_valid_namespace_labels(value: str) -> None:
    assert namespace_name(value) == value


@pytest.mark.parametrize("value", ["", "A", "a.b", "-a", "a-", "a_b", "a" * 64, "a\n", "a b"])
def test_namespace_scope_rejects_invalid_labels(value: str) -> None:
    with pytest.raises(AppError):
        namespace_name(value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kubeconfig": ""},
        {"context": "\x1b"},
        {"namespace": "bad!"},
        {"all_namespaces": 1},
        {"timeout": True},
        {"timeout": float("nan")},
        {"timeout": 0},
        {"timeout": 3601},
        {"namespace": "default", "all_namespaces": True},
    ],
)
def test_invalid_request_cannot_reach_a_transport(overrides: dict) -> None:
    with pytest.raises(AppError):
        replace(ConnectionRequest(), **overrides)


def test_explicit_valid_request_is_immutable() -> None:
    request = ConnectionRequest("/tmp/config", "chosen", "team", timeout=3)
    assert request.timeout == 3 and request.context == "chosen"
