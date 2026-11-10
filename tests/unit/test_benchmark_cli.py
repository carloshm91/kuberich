"""Local benchmark browsing and explicit result paths cross launch without effects."""

import io
import sys
from types import SimpleNamespace

import pytest

from kuberich import cli
from kuberich.config.catalog import KubeCatalog
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService
from kuberich.ui import launch


def test_benchmark_load_requires_write_policy_but_result_browsing_is_local():
    writable = CommandService(AccessPolicy(False))
    readonly = CommandService(AccessPolicy(True))
    assert writable.resolve(":benchmark") is Command.BENCHMARK
    assert readonly.resolve(":benchmarks") is Command.BENCHMARKS
    for text in ("benchmark extra", "benchmarks /tmp/elsewhere"):
        with pytest.raises(AppError, match="without arguments"):
            writable.resolve(text)
    with pytest.raises(AppError, match="Read-only"):
        readonly.resolve(":benchmark")


def test_benchmark_result_directory_crosses_real_bootstrap_and_launch_without_creation(
    tmp_path, monkeypatch
):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    captures = []

    class CapturedApp:
        return_code = 0
        navigation = SimpleNamespace(mouse=False)

        def __init__(self, settings, logger, **kwargs):
            captures.append(kwargs)

        def run(self, *, mouse):
            assert mouse is False

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(sys, "stdout", Terminal())
    monkeypatch.setattr(launch, "load_catalog", lambda *args: KubeCatalog())
    monkeypatch.setattr(launch, "KubeRichApp", CapturedApp)
    config = tmp_path / "preferences.yaml"
    config.write_text("schema_version: 1\n")
    assert (
        cli.main(
            [
                "--config",
                str(config),
                "--log-file",
                str(tmp_path / "owned.log"),
                "--command",
                "benchmarks",
                "--benchmark-directory",
                "saved/results",
            ]
        )
        == 0
    )
    assert captures[0]["initial_command"] is Command.BENCHMARKS
    assert captures[0]["benchmark_directory"] == tmp_path / "saved/results"
    assert not (tmp_path / "saved").exists()


@pytest.mark.parametrize("arguments", [["info"], ["config", "check"], ["config", "init"]])
def test_benchmark_directory_is_terminal_only_before_config_io(
    tmp_path, monkeypatch, capsys, arguments
):
    def refused(*args, **kwargs):
        pytest.fail("Rejected launch option read configuration or started a terminal")

    monkeypatch.setattr(cli, "read_config", refused)
    monkeypatch.setattr(cli, "run_terminal", refused)
    assert cli.main(["--benchmark-directory", str(tmp_path / "absent"), *arguments]) == 2
    assert "terminal" in capsys.readouterr().err or arguments == ["config", "init"]
    assert not (tmp_path / "absent").exists()


def test_benchmark_load_cannot_be_an_initial_cli_command(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "run_terminal", lambda *args, **kwargs: pytest.fail("Unscoped benchmark started")
    )
    assert cli.main(["--command", "benchmark"]) == 4
    assert "interactive resource selection" in capsys.readouterr().err
