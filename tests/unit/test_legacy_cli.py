"""The deprecated console name preserves behavior and keeps its warning on stderr."""

import sys

import pytest

from kuberich import cli

NOTICE = (
    "Warning: kubetrol is deprecated; use kuberich instead. "
    "This command will be removed in 0.4.0.\n"
)


def invoke(command, arguments, capsys):
    try:
        result = command(arguments)
    except SystemExit as error:
        result = error.code
    captured = capsys.readouterr()
    return result, captured.out, captured.err


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["version", "--short"]])
def test_legacy_help_and_versions_keep_canonical_stdout_without_loading_preferences(
    arguments, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("Help and version must not read preferences or launch a terminal")

    monkeypatch.setattr(cli, "read_config", forbidden)
    monkeypatch.setattr(cli, "run_terminal", forbidden)
    current = invoke(cli.main, arguments, capsys)
    previous = invoke(cli.legacy_main, arguments, capsys)
    assert current[0] == previous[0] == 0
    assert current[1] == previous[1] and current[2] == ""
    assert previous[2] == NOTICE


@pytest.mark.parametrize("arguments", [["--unexpected", "token=private-marker"], ["--command", ""]])
def test_legacy_failures_preserve_the_exit_code_and_do_not_echo_sensitive_arguments(
    arguments, capsys
):
    current = invoke(cli.main, arguments, capsys)
    previous = invoke(cli.legacy_main, arguments, capsys)
    assert current[0] == previous[0] == 2
    assert current[1] == previous[1] == ""
    assert previous[2] == NOTICE + current[2]
    assert "private-marker" not in previous[2]


def test_console_invocation_uses_process_arguments_and_keeps_canonical_identity(
    monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["kubetrol", "--version"])
    with pytest.raises(SystemExit) as caught:
        cli.legacy_main()
    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == f"kuberich {cli.version('kuberich')}\n"
    assert captured.err == NOTICE


def test_legacy_info_retains_real_read_only_inspection_and_safe_json(tmp_path, capsys):
    config = tmp_path / "preferences.yaml"
    original = "schema_version: 1\nread_only: true\nprivate_note: private-marker\n"
    config.write_text(original)
    arguments = ["--config", str(config), "info"]
    current = invoke(cli.main, arguments, capsys)
    previous = invoke(cli.legacy_main, arguments, capsys)
    assert current[0] == previous[0] == 0
    assert current[1] == previous[1] and previous[2] == NOTICE
    assert "private-marker" not in previous[1] + previous[2]
    assert config.read_text() == original
    assert list(tmp_path.iterdir()) == [config]
