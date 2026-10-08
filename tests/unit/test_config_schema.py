"""Behavioral contracts for defaults, migrations, validation and layer precedence."""

from typing import Any

import pytest

from kuberich.config.schema import (
    ConfigDocument,
    Settings,
    parse_document,
    resolve_settings,
    settings_from,
)
from kuberich.errors import AppError


def test_defaults_and_unknown_fields_survive_a_round_trip() -> None:
    future = {"plugin_settings": {"bindings": ["a", "b"], "enabled": True}, "future_flag": None}
    document = parse_document({"schema_version": 1, **future})
    assert document.settings == Settings()
    assert document.unknown == future
    assert not document.migrated
    assert parse_document(document.to_mapping()) == document


@pytest.mark.parametrize("schema", [None, True, False, "1", 1.0, 2, -1])
def test_unsupported_schema_is_not_silently_downgraded(schema: object) -> None:
    with pytest.raises(AppError, match="Unsupported schema_version"):
        parse_document({"schema_version": schema})


@pytest.mark.parametrize("version", [None, 0])
def test_legacy_preferences_migrate_without_discarding_unknowns(version: int | None) -> None:
    data: dict[str, object] = {"refresh": 5, "readonly": True, "extra": [1, "two"]}
    if version is not None:
        data["schema_version"] = version
    document = parse_document(data)
    assert document.migrated
    assert document.settings.refresh_seconds == 5.0
    assert document.settings.read_only is True
    assert document.unknown == {"extra": [1, "two"]}
    assert document.to_mapping()["schema_version"] == 1
    assert "refresh" not in document.to_mapping()
    assert not parse_document(document.to_mapping()).migrated


def test_current_version_does_not_reinterpret_legacy_unknown_names() -> None:
    document = parse_document({"schema_version": 1, "readonly": "future_value"})
    assert document.settings.read_only is False
    assert document.unknown == {"readonly": "future_value"}


@pytest.mark.parametrize("old,new", [("refresh", "refresh_seconds"), ("readonly", "read_only")])
def test_conflicting_migration_names_are_rejected(old: str, new: str) -> None:
    with pytest.raises(AppError, match="cannot be combined"):
        parse_document({old: True, new: True})


@pytest.mark.parametrize("key", ["current-context", "clusters", "contexts", "users"])
def test_kubeconfig_is_never_treated_as_preferences(key: str) -> None:
    with pytest.raises(AppError, match="This is a kubeconfig"):
        parse_document({key: "private-cluster"})


def test_minimal_kubeconfig_is_also_rejected() -> None:
    with pytest.raises(AppError, match="This is a kubeconfig"):
        parse_document({"apiVersion": "v1", "kind": "Config"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("theme", 3),
        ("theme", ""),
        ("theme", "bad name"),
        ("theme", "a" * 65),
        ("refresh_seconds", "two"),
        ("refresh_seconds", True),
        ("refresh_seconds", 0.09),
        ("refresh_seconds", 3601),
        ("refresh_seconds", float("nan")),
        ("refresh_seconds", float("inf")),
        ("refresh_seconds", 10**1000),
        ("read_only", "true"),
        ("log_level", {}),
        ("log_level", "verbose"),
        ("log_file", 17),
        ("log_file", ""),
        ("log_file", "  "),
        ("log_file", "logs\x00secret"),
        ("log_file", "logs\x85secret"),
    ],
)
def test_invalid_values_name_the_field_without_echoing_input(field: str, value: object) -> None:
    with pytest.raises(AppError, match=field):
        settings_from({field: value})


@pytest.mark.parametrize(
    "values",
    [{"theme": 2}, {"refresh_seconds": True}, {"read_only": 1}, {"log_level": []}, {"log_file": 1}],
)
def test_direct_construction_is_also_validated(values: dict[str, Any]) -> None:
    with pytest.raises(AppError):
        Settings(**values)


@pytest.mark.parametrize("seconds", [0.1, 3600])
def test_refresh_boundary_is_inclusive(seconds: float) -> None:
    assert settings_from({"refresh_seconds": seconds}).refresh_seconds == seconds


def test_every_environment_preference_is_applied_before_cli_overrides() -> None:
    document = parse_document({"schema_version": 1, "theme": "file-theme", "refresh_seconds": 10})
    environment = {
        "KUBERICH_THEME": "env-theme",
        "KUBERICH_REFRESH": "3.5",
        "KUBERICH_READONLY": "TRUE",
        "KUBERICH_LOG_LEVEL": "DEBUG",
        "KUBERICH_LOG_FILE": "env.log",
        "AWS_SECRET_ACCESS_KEY": "ignored",
    }
    settings = resolve_settings(
        document, environment, {"theme": "cli-theme", "log_file": "cli.log"}
    )
    assert settings == Settings("cli-theme", 3.5, True, "DEBUG", "cli.log")
    assert document.settings.theme == "file-theme"
    assert resolve_settings(ConfigDocument(), {"KUBERICH_READONLY": "false"}, {}).read_only is False


@pytest.mark.parametrize(
    "variable,value,message",
    [
        ("KUBERICH_REFRESH", "Bearer secret", "must be a number"),
        ("KUBERICH_READONLY", "yes", "must be true or false"),
        ("KUBERICH_THEME", "", "theme must"),
        ("KUBERICH_LOG_LEVEL", "token=secret", "log_level must"),
        ("KUBERICH_LOG_FILE", "", "log_file must"),
    ],
)
def test_invalid_environment_does_not_echo_values(variable: str, value: str, message: str) -> None:
    with pytest.raises(AppError, match=message) as error:
        resolve_settings(ConfigDocument(), {variable: value}, {})
    assert "secret" not in str(error.value)


def test_invalid_environment_is_not_masked_by_a_valid_cli_override() -> None:
    with pytest.raises(AppError, match="log_level"):
        resolve_settings(ConfigDocument(), {"KUBERICH_LOG_LEVEL": "invalid"}, {"log_level": "INFO"})


def test_unknown_override_is_rejected() -> None:
    with pytest.raises(AppError, match="Unknown preference override"):
        resolve_settings(ConfigDocument(), {}, {"token": "secret"})


def test_file_environment_and_cli_levels_accept_common_lowercase_spelling() -> None:
    document = parse_document({"schema_version": 1, "log_level": "warning"})
    assert document.settings.log_level == "WARNING"
    settings = resolve_settings(document, {"KUBERICH_LOG_LEVEL": "debug"}, {"log_level": "info"})
    assert settings.log_level == "INFO"
