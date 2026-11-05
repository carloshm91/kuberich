"""Local browsing starts from the CLI; selected-source exports stay interactive."""

import pytest

from kuberich import cli
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService


@pytest.mark.parametrize("read_only", [False, True])
def test_export_commands_are_local_read_actions_with_no_path_grammar(read_only):
    service = CommandService(AccessPolicy(read_only))
    assert service.resolve(":export") is Command.EXPORT
    assert service.resolve(":exports") is Command.EXPORTS
    from kuberich.errors import AppError

    for text in ("export file.yaml", "exports /tmp/elsewhere"):
        with pytest.raises(AppError, match="without arguments"):
            service.resolve(text)


def test_cli_exports_dispatches_the_offline_startup_view(tmp_path, monkeypatch, capsys):
    calls = []
    (tmp_path / "preferences.yaml").write_text("schema_version: 1\n")
    monkeypatch.setattr(cli, "run_terminal", lambda *args, **kwargs: calls.append(kwargs))
    assert (
        cli.main(
            [
                "--config",
                str(tmp_path / "preferences.yaml"),
                "--log-file",
                str(tmp_path / "owned.log"),
                "--command",
                "exports",
            ]
        )
        == 0
    )
    assert len(calls) == 1 and calls[0]["initial_command"] is Command.EXPORTS
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command", ["export", "diagnose"])
def test_cli_rejects_selected_read_actions_before_launch(tmp_path, monkeypatch, capsys, command):
    calls = []
    (tmp_path / "preferences.yaml").write_text("schema_version: 1\n")
    monkeypatch.setattr(cli, "run_terminal", lambda *args, **kwargs: calls.append(kwargs))
    assert cli.main(["--config", str(tmp_path / "preferences.yaml"), "--command", command]) != 0
    assert not calls
    assert "interactive resource selection" in capsys.readouterr().err


@pytest.mark.parametrize(
    "selected", ["relative/exports", "~/owned-exports", "../preserved-exports"]
)
def test_export_directory_crosses_real_bootstrap_and_launch_without_directory_io(
    tmp_path, monkeypatch, selected
):
    import io
    import logging
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from kuberich.config.catalog import KubeCatalog
    from kuberich.ui import launch

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    captures = []

    class App:
        return_code = 0
        navigation = SimpleNamespace(mouse=False)

        def __init__(self, settings, logger, **kwargs):
            assert isinstance(logger, logging.Logger)
            captures.append(kwargs)

        def run(self, *, mouse):
            assert mouse is False

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(launch, "KubeRichApp", App)
    monkeypatch.setattr(launch, "load_catalog", lambda *args: KubeCatalog())
    preferences = tmp_path / "preferences.yaml"
    contents = "schema_version: 1\n"
    preferences.write_text(contents)
    assert (
        cli.main(
            [
                "--config",
                str(preferences),
                "--log-file",
                str(tmp_path / "owned.log"),
                "--screen-dump-dir",
                "unused",
                "--screen-dump-dir",
                selected,
                "--command",
                "exports",
            ]
        )
        == 0
    )
    expected = Path(selected).expanduser()
    if not expected.is_absolute():
        expected = tmp_path / expected
    assert captures[0]["export_directory"] == expected
    assert captures[0]["initial_command"] is Command.EXPORTS
    assert not expected.exists() and not (tmp_path / "unused").exists()
    assert preferences.read_text() == contents


@pytest.mark.parametrize(
    "command",
    [
        ["info"],
        ["config", "check"],
        ["config", "init"],
        ["config", "migrate"],
        ["bug-report"],
        ["help"],
        ["version"],
        ["kubeconfig", "oidc-migration"],
    ],
)
def test_export_directory_is_terminal_only_and_rejected_before_io(
    tmp_path, monkeypatch, capsys, command
):
    def forbidden(*args, **kwargs):
        pytest.fail("Terminal-only export settings reached local I/O or launch")

    monkeypatch.setattr(cli, "read_config", forbidden)
    monkeypatch.setattr(cli, "diagnostic_logging", forbidden)
    monkeypatch.setattr(cli, "run_terminal", forbidden)
    target = tmp_path / "opaque-export-value"
    assert cli.main(["--screen-dump-dir", str(target), *command]) == 2
    result = capsys.readouterr()
    assert result.out == "" and "opaque-export-value" not in result.err
    assert "unavailable" not in result.err and not target.exists()


@pytest.mark.parametrize("value", ["", "bad\nvalue", "bad\x1b]52;c;opaque-value\x07"])
def test_export_directory_hostile_syntax_does_not_echo_or_load_preferences(
    value, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "read_config", lambda *args, **kwargs: pytest.fail("Loaded preferences")
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--screen-dump-dir", value])
    assert stopped.value.code == 2
    output = capsys.readouterr()
    assert "invalid command line" in output.err and "opaque-value" not in output.err


def test_directory_capture_is_lexical_and_preserves_parent_components(tmp_path, monkeypatch):
    from pathlib import Path

    from kuberich.config.launch import capture_export_directory

    monkeypatch.setenv("HOME", str(tmp_path))

    def forbidden(*args, **kwargs):
        pytest.fail("Lexical capture attempted directory I/O or normalization")

    for name in ("stat", "exists", "resolve", "mkdir"):
        monkeypatch.setattr(Path, name, forbidden)
    assert (
        capture_export_directory(Path("relative/../missing"), tmp_path)
        == tmp_path / "relative/../missing"
    )
    assert capture_export_directory(Path("~/exports"), tmp_path) == tmp_path / "exports"
    assert capture_export_directory(tmp_path / "absolute", tmp_path) == tmp_path / "absolute"


def test_directory_home_expansion_failure_is_safe_before_launch(tmp_path, monkeypatch, capsys):
    from pathlib import Path

    def refused(path):
        raise RuntimeError("opaque-home-value")

    monkeypatch.setattr(Path, "expanduser", refused)
    assert cli.main(["--screen-dump-dir", "~/owned"]) == 2
    error = capsys.readouterr().err
    assert "Cannot capture" in error and "opaque-home-value" not in error
    assert not list(tmp_path.iterdir())


def test_rejected_export_directory_keeps_fresh_offline_imports_light(tmp_path):
    import subprocess
    import sys

    from tests.support.distribution import clean_environment

    script = """
import importlib.abc
import sys
class Offline(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'textual', 'kubernetes_asyncio'} or fullname in {'kuberich.domain.exports', 'kuberich.adapters.artifact_files'}:
            raise AssertionError('Offline export-path rejection imported terminal or export adapters')
sys.meta_path.insert(0, Offline())
from kuberich.cli import main
assert main(['--screen-dump-dir', sys.argv[1], 'info']) == 2
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "missing")],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "missing").exists()
