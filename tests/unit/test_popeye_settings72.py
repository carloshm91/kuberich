"""Offline bounded executable selection and explicit local trust classification."""

from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.config.popeye import (
    POPEYE_SECTIONS,
    PopeyeSettings,
    parse_popeye_settings,
    serialize_popeye_settings,
)
from kuberich.errors import AppError


def test_defaults_explicit_disable_and_round_trip_are_offline():
    assert parse_popeye_settings(None) is None
    assert serialize_popeye_settings(None) is None
    value = parse_popeye_settings({"executable": "/owned/popeye"})
    assert value == PopeyeSettings(Path("/owned/popeye"))
    assert (
        not value.trusted_read_only and value.sections == ("pods",) and value.timeout_seconds == 60
    )
    assert parse_popeye_settings(serialize_popeye_settings(value)) == value
    changed = replace(
        value, sections=("pods", "deployments"), trusted_read_only=True, timeout_seconds=120
    )
    assert parse_popeye_settings(serialize_popeye_settings(changed)) == changed
    assert {"cluster", "gateways", "podmetrics", "persistentvolumeclaims"} <= POPEYE_SECTIONS


@pytest.mark.parametrize(
    "value",
    [
        [],
        "popeye",
        {},
        {"executable": 5},
        {"executable": "relative"},
        {"executable": "/p", "args": []},
        {"executable": "/p", "sections": "pods"},
    ],
)
def test_invalid_raw_configuration_fails_offline(value):
    with pytest.raises(AppError):
        parse_popeye_settings(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"executable": "/p"},
        {"executable": Path("relative")},
        {"executable": Path("/" + "x" * 4096)},
        {"executable": Path("/owned/\x1bp")},
        {"sections": []},
        {"sections": ()},
        {"sections": ("pods",) * 17},
        {"sections": ("pods", "pods")},
        {"sections": ("PODS",)},
        {"sections": ([],)},
        {"sections": ("pods", 3)},
        {"timeout_seconds": True},
        {"timeout_seconds": 0},
        {"timeout_seconds": 121},
        {"timeout_seconds": 1.5},
        {"trusted_read_only": 1},
    ],
)
def test_settings_direct_construction_enforces_the_same_contract(changes):
    with pytest.raises(AppError):
        PopeyeSettings(**{"executable": Path("/owned/popeye"), **changes})
