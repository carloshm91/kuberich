"""The retired console shim is absent; canonical invocation preserves its contracts."""

import sys

import pytest

from kuberich import cli


def test_retired_legacy_python_entry_point_is_absent():
    assert not hasattr(cli, "legacy_main")


def invoke(command, arguments, capsys):
    try:
        result = command(arguments)
    except SystemExit as error:
        result = error.code
    captured = capsys.readouterr()
    return result, captured.out, captured.err


@pytest.mark.parametrize("arguments", [["--help"], ["--version"], ["version", "--short"]])
def test_canonical_help_and_versions_do_not_load_preferences_or_warn_about_an_alias(
    arguments, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("Help and version must not read preferences or launch a terminal")

    monkeypatch.setattr(cli, "read_config", forbidden)
    monkeypatch.setattr(cli, "run_terminal", forbidden)
    current = invoke(cli.main, arguments, capsys)
    assert current[0] == 0 and current[2] == ""
    assert "kuberich" in current[1] or arguments == ["version", "--short"]
    assert "kubetrol" not in current[1]
    if arguments == ["--version"]:
        assert current[1] == f"kuberich {cli.version('kuberich')}\n"
    elif arguments == ["version", "--short"]:
        assert current[1] == f"{cli.version('kuberich')}\n"
    else:
        assert "usage: kuberich" in current[1]


@pytest.mark.parametrize("arguments", [["--unexpected", "token=private-marker"], ["--command", ""]])
def test_canonical_failures_preserve_the_exit_code_and_do_not_echo_sensitive_arguments(
    arguments, capsys
):
    current = invoke(cli.main, arguments, capsys)
    assert current[0] == 2 and current[1] == ""
    assert "invalid command line" in current[2]
    assert "private-marker" not in current[2] and "deprecated" not in current[2]


def test_canonical_invocation_keeps_its_identity_regardless_of_process_program_name(
    monkeypatch, capsys
):
    monkeypatch.setattr(sys, "argv", ["kubetrol", "--version"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == f"kuberich {cli.version('kuberich')}\n"
    assert captured.err == ""


def test_canonical_info_retains_real_read_only_inspection_and_safe_json(tmp_path, capsys):
    config = tmp_path / "preferences.yaml"
    original = "schema_version: 1\nread_only: true\nprivate_note: private-marker\n"
    config.write_text(original)
    arguments = ["--config", str(config), "info"]
    current = invoke(cli.main, arguments, capsys)
    assert current[0] == 0 and current[2] == ""
    assert "private-marker" not in current[1] + current[2]
    assert config.read_text() == original
    assert list(tmp_path.iterdir()) == [config]
