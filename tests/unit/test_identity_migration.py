"""Actual preference compatibility, precedence and non-destructive migration."""

import json
import os
import stat
from pathlib import Path

import pytest

from kuberich import cli
from kuberich.config import paths
from kuberich.config.schema import ConfigDocument, resolve_settings
from kuberich.config.store import read_config
from kuberich.diagnostics.logging import diagnostic_logging


@pytest.fixture
def locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, Path]:
    monkeypatch.setattr(
        paths, "user_config_path", lambda app, **kwargs: tmp_path / "preferences" / app
    )
    return (
        tmp_path / "preferences" / "kubetrol" / "config.yaml",
        tmp_path / "preferences" / "kuberich" / "config.yaml",
    )


def legacy_file(source: Path, extra: str = "") -> bytes:
    content = (
        "theme: textual-light\nreadonly: true\nrefresh: 4.5\n"
        "opaque-private-field: private-value\n" + extra
    ).encode()
    source.parent.mkdir(parents=True)
    source.write_bytes(content)
    return content


@pytest.mark.parametrize("action", ["info", "config check"])
def test_legacy_defaults_are_read_without_creating_or_rewriting_files(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str], action: str
) -> None:
    source, destination = locations
    original = legacy_file(source, "log_file: logs/custom.log\n")
    assert cli.main(action.split()) == 0
    output = capsys.readouterr()
    assert "private-value" not in output.out + output.err
    if action == "info":
        information = json.loads(output.out)
        assert information["config_file"] == str(source)
        assert information["config_migration_target"] == str(destination)
        assert information["migration_pending"] and information["config_exists"]
        assert information["preferences"]["read_only"] is True
        assert information["preferences"]["refresh_seconds"] == 4.5
        assert information["preferences"]["theme"] == "textual-light"
        assert information["log_file"] == str(source.parent / "logs/custom.log")
    assert source.read_bytes() == original
    assert not destination.parent.exists()


@pytest.mark.parametrize("log_file", [None, "logs/custom.log", "/tmp/owned-explicit.log"])
def test_migration_preserves_source_unknown_fields_and_log_destination_and_is_idempotent(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str], log_file: str | None
) -> None:
    source, destination = locations
    original = legacy_file(source, f"log_file: {log_file}\n" if log_file else "")
    assert cli.main(["config", "migrate"]) == 0
    output = capsys.readouterr()
    assert "Original Kubetrol preferences were retained" in output.out
    assert "private-value" not in output.out + output.err
    document = read_config(destination)
    assert document.unknown == {"opaque-private-field": "private-value"}
    assert document.settings.read_only is True and document.settings.refresh_seconds == 4.5
    assert not document.migrated
    expected = (
        str(source.parent / log_file)
        if log_file is not None and not Path(log_file).is_absolute()
        else log_file
    )
    assert document.settings.log_file == expected
    assert source.read_bytes() == original
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    migrated = destination.read_bytes()
    assert cli.main(["config", "migrate"]) == 0
    assert "already exist" in capsys.readouterr().out
    assert destination.read_bytes() == migrated and source.read_bytes() == original
    assert cli.main(["info"]) == 0
    information = json.loads(capsys.readouterr().out)
    assert information["config_file"] == str(destination)
    assert not information["migration_pending"]
    assert information["config_migration_target"] is None


def test_new_preferences_win_over_existing_legacy_preferences(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, destination = locations
    original = legacy_file(source)
    destination.parent.mkdir()
    content = b"schema_version: 1\ntheme: k9s\nread_only: false\n"
    destination.write_bytes(content)
    assert cli.main(["info"]) == 0
    information = json.loads(capsys.readouterr().out)
    assert information["preferences"]["theme"] == "k9s"
    assert information["preferences"]["read_only"] is False
    assert cli.main(["config", "migrate"]) == 0
    assert "already exist" in capsys.readouterr().out
    assert destination.read_bytes() == content and source.read_bytes() == original


@pytest.mark.parametrize("kind", ["invalid", "symlink", "directory"])
def test_invalid_or_special_new_preferences_never_fall_back_to_legacy(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    source, destination = locations
    original = legacy_file(source)
    destination.parent.mkdir()
    if kind == "invalid":
        destination.write_text("secret: private-value\nmalformed: [")
    elif kind == "symlink":
        destination.symlink_to(destination.parent / "missing")
    else:
        destination.mkdir()
    location = paths.config_location(None, {})
    assert location.path == destination and location.migration_target is None
    assert cli.main(["info"]) in {2, 3}
    assert "private-value" not in capsys.readouterr().err
    assert source.read_bytes() == original


def test_dangling_legacy_symlink_is_reported_instead_of_becoming_defaults(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, destination = locations
    source.parent.mkdir(parents=True)
    source.symlink_to(source.parent / "missing")
    assert paths.config_location(None, {}).migration_target == destination
    assert cli.main(["config", "migrate"]) == 3
    assert "regular file" in capsys.readouterr().err
    assert not destination.exists()


def test_config_init_never_discards_legacy_preferences(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, destination = locations
    original = legacy_file(source)
    assert cli.main(["config", "init"]) == 3
    assert "never overwrites" in capsys.readouterr().err
    assert source.read_bytes() == original and not destination.exists()


def test_missing_legacy_config_does_not_create_an_empty_migration(
    locations: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    source, destination = locations
    assert cli.main(["config", "migrate"]) == 3
    assert "missing" in capsys.readouterr().err
    assert not source.exists() and not destination.exists()


def test_migration_race_never_overwrites_a_destination_created_during_commit(
    locations: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source, destination = locations
    original = legacy_file(source)
    competing = b"schema_version: 1\ntheme: k9s\n"
    link = os.link

    def race(temporary: Path, target: Path) -> None:
        assert target == destination
        destination.write_bytes(competing)
        link(temporary, target)

    monkeypatch.setattr(os, "link", race)
    assert cli.main(["config", "migrate"]) == 3
    assert "Cannot save preferences" in capsys.readouterr().err
    assert destination.read_bytes() == competing and source.read_bytes() == original
    assert not list(destination.parent.glob(".kuberich-*.tmp"))


@pytest.mark.parametrize("override", ["cli", "new-env", "old-env", "runtime"])
def test_migration_refuses_explicit_paths_or_runtime_overrides(
    locations: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    override: str,
) -> None:
    source, destination = locations
    original = legacy_file(source)
    arguments = ["config", "migrate"]
    if override == "cli":
        arguments = ["--config", str(source), *arguments]
    elif override == "runtime":
        arguments = ["--readonly", *arguments]
    else:
        monkeypatch.setenv(
            "KUBERICH_CONFIG" if override == "new-env" else "KUBETROL_CONFIG", str(source)
        )
    assert cli.main(arguments) == 2
    assert "without overrides" in capsys.readouterr().err
    assert source.read_bytes() == original and not destination.exists()


def test_config_environment_aliases_have_per_field_canonical_precedence(tmp_path: Path) -> None:
    old = tmp_path / "old.yaml"
    new = tmp_path / "new.yaml"
    environment = {"KUBETROL_CONFIG": str(old), "KUBERICH_CONFIG": str(new)}
    assert paths.config_location(None, environment).path == new
    assert paths.config_location(str(old), environment).path == old
    assert paths.config_location(None, {"KUBETROL_CONFIG": str(old)}).path == old
    settings = resolve_settings(
        ConfigDocument(),
        {
            "KUBETROL_THEME": "textual-light",
            "KUBETROL_REFRESH": "3.5",
            "KUBETROL_READONLY": "true",
            "KUBETROL_LOG_LEVEL": "DEBUG",
            "KUBETROL_LOG_FILE": "legacy.log",
            "KUBERICH_THEME": "k9s",
        },
        {},
    )
    assert settings.theme == "k9s" and settings.refresh_seconds == 3.5 and settings.read_only
    assert settings.log_level == "DEBUG" and settings.log_file == "legacy.log"


@pytest.mark.parametrize(
    "variable,value", [("REFRESH", "opaque-secret"), ("READONLY", "opaque-secret")]
)
def test_invalid_legacy_environment_values_are_safe_and_canonical_values_take_precedence(
    variable: str, value: str
) -> None:
    from kuberich.errors import AppError

    environment = {f"KUBETROL_{variable}": value}
    with pytest.raises(AppError) as error:
        resolve_settings(ConfigDocument(), environment, {})
    assert f"KUBETROL_{variable}" in str(error.value) and value not in str(error.value)
    environment[f"KUBERICH_{variable}"] = "4" if variable == "REFRESH" else "false"
    settings = resolve_settings(ConfigDocument(), environment, {})
    assert settings.refresh_seconds == 4 if variable == "REFRESH" else not settings.read_only


def test_legacy_relative_environment_log_path_is_relative_to_launch_directory(
    locations: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source, _ = locations
    legacy_file(source, "log_file: same.log\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KUBETROL_LOG_FILE", "same.log")
    assert cli.main(["info"]) == 0
    assert json.loads(capsys.readouterr().out)["log_file"] == str(tmp_path / "same.log")


def test_explicit_legacy_logs_lock_and_archives_remain_usable(tmp_path: Path) -> None:
    path = tmp_path / "legacy.log"
    path.write_bytes(b"# Kubetrol diagnostic log v1\nold message\n")
    path.with_name("legacy.log.lock").write_bytes(b"# Kubetrol diagnostic lock v1\n")
    path.with_name("legacy.log.1").write_bytes(b"# Kubetrol diagnostic log v1\narchive\n")
    with diagnostic_logging(path, "INFO") as logger:
        logger.info("new message")
    contents = path.read_text()
    assert contents.startswith("# Kubetrol diagnostic log v1\n")
    assert "old message" in contents and "new message" in contents
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
