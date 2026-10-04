"""Path precedence and origin-specific relative path resolution."""

from pathlib import Path

import pytest

from kubetrol.config.paths import config_location, log_location, preference_path
from kubetrol.config.schema import Settings
from kubetrol.errors import AppError


def test_config_selection_prefers_cli_then_environment_then_platform(tmp_path: Path) -> None:
    environment = {"KUBETROL_CONFIG": str(tmp_path / "env.yaml"), "KUBECONFIG": "never-read"}
    cli = config_location(str(tmp_path / "cli.yaml"), environment)
    assert cli.path == tmp_path / "cli.yaml" and cli.explicit
    env = config_location(None, environment)
    assert env.path == tmp_path / "env.yaml" and env.explicit
    default = config_location(None, {})
    assert default.path == tmp_path / "config" / "config.yaml" and not default.explicit
    assert not default.path.parent.exists()


def test_tilde_spaces_and_relative_paths_resolve_without_creating_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    assert preference_path("relative path/config.yaml") == tmp_path / "relative path/config.yaml"
    assert preference_path("~/kubetrol") == Path.home() / "kubetrol"
    assert not (tmp_path / "relative path").exists()


@pytest.mark.parametrize("value", ["", " ", "path\nsecret", "path\x7f", "path\x9f"])
def test_invalid_path_is_not_echoed(value: str) -> None:
    with pytest.raises(AppError, match="Preference paths") as error:
        preference_path(value)
    assert "secret" not in str(error.value)


def test_home_resolution_error_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(self: Path) -> Path:
        raise RuntimeError("credentials=hidden")

    monkeypatch.setattr(Path, "expanduser", unavailable)
    with pytest.raises(AppError, match="Cannot resolve") as error:
        preference_path("~/config.yaml")
    assert "hidden" not in str(error.value)


def test_file_log_paths_use_config_directory_and_overrides_use_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "settings" / "config.yaml"
    relative = Settings(log_file="logs/local.log")
    assert log_location(relative, config, from_file=True) == config.parent / "logs/local.log"
    assert log_location(relative, config, from_file=False) == tmp_path / "logs/local.log"
    absolute = Settings(log_file=str(tmp_path / "absolute.log"))
    assert log_location(absolute, config, from_file=True) == tmp_path / "absolute.log"
    assert log_location(Settings(), config, from_file=True) == tmp_path / "logs/kubetrol.log"
