"""Operator-facing audited launch contract and rejection before side effects."""

import json
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from kuberich import cli
from kuberich.config.schema import Settings
from kuberich.services.commands import Command
from kuberich.ui.presentation import Presentation


@pytest.mark.parametrize(
    "action",
    [
        "edit",
        "annotate",
        "scale",
        "scale 2",
        "restart",
        "rollback 1",
        "rollout",
        "attach",
        "upload",
        "download",
    ],
)
def test_selected_resource_actions_are_refused_at_startup(action, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_terminal", lambda *a, **k: pytest.fail("Started unscoped action"))
    assert cli.main(["--command", action]) == 4
    assert "interactive resource selection" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments,flag,owner",
    [
        (["--splashless"], "--splashless", "U01 #56"),
        (["--invert"], "--invert", "U01 #56"),
        (["--screen-dump-dir", "fixture"], "--screen-dump-dir", "O06 #73"),
    ],
)
def test_pending_flags_name_the_missing_behavior_without_any_io(
    arguments: list[str],
    flag: str,
    owner: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A pending option must fail before preference/log/UI side effects.")

    monkeypatch.setattr(cli, "read_config", forbidden)
    monkeypatch.setattr(cli, "run_terminal", forbidden)
    monkeypatch.setattr(cli, "diagnostic_logging", forbidden)
    assert cli.main(arguments) == 4
    output = capsys.readouterr()
    assert flag in output.err and owner in output.err and "unavailable" in output.err
    assert "opaque-secret" not in output.err and output.out == ""
    assert list(tmp_path.iterdir()) == []


def test_identity_options_do_not_read_selected_files_for_info(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    contents = "users: [{token: opaque-secret}]\n"
    kubeconfig.write_text(contents)
    assert cli.main(["--kubeconfig", str(kubeconfig), "info"]) == 2
    assert kubeconfig.read_text() == contents
    assert "opaque-secret" not in capsys.readouterr().err
    assert cli.main(["--certificate-authority", str(tmp_path / "missing"), "info"]) == 2
    assert "only to terminal" in capsys.readouterr().err


def test_repeated_impersonation_groups_are_captured_in_order_for_launch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = ["--as", "fixture", "--as-group", "group one", "--as-group", "group-two"]
    parsed = cli._parser().parse_args(arguments)
    assert parsed.as_group == ["group one", "group-two"]
    captured = []
    monkeypatch.setattr(
        cli, "run_terminal", lambda *args, **kwargs: captured.append(kwargs["connection"])
    )
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert "group one" not in output.err and "group-two" not in output.err
    assert output.err == "" and output.out == ""
    assert captured[0].overrides.as_user == "fixture"
    assert captured[0].overrides.as_groups == ("group one", "group-two")


@pytest.mark.parametrize(
    "arguments,message",
    [
        (["--readonly", "--write"], "mutually exclusive"),
        (["-n", "fixture", "-A"], "mutually exclusive"),
        (["--as-group", "opaque-group"], "requires --as"),
        (["--client-key", "opaque-path"], "supplied together"),
        (["--client-certificate", "opaque-path"], "supplied together"),
        (
            ["--token", "opaque-secret", "--client-key", "key", "--client-certificate", "cert"],
            "mutually exclusive",
        ),
        (
            ["--certificate-authority", "opaque-path", "--insecure-skip-tls-verify"],
            "mutually exclusive",
        ),
    ],
)
def test_invalid_combinations_have_owned_specific_errors(
    arguments: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(arguments) == 2
    output = capsys.readouterr()
    assert message in output.err
    assert "opaque-" not in output.err and output.out == ""


@pytest.mark.parametrize(
    "arguments", [["help"], ["version"], ["version", "--short"], ["version", "-s"]]
)
def test_inspection_commands_do_not_load_broken_preferences_or_credentials(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("KUBERICH_CONFIG", "/nonexistent/opaque-secret")
    monkeypatch.setenv("KUBERICH_READONLY", "invalid")
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert output.err == "" and "opaque-secret" not in output.out
    if arguments == ["help"]:
        assert output.out == cli._parser().format_help()
    else:
        expected = version("kuberich") if len(arguments) > 1 else f"kuberich {version('kuberich')}"
        assert output.out == expected + "\n"


@pytest.mark.parametrize(
    "arguments", [["--readonly", "help"], ["--config", "opaque-path", "version"]]
)
def test_inspection_commands_refuse_runtime_options_instead_of_ignoring_them(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(arguments) == 2
    assert "do not accept" in capsys.readouterr().err


def test_help_matches_reviewable_contract_snapshot() -> None:
    # argparse 3.13+ lists aliases with one trailing metavar; keep native formatting.
    name = "launch-help-py312.txt" if sys.version_info < (3, 13) else "launch-help-py313plus.txt"
    expected = (Path(__file__).parent / "snapshots" / name).read_text()
    assert cli._parser().format_help() == expected


@pytest.mark.parametrize(
    "flag",
    ["--readonly", "--write", "--refresh", "--command", "--headless", "--logoless", "--crumbsless"],
)
def test_config_init_refuses_all_runtime_options(
    flag: str,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    value = ["2"] if flag == "--refresh" else ["help"] if flag == "--command" else []
    assert cli.main([flag, *value, "config", "init"]) == 2
    output = capsys.readouterr()
    assert "runtime overrides" in output.err or "only to terminal" in output.err
    assert not (tmp_path / "config").exists()


@pytest.mark.parametrize("flag", ["--headless", "--logoless", "--crumbsless", "--command"])
@pytest.mark.parametrize("command", [["info"], ["config", "check"]])
def test_terminal_options_are_not_silently_ignored_by_diagnostics(
    flag: str,
    command: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([flag, *(["help"] if flag == "--command" else []), *command]) == 2
    assert "only to terminal" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--refresh", "-r"])
def test_refresh_precedence_is_shared_by_diagnostics_and_terminal(
    flag: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "preferences.yaml"
    path.write_text("schema_version: 1\nrefresh_seconds: 7\n")
    monkeypatch.setenv("KUBERICH_CONFIG", str(path))
    monkeypatch.setenv("KUBERICH_REFRESH", "5")
    assert cli.main([flag, "3.5", "info"]) == 0
    assert json.loads(capsys.readouterr().out)["preferences"]["refresh_seconds"] == 3.5
    assert cli.main([flag, "3.5", "config", "check"]) == 0
    capsys.readouterr()
    captured = []
    monkeypatch.setattr(
        cli, "run_terminal", lambda settings, *args, **kwargs: captured.append(settings)
    )
    assert cli.main([flag, "3.5"]) == 0
    assert captured[0].refresh_seconds == 3.5
    assert capsys.readouterr().err == ""
    assert (tmp_path / "logs").exists()


@pytest.mark.parametrize("value", ["0", "3601", "nan", "inf", "-1"])
def test_refresh_range_and_finiteness_are_validated(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--refresh", value, "info"]) == 2
    assert "finite number" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        ["-r", "opaque-secret"],
        ["--token"],
        ["--token", "x\x1b]52;c;secret\x07"],
        ["--context=bad\nvalue"],
        ["--as-group", ""],
        ["--command", "x" * 8193],
        ["--insecure-skip-tls-verify=opaque-secret"],
    ],
)
def test_syntax_or_hostile_values_fail_without_echoing_data(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    output = capsys.readouterr()
    assert "invalid command line" in output.err and "opaque-secret" not in output.err
    assert "clipboard" not in output.err and "bad\nvalue" not in output.err


@pytest.mark.parametrize(
    "file_readonly,env_readonly,flag,expected",
    [(False, "false", "--readonly", True), (True, "true", "--write", False)],
)
def test_explicit_readonly_choice_overrides_environment_and_file_without_persisting(
    file_readonly: bool,
    env_readonly: str,
    flag: str,
    expected: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "preferences.yaml"
    contents = f"schema_version: 1\nread_only: {str(file_readonly).lower()}\n"
    path.write_text(contents)
    monkeypatch.setenv("KUBERICH_CONFIG", str(path))
    monkeypatch.setenv("KUBERICH_READONLY", env_readonly)
    assert cli.main([flag, "info"]) == 0
    assert json.loads(capsys.readouterr().out)["preferences"]["read_only"] is expected
    assert path.read_text() == contents


@pytest.mark.parametrize(
    "arguments",
    [
        ["--readonly", "--command", "shell"],
        ["--readonly", "-c", "attach fixture"],
        ["--readonly", "-c", "delete fixture"],
    ],
)
def test_readonly_initial_commands_use_the_service_policy_before_launch(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    assert cli.main(arguments) == 2
    assert "Read-only mode blocks" in capsys.readouterr().err
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize("command", ["networkpolicies", "shell", "help extra"])
def test_initial_commands_require_real_behavior(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["-c", command]) == 4
    assert "Available: po, ctx, ns" in capsys.readouterr().err


@pytest.mark.parametrize("command", [" ", ":", ": "])
def test_explicit_empty_initial_command_is_not_ignored(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--command", command]) == 2
    assert "must name an initial command" in capsys.readouterr().err


@pytest.mark.parametrize("level_flag", ["--log-level", "--logLevel", "-l"])
@pytest.mark.parametrize("path_flag", ["--log-file", "--logFile"])
def test_all_log_aliases_and_last_scalar_value_are_effective(
    level_flag: str,
    path_flag: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = tmp_path / "last.log"
    assert (
        cli.main(
            [
                level_flag,
                "ERROR",
                level_flag,
                "debug",
                path_flag,
                str(selected),
                "-r",
                "7",
                "--refresh",
                "3",
                "info",
            ]
        )
        == 0
    )
    information = json.loads(capsys.readouterr().out)
    assert information["preferences"]["log_level"] == "DEBUG"
    assert information["preferences"]["refresh_seconds"] == 3
    assert information["log_file"] == str(selected)
    assert not selected.exists()


@pytest.mark.parametrize("flag,command", [("--command", "help"), ("-c", "quit")])
def test_launch_receives_effective_policy_presentation_and_initial_command(
    flag: str,
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[Settings, object, object]] = []

    def record(settings: Settings, logger: object, **kwargs: object) -> None:
        captured.append((settings, kwargs["presentation"], kwargs["initial_command"]))

    monkeypatch.setattr(cli, "run_terminal", record)
    assert cli.main(["--readonly", "--headless", "--logoless", "--crumbsless", flag, command]) == 0
    settings, presentation, initial = captured[0]
    assert settings.read_only
    assert presentation == Presentation(True, True, True)
    assert initial is (Command.HELP if command == "help" else Command.QUIT)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--context", "chosen"],
        ["--kubeconfig", "owned"],
        ["-n", "team"],
        ["-A"],
        ["--request-timeout", "2s"],
        ["--cluster", "chosen"],
        ["--user", "chosen"],
        ["--as", "chosen"],
        ["--as", "chosen", "--as-group", "group"],
        ["--token", "chosen"],
        ["--certificate-authority", "chosen"],
        ["--client-certificate", "chosen", "--client-key", "chosen"],
        ["--insecure-skip-tls-verify"],
        ["--insecure-skip-tls-verify=false"],
    ],
)
@pytest.mark.parametrize(
    "subcommand", [["info"], ["config", "check"], ["config", "init"], ["help"], ["version"]]
)
def test_connection_flags_never_load_credentials_in_inspection(
    arguments, subcommand, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "read_config", lambda *args, **kwargs: pytest.fail("No preference I/O before refusal")
    )
    assert cli.main([*arguments, *subcommand]) == 2
    assert "chosen" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments", [["--request-timeout", "0"], ["--request-timeout", "nan"], ["-n", "INVALID"]]
)
def test_invalid_connection_values_are_owned_errors_before_any_io(arguments, monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "read_config",
        lambda *args, **kwargs: pytest.fail("Invalid connection reached preferences"),
    )
    assert cli.main(arguments) == 2
    assert capsys.readouterr().out == ""


def test_launch_passes_context_scope_and_timeout_without_loading_credentials(monkeypatch):
    captured = []
    monkeypatch.setattr(
        cli, "run_terminal", lambda *args, **kwargs: captured.append(kwargs["connection"])
    )
    assert (
        cli.main(
            [
                "--kubeconfig",
                "owned",
                "--context",
                "CasePreserved",
                "-n",
                "team",
                "--request-timeout",
                "1500ms",
            ]
        )
        == 0
    )
    request = captured[0]
    assert request.context == "CasePreserved" and request.namespace == "team"
    assert request.kubeconfig == "owned" and request.timeout == 1.5
    assert cli.main(["-A"]) == 0
    assert captured[1].all_namespaces


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ([], None),
        (["--insecure-skip-tls-verify"], True),
        (["--insecure-skip-tls-verify=TRUE"], True),
        (["--insecure-skip-tls-verify=false"], False),
    ],
)
def test_launch_captures_tls_boolean_and_last_identity_alias(arguments, expected, monkeypatch):
    captured = []
    monkeypatch.setattr(
        cli, "run_terminal", lambda *args, **kwargs: captured.append(kwargs["connection"])
    )
    assert (
        cli.main(
            [
                "--cluster",
                "first",
                "--cluster",
                "last",
                "--user",
                "auth",
                "--token",
                "synthetic-token",
                *arguments,
            ]
        )
        == 0
    )
    overrides = captured[0].overrides
    assert overrides.cluster == "last" and overrides.user == "auth"
    assert overrides.insecure is expected and overrides.token == "synthetic-token"
    assert "synthetic-token" not in repr(captured[0])


def test_cli_certificate_paths_are_captured_from_launch_directory_without_reading(
    monkeypatch, tmp_path
):
    captured = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli, "run_terminal", lambda *args, **kwargs: captured.append(kwargs["connection"])
    )
    assert (
        cli.main(
            [
                "--certificate-authority",
                "absent-ca",
                "--client-key",
                "absent-key",
                "--client-certificate",
                "absent-cert",
            ]
        )
        == 0
    )
    overrides = captured[0].overrides
    assert overrides.certificate_authority == str(tmp_path / "absent-ca")
    assert overrides.client_key == str(tmp_path / "absent-key")
    assert overrides.client_certificate == str(tmp_path / "absent-cert")
    assert not any(path.name.startswith("absent") for path in tmp_path.iterdir())
