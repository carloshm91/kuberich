"""Behavioral checks for the supported development CLI."""

import importlib
import runpy
import sys
from importlib.metadata import version

import pytest

from kubetrol.cli import main


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_describes_available_behavior(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([flag])

    assert exit_info.value.code == 0
    output = capsys.readouterr()
    assert "usage: kubetrol" in output.out
    assert "--version" in output.out
    assert "terminal interface is not available yet" in output.out
    assert output.err == ""


def test_version_uses_installed_distribution_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    output = capsys.readouterr()
    assert output.out == f"kubetrol {version('kubetrol')}\n"
    assert output.err == ""


def test_no_arguments_reports_the_actual_stage(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    output = capsys.readouterr()
    assert "Kubetrol is installed" in output.out
    assert "terminal interface is not available yet" in output.out
    assert output.err == ""


def test_entry_point_reads_process_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kubetrol"])

    assert main() == 0
    assert "Kubetrol is installed" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [["--context", "example"], ["--ver"], ["pods"]])
def test_unsupported_arguments_fail_explicitly(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "unrecognized arguments" in output.err


def test_importing_module_does_not_execute_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kubetrol", "unsupported"])

    importlib.import_module("kubetrol.__main__")

    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_python_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kubetrol", "--version"])
    monkeypatch.delitem(sys.modules, "kubetrol.__main__", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("kubetrol", run_name="__main__")

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"kubetrol {version('kubetrol')}\n"
