"""User-visible local commands, failure codes and credential-free diagnostics."""

import json
import logging
from pathlib import Path

import pytest

from kuberich import cli
from kuberich.cli import main
from kuberich.config.schema import Settings
from kuberich.config.store import read_config


def test_info_reports_defaults_without_creating_files_or_reading_kubeconfig(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    kubeconfig = tmp_path / "sensitive-kubeconfig"
    original = "current-context: fixture\nusers: [{token: opaque-sensitive-token}]\n"
    kubeconfig.write_text(original)
    monkeypatch.setenv("KUBECONFIG", str(kubeconfig))
    assert main(["info"]) == 0
    output = capsys.readouterr()
    information = json.loads(output.out)
    assert information["version"] == cli.version("kuberich")
    assert information["config_file"] == str(tmp_path / "config/config.yaml")
    assert information["log_file"] == str(tmp_path / "logs/kuberich.log")
    assert information["preferences"]["theme"] == "k9s"
    assert not information["cluster_connected"] and information["terminal_ui_available"]
    assert not information["config_exists"] and not information["migration_pending"]
    assert information["dependencies"]["textual"]
    assert "opaque-sensitive-token" not in output.out and output.err == ""
    assert not (tmp_path / "config").exists() and not (tmp_path / "logs").exists()
    assert kubeconfig.read_text() == original


def test_info_omits_unknown_fields_and_reports_pending_migration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "theme: custom-theme\nopaque-private-field: private-value\nlog_file: logs/file.log\n"
    )
    assert main(["--config", str(path), "info"]) == 0
    information = json.loads(capsys.readouterr().out)
    assert information["migration_pending"]
    assert information["unknown_fields"] == 1
    assert information["log_file"] == str(tmp_path / "logs/file.log")
    assert information["preferences"]["theme"] == "custom-theme"
    assert "private-value" not in json.dumps(information)
    assert "opaque-private-field" not in json.dumps(information)


def test_init_and_check_are_safe_and_init_never_overwrites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config" / "config.yaml"
    assert main(["config", "init"]) == 0
    assert read_config(path).settings == Settings()
    contents = path.read_bytes()
    assert main(["config", "check"]) == 0
    assert "valid" in capsys.readouterr().out
    assert main(["config", "init"]) == 3
    assert "already exist" in capsys.readouterr().err
    assert path.read_bytes() == contents
    assert not (tmp_path / "logs").exists()


def test_explicit_missing_config_can_be_initialized_but_cannot_be_silently_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "explicit.yaml"
    assert main(["--config", str(path), "info"]) == 3
    assert "missing" in capsys.readouterr().err
    assert main(["--config", str(path), "config", "init"]) == 0
    assert path.is_file()


@pytest.mark.parametrize("flag", ["--log-file", "--log-level"])
def test_init_refuses_runtime_overrides_instead_of_ignoring_them(
    flag: str, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main([flag, "ignored-value", "config", "init"]) == 2
    assert "runtime overrides" in capsys.readouterr().err
    assert not (tmp_path / "config").exists()


def test_check_is_read_only_and_missing_default_uses_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["config", "check"]) == 0
    assert "No files were changed" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_cli_log_aliases_override_file_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("schema_version: 1\nlog_level: ERROR\nlog_file: file.log\n")
    monkeypatch.setenv("KUBERICH_CONFIG", str(path))
    monkeypatch.setenv("KUBERICH_LOG_LEVEL", "INFO")
    monkeypatch.setenv("KUBERICH_LOG_FILE", str(tmp_path / "env.log"))
    selected = tmp_path / "cli.log"
    monkeypatch.setattr(cli, "run_terminal", lambda settings, logger, **kwargs: None)
    assert main(["--logFile", str(selected), "-l", "DEBUG"]) == 0
    assert "Launching terminal interface" in selected.read_text()
    assert capsys.readouterr().err == ""
    assert not (tmp_path / "file.log").exists() and not (tmp_path / "env.log").exists()


def test_environment_relative_log_path_uses_working_directory_even_if_identical_to_file_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config/config.yaml"
    path.parent.mkdir()
    path.write_text("schema_version: 1\nlog_file: same.log\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KUBERICH_LOG_FILE", "same.log")
    assert main(["--config", str(path), "info"]) == 0
    assert json.loads(capsys.readouterr().out)["log_file"] == str(tmp_path / "same.log")


def test_malformed_config_error_has_no_contents_traceback_or_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("token: opaque-secret\nmalformed: [")
    assert main(["--config", str(path)]) == 2
    output = capsys.readouterr()
    assert "Invalid YAML" in output.err
    assert "opaque-secret" not in output.err and "Traceback" not in output.err
    assert output.out == "" and not (tmp_path / "logs").exists()


def test_command_line_errors_do_not_echo_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--token", "opaque-secret\x1b]52;clipboard\x07"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "opaque-secret" not in output.err and "clipboard" not in output.err
    assert "invalid command line" in output.err


@pytest.mark.parametrize("arguments", [["info", "--he"], ["config", "check", "--he"], ["config"]])
def test_subcommand_arguments_are_explicit_and_not_abbreviated(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert "invalid command line" in capsys.readouterr().err


def test_unexpected_runtime_failure_has_safe_console_message_and_debug_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken_launch(*args: object, **kwargs: object) -> None:
        raise RuntimeError("opaque-sensitive-runtime-data")

    monkeypatch.setenv("KUBERICH_LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(cli, "run_terminal", broken_launch)
    assert main([]) == 1
    assert "unexpected local failure" in capsys.readouterr().err
    contents = (tmp_path / "logs/kuberich.log").read_text()
    assert "exception=RuntimeError" in contents
    assert "opaque-sensitive-runtime-data" not in contents


def test_logging_failure_returns_io_code_without_raw_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise OSError("opaque-log-secret")

    monkeypatch.setenv("KUBERICH_LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(logging.Formatter, "formatTime", failed)
    assert main([]) == 3
    output = capsys.readouterr()
    assert "Cannot write diagnostic log" in output.err
    assert "opaque-log-secret" not in output.err


def test_interrupt_returns_130_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "read_config", interrupted)
    assert main(["config", "check"]) == 130
    assert capsys.readouterr().err == "kuberich: interrupted.\n"


def test_disconnected_terminal_returns_129_without_writing_to_closed_stderr(monkeypatch, capsys):
    from kuberich.errors import AppError, ExitCode

    def disconnected(*args, **kwargs):
        raise AppError("Terminal disconnected.", ExitCode.HANGUP)

    monkeypatch.setattr(cli, "run_terminal", disconnected)
    assert main([]) == 129
    output = capsys.readouterr()
    assert not output.out and not output.err


def test_info_omits_sensitive_shell_arguments_and_retains_only_safe_preferences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "preferences.yaml"
    contents = 'schema_version: 1\nshell: ["sh", "-c", "opaque-sensitive-shell-argument"]\n'
    path.write_text(contents)
    assert main(["--config", str(path), "info"]) == 0
    output = capsys.readouterr()
    assert "opaque-sensitive-shell-argument" not in output.out and not output.err
    assert set(json.loads(output.out)["preferences"]) == {
        "theme",
        "refresh_seconds",
        "read_only",
        "log_level",
    }
    assert path.read_text() == contents
