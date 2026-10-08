"""Behavioral checks for the supported development CLI."""

import importlib
import runpy
import sys
from importlib.metadata import version

import pytest

from kuberich.cli import main


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_describes_available_behavior(flag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([flag])

    assert exit_info.value.code == 0
    output = capsys.readouterr()
    assert "usage: kuberich" in output.out
    assert "--version" in output.out
    assert "Live pod table preview" in output.out
    assert "embedded container shells" in output.out
    assert output.err == ""


def test_version_uses_installed_distribution_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    output = capsys.readouterr()
    assert output.out == f"kuberich {version('kuberich')}\n"
    assert output.err == ""


def test_no_arguments_requires_a_real_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2

    output = capsys.readouterr()
    assert output.out == ""
    assert "requires an interactive terminal" in output.err


def test_entry_point_reads_process_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kuberich"])

    assert main() == 2
    assert "requires an interactive terminal" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [["--ver"], ["pods"]])
def test_unsupported_arguments_fail_explicitly(
    arguments: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)

    assert exit_info.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "invalid command line" in output.err


def test_importing_module_does_not_execute_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kuberich", "unsupported"])

    importlib.import_module("kuberich.__main__")

    output = capsys.readouterr()
    assert output.out == output.err == ""


def test_python_module_entry_point(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["kuberich", "--version"])
    monkeypatch.delitem(sys.modules, "kuberich.__main__", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("kuberich", run_name="__main__")

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"kuberich {version('kuberich')}\n"
