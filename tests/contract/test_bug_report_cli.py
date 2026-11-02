"""Offline bug-report commands preserve preference precedence without TUI or SDK imports."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from kuberich.diagnostics.logging import LOG_HEADER

ROOT = Path(__file__).resolve().parents[2]
CHILD = r"""
import importlib.abc
import json
import os
import sys
sys.path.insert(0, sys.argv[1])
class OfflineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"textual", "kubernetes_asyncio"}:
            raise AssertionError("Offline bug-report imported TUI or Kubernetes SDK")
sys.meta_path.insert(0, OfflineImports())
forbidden = os.path.abspath(os.environ["KUBECONFIG"])
def no_kubeconfig_reads(event, arguments):
    if event in {"subprocess.Popen", "os.system", "os.exec"}:
        raise AssertionError("Offline bug-report executed a helper")
    if event == "open" and isinstance(arguments[0], (str, bytes, os.PathLike)):
        if os.path.abspath(os.fsdecode(arguments[0])) == forbidden:
            raise AssertionError("Offline bug-report read kubeconfig")
sys.addaudithook(no_kubeconfig_reads)
from kuberich.cli import main
raise SystemExit(main(json.loads(sys.argv[2])))
"""


def invoke(directory, arguments, *, environment=None):
    settings = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("KUBERICH_", "KUBETROL_", "KUBERNETES_"))
    }
    settings.update(
        {
            "HOME": str(directory / "home"),
            "XDG_CONFIG_HOME": str(directory / "config-home"),
            "XDG_STATE_HOME": str(directory / "state-home"),
            "XDG_DATA_HOME": str(directory / "data-home"),
            "KUBECONFIG": str(directory / "private-kubeconfig"),
        }
    )
    settings.update(environment or {})
    return subprocess.run(
        [sys.executable, "-I", "-c", CHILD, str(ROOT / "src"), json.dumps(arguments)],
        cwd=directory,
        env=settings,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def log(path, message):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(LOG_HEADER + message.encode() + b"\n")


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        ("default-missing", "missing"),
        ("valid", "valid"),
        ("invalid", "invalid"),
        ("explicit-missing", "invalid"),
        ("kubeconfig", "invalid"),
    ],
)
def test_report_works_offline_with_valid_missing_and_invalid_preferences(
    tmp_path, configuration, expected
):
    private = tmp_path / "private-kubeconfig"
    private.write_text("private-cluster-credentials-must-never-be-read")
    arguments = []
    config = tmp_path / "preferences.yaml"
    if configuration != "default-missing":
        arguments += ["--config", str(config)]
    if configuration == "valid":
        config.write_text("schema_version: 1\nprivate_extra: config-secret-marker\n")
    elif configuration == "invalid":
        config.write_text("token: [malformed-secret-marker\n")
    elif configuration == "kubeconfig":
        config.write_text("apiVersion: v1\nkind: Config\nusers: [private-auth-marker]\n")
    output = tmp_path / "report.json"
    result = invoke(tmp_path, [*arguments, "bug-report", "--output", str(output)])
    assert result.returncode == 0, result.stderr
    assert result.stderr == "" and str(output) in result.stdout
    report = json.loads(output.read_text())
    assert report["config_check"] == expected
    assert report["version"] and report["python"] and report["platform"]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not {"kubeconfig", "config", "settings", "preferences", "environment"} & report.keys()
    for secret in (
        "private-cluster-credentials",
        "config-secret-marker",
        "malformed-secret-marker",
        "private-auth-marker",
    ):
        assert secret not in output.read_text() + result.stdout + result.stderr
    assert private.read_text() == "private-cluster-credentials-must-never-be-read"


@pytest.mark.parametrize("selection", ["file", "current-env", "legacy-env", "both-env", "cli"])
def test_log_path_precedence_preserves_file_relative_and_cwd_relative_semantics(
    tmp_path, selection
):
    config = tmp_path / "preferences/config.yaml"
    config.parent.mkdir()
    config.write_text("schema_version: 1\nlog_file: relative.log\n")
    log(config.parent / "relative.log", "file-relative diagnostic")
    log(tmp_path / "relative.log", "cwd-relative diagnostic")
    log(tmp_path / "current.log", "current-environment diagnostic")
    log(tmp_path / "legacy.log", "legacy-environment diagnostic")
    log(tmp_path / "cli.log", "command-line diagnostic")
    environment = {}
    expected = "file-relative diagnostic"
    arguments = ["--config", str(config)]
    if selection in {"current-env", "both-env", "cli"}:
        environment["KUBERICH_LOG_FILE"] = "current.log"
        expected = "current-environment diagnostic"
    if selection in {"legacy-env", "both-env", "cli"}:
        environment["KUBETROL_LOG_FILE"] = "legacy.log"
        if selection == "legacy-env":
            expected = "legacy-environment diagnostic"
    if selection == "cli":
        arguments += ["--log-file", "cli.log"]
        expected = "command-line diagnostic"
    output = tmp_path / "report.json"
    result = invoke(
        tmp_path, [*arguments, "bug-report", "--output", str(output)], environment=environment
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(output.read_text())
    assert value["config_check"] == "valid"
    assert value["recent_log"] == {"status": "included", "text": expected + "\n"}


def test_invalid_runtime_settings_are_reported_without_echoing_the_input(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("schema_version: 1\n")
    output = tmp_path / "report.json"
    result = invoke(
        tmp_path,
        [
            "--config",
            str(config),
            "--log-level",
            "private-invalid-marker",
            "bug-report",
            "--output",
            str(output),
        ],
    )
    assert result.returncode == 0 and result.stderr == ""
    value = json.loads(output.read_text())
    assert value["config_check"] == "invalid"
    assert "private-invalid-marker" not in output.read_text() + result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["regular", "symlink", "fifo"])
def test_cli_refuses_existing_report_paths_without_modifying_the_target(tmp_path, kind):
    target = tmp_path / "target"
    target.write_text("previous-private-content")
    output = tmp_path / "report.json"
    if kind == "regular":
        output.write_text("keep existing report")
    elif kind == "symlink":
        output.symlink_to(target)
    else:
        os.mkfifo(output)
    before = output.lstat()
    result = invoke(tmp_path, ["bug-report", "--output", str(output)])
    assert result.returncode == 3 and result.stdout == ""
    assert "choose a new file" in result.stderr and "previous-private-content" not in result.stderr
    assert output.lstat() == before and target.read_text() == "previous-private-content"


def test_default_report_uses_its_own_state_directory_and_a_new_private_name(tmp_path):
    result = invoke(tmp_path, ["bug-report"])
    assert result.returncode == 0 and result.stderr == ""
    destination = Path(result.stdout.removeprefix("Created diagnostic report: ").strip())
    assert destination.is_relative_to(tmp_path)
    assert destination.name.startswith("kuberich-report-") and destination.suffix == ".json"
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert json.loads(destination.read_text())["config_check"] == "missing"


@pytest.mark.parametrize("selection", ["explicit", "current-env", "legacy-env"])
def test_invalid_preference_selection_still_reports_without_credentials_helpers_or_sdk(
    tmp_path, selection
):
    private = tmp_path / "private-kubeconfig"
    private.write_text("private-auth-marker-must-never-be-read")
    output = tmp_path / "report.json"
    arguments = ["--config", ""] if selection == "explicit" else []
    environment = (
        {}
        if selection == "explicit"
        else {"KUBERICH_CONFIG" if selection == "current-env" else "KUBETROL_CONFIG": ""}
    )
    result = invoke(
        tmp_path, [*arguments, "bug-report", "--output", str(output)], environment=environment
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == "" and str(output) in result.stdout
    value = json.loads(output.read_text())
    assert value["config_check"] == "invalid" and value["recent_log"] == {"status": "unavailable"}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert "private-auth-marker" not in output.read_text() + result.stdout + result.stderr
    assert private.read_text() == "private-auth-marker-must-never-be-read"
