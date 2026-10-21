"""Per-context settings tighten a session; flags and environment keep precedence."""

import asyncio
from pathlib import Path

import pytest

from kuberich.config.context_settings import (
    ContextOverride,
    ContextSettings,
    context_settings_from,
    parse_context_settings,
)
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings, parse_document
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.ui.config_check import unsupported_fields


def test_context_overrides_follow_flag_environment_context_file_precedence():
    value = parse_context_settings(
        {
            "schema_version": 1,
            "contexts": {
                "prod": {"read_only": True, "refresh_seconds": 5},
                "lab": {"refresh_seconds": 1},
            },
        }
    )
    assert value.contexts == (
        ("lab", ContextOverride(False, 1.0)),
        ("prod", ContextOverride(True, 5.0)),
    )
    settings = Settings(refresh_seconds=2)
    assert value.effective(settings, (), "prod") == (True, 5.0)
    assert value.effective(settings, ("refresh_seconds",), "prod") == (True, 2.0)
    assert value.effective(settings, (), "lab") == (False, 1.0)
    assert value.effective(settings, (), "other") == (False, 2.0)
    assert value.effective(settings, (), None) == (False, 2.0)
    assert parse_context_settings({}) == ContextSettings()
    assert context_settings_from(ConfigDocument()) == ContextSettings()
    document = parse_document(
        {"schema_version": 1, "context_settings": {"contexts": {"a": {"read_only": True}}}}
    )
    assert context_settings_from(document).effective(settings, (), "a") == (True, 2.0)


@pytest.mark.parametrize(
    "value, message",
    [
        ([], "only schema_version and contexts"),
        ({"other": 1}, "only schema_version and contexts"),
        ({"schema_version": 2}, "schema_version"),
        ({"schema_version": True}, "schema_version"),
        ({"contexts": []}, "at most 128"),
        ({"contexts": {str(n): {"read_only": True} for n in range(129)}}, "at most 128"),
        ({"contexts": {1: {"read_only": True}}}, "bounded text"),
        ({"contexts": {"": {"read_only": True}}}, "bounded text"),
        ({"contexts": {"a" * 254: {"read_only": True}}}, "bounded text"),
        ({"contexts": {"bad\x1b": {"read_only": True}}}, "bounded text"),
        ({"contexts": {"a": {}}}, "only read_only and refresh_seconds"),
        ({"contexts": {"a": []}}, "only read_only and refresh_seconds"),
        ({"contexts": {"a": {"theme": "k9s"}}}, "only read_only and refresh_seconds"),
        ({"contexts": {"a": {"read_only": False}}}, "cannot turn read-only off"),
        ({"contexts": {"a": {"read_only": "true"}}}, "cannot turn read-only off"),
        ({"contexts": {"a": {"refresh_seconds": True}}}, "between 0.1 and 3600"),
        ({"contexts": {"a": {"refresh_seconds": "5"}}}, "between 0.1 and 3600"),
        ({"contexts": {"a": {"refresh_seconds": 0}}}, "between 0.1 and 3600"),
        ({"contexts": {"a": {"refresh_seconds": 10**400}}}, "between 0.1 and 3600"),
        ({"contexts": {"a": {"refresh_seconds": float("nan")}}}, "between 0.1 and 3600"),
    ],
)
def test_context_settings_are_strict(value, message):
    with pytest.raises(AppError, match=message):
        parse_context_settings(value)


def test_preference_source_keeps_startup_precedence_and_refuses_stale_replacement(tmp_path: Path):
    document = parse_document({"schema_version": 1, "refresh_seconds": 3})
    source = PreferenceSource(
        ConfigLocation(tmp_path / "p.yaml", True),
        document,
        environment={"KUBETROL_READONLY": "true", "HOME": "/x"},
        overrides={"refresh_seconds": 7.0},
    )
    assert source.pinned == {"read_only", "refresh_seconds"}
    assert source.settings(document) == Settings(refresh_seconds=7.0, read_only=True)
    assert PreferenceSource(source.location, document).pinned == frozenset()
    updated = parse_document({"schema_version": 1})

    async def replace():
        assert not await source.replace(updated, ConfigDocument())
        assert source.document is document
        assert await source.replace(updated, document)
        assert source.document is updated

    asyncio.run(replace())
    assert "HOME" not in repr(source)


def test_unsupported_fields_are_named_bounded_and_escaped():
    assert unsupported_fields(ConfigDocument()) is None
    document = parse_document({"schema_version": 1, "zeta": 1, "alpha\x1b": 2})
    assert unsupported_fields(document) == (
        "Unsupported preference fields are kept but ignored: alpha\\u001b, zeta."
    )
    many = parse_document({"schema_version": 1, **{f"f{n:02}": n for n in range(10)}})
    assert unsupported_fields(many).endswith("f07 and 2 more.")
