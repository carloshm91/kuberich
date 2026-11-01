"""Public bug-report commands write real private bundles under normal coverage."""

import json
import os
import stat
from pathlib import Path

import pytest

from kuberich.cli import main
from kuberich.config.paths import config_location
from kuberich.diagnostics import reports
from kuberich.diagnostics.logging import LOG_HEADER


@pytest.fixture(autouse=True)
def report_environment(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith(("KUBERICH_", "KUBETROL_")):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state-home"))
    monkeypatch.setattr(reports, "user_state_path", lambda *args, **kwargs: tmp_path / "state")
    assert config_location(None, os.environ).path.is_relative_to(tmp_path)


@pytest.mark.parametrize(
    ("preferences", "expected"),
    [
        ("valid", "valid"),
        ("invalid", "invalid"),
        ("explicit-missing", "invalid"),
        ("default-missing", "missing"),
    ],
)
def test_command_writes_status_without_exposing_preferences_or_error_values(
    tmp_path, capsys, preferences, expected
):
    config = tmp_path / "preferences.yaml"
    arguments = [] if preferences == "default-missing" else ["--config", str(config)]
    if preferences == "valid":
        config.write_text("schema_version: 1\nprivate_note: private-config-marker\n")
    elif preferences == "invalid":
        config.write_text("token: [private-malformed-marker\n")
    output = tmp_path / "report.json"
    assert main([*arguments, "bug-report", "--output", str(output)]) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and str(output) in captured.out
    value = json.loads(output.read_text())
    assert value["config_check"] == expected
    assert value["schema_version"] == 1 and value["version"] and value["python"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "private-config-marker" not in output.read_text() + captured.out
    assert "private-malformed-marker" not in output.read_text() + captured.out
    assert not {"settings", "preferences", "kubeconfig", "environment"} & value.keys()


@pytest.mark.parametrize("source", ["file", "current-env", "legacy-env", "both-env", "cli"])
def test_command_reads_the_effective_log_with_real_file_environment_and_cli_precedence(
    tmp_path, monkeypatch, capsys, source
):
    config = tmp_path / "preferences/config.yaml"
    config.parent.mkdir()
    config.write_text("schema_version: 1\nlog_file: file.log\n")
    messages = {
        config.parent / "file.log": "file-relative event",
        tmp_path / "current.log": "current-environment event",
        tmp_path / "legacy.log": "legacy-environment event",
        tmp_path / "cli.log": "command-line event",
    }
    for path, message in messages.items():
        path.write_bytes(LOG_HEADER + f"{message}\npassword=private-log-marker\n".encode())
    arguments = ["--config", str(config)]
    expected = "file-relative event"
    if source in {"current-env", "both-env", "cli"}:
        monkeypatch.setenv("KUBERICH_LOG_FILE", "current.log")
        expected = "current-environment event"
    if source in {"legacy-env", "both-env", "cli"}:
        monkeypatch.setenv("KUBETROL_LOG_FILE", "legacy.log")
        if source == "legacy-env":
            expected = "legacy-environment event"
    if source == "cli":
        arguments += ["--log-file", "cli.log"]
        expected = "command-line event"
    output = tmp_path / "report.json"
    assert main([*arguments, "bug-report", "--output", str(output)]) == 0
    value = json.loads(output.read_text())
    assert value["config_check"] == "valid"
    assert value["recent_log"]["status"] == "included"
    assert value["recent_log"]["text"] == f"{expected}\npassword=[REDACTED]\n"
    captured = capsys.readouterr()
    assert captured.err == "" and "private-log-marker" not in captured.out + output.read_text()


def test_command_can_report_invalid_common_overrides_without_echoing_them(tmp_path, capsys):
    config = tmp_path / "preferences.yaml"
    config.write_text("schema_version: 1\n")
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "--config",
                str(config),
                "--log-level",
                "private-invalid-level",
                "bug-report",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["config_check"] == "invalid"
    captured = capsys.readouterr()
    assert captured.err == "" and "private-invalid-level" not in captured.out + output.read_text()


def test_command_creates_a_new_report_in_its_selected_state_directory(tmp_path, capsys):
    assert main(["bug-report"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    destination = Path(captured.out.removeprefix("Created diagnostic report: ").strip())
    assert destination.parent == tmp_path / "state/reports"
    assert destination.name.startswith("kuberich-report-")
    assert json.loads(destination.read_text())["config_check"] == "missing"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_command_refuses_existing_reports_with_a_safe_exit_and_preserves_bytes(tmp_path, capsys):
    output = tmp_path / "report.json"
    output.write_text("previous-private-report")
    assert main(["bug-report", "--output", str(output)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "choose a new file" in captured.err
    assert "previous-private-report" not in captured.err
    assert output.read_text() == "previous-private-report"


@pytest.mark.parametrize("selection", ["explicit", "current-env", "legacy-env"])
def test_report_describes_an_invalid_preference_selection_with_a_private_bundle(
    tmp_path, monkeypatch, capsys, selection
):
    arguments = []
    if selection == "explicit":
        arguments = ["--config", ""]
    else:
        monkeypatch.setenv(
            "KUBERICH_CONFIG" if selection == "current-env" else "KUBETROL_CONFIG", ""
        )
    output = tmp_path / "report.json"
    assert main([*arguments, "bug-report", "--output", str(output)]) == 0
    value = json.loads(output.read_text())
    assert value["config_check"] == "invalid"
    assert value["recent_log"] == {"status": "unavailable"}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    captured = capsys.readouterr()
    assert captured.err == "" and str(output) in captured.out


@pytest.mark.parametrize("selection", ["explicit", "current-env", "legacy-env"])
@pytest.mark.parametrize("command", [["info"], ["config", "check"]])
def test_other_commands_still_refuse_an_invalid_preference_selection(
    tmp_path, monkeypatch, capsys, selection, command
):
    arguments = []
    if selection == "explicit":
        arguments = ["--config", ""]
    else:
        monkeypatch.setenv(
            "KUBERICH_CONFIG" if selection == "current-env" else "KUBETROL_CONFIG", ""
        )
    assert main([*arguments, *command]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "Preference paths must be nonempty" in captured.err
    assert not (tmp_path / "state/reports").exists()


@pytest.mark.parametrize("destination", ["empty", "existing"])
def test_invalid_selection_does_not_relax_report_destination_validation(
    tmp_path, monkeypatch, capsys, destination
):
    monkeypatch.setenv("KUBERICH_CONFIG", "")
    output = tmp_path / "report.json"
    if destination == "existing":
        output.write_text("previous-private-report")
    if destination == "empty":
        with pytest.raises(SystemExit) as caught:
            main(["bug-report", "--output", ""])
        assert caught.value.code == 2
    else:
        assert main(["bug-report", "--output", str(output)]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err
    if destination == "existing":
        assert output.read_text() == "previous-private-report"
    else:
        assert not output.exists()
