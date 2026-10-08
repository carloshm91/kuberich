"""Process snapshots and builders never parse resource text as shell instructions."""

import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from kuberich.domain.processes import (
    ProcessCommand,
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
    capture_kubeconfigs,
    editor_command,
    exit_status,
    kubectl_exec_command,
    process_timeout,
)
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import Action


def target(**changes):
    values = dict(
        session=SessionIdentity("--context; literal $(command)", 7),
        group="",
        resource="pods",
        namespace="fixture",
        name="pod-a",
        uid="uid-a",
        container="app",
    )
    values.update(changes)
    return ResourceTarget(**values)


def command(tmp_path, **changes):
    values = dict(
        argv=("tool", "literal argument"),
        environment=(("PATH", "/bin"),),
        directory=tmp_path,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.PLUGIN,
    )
    values.update(changes)
    return ProcessCommand(**values)


@pytest.mark.parametrize(
    "purpose,action",
    [
        (ProcessPurpose.EXEC, Action.EXEC),
        (ProcessPurpose.ATTACH, Action.ATTACH),
        (ProcessPurpose.EDITOR, Action.MUTATE),
        (ProcessPurpose.PLUGIN, Action.PLUGIN),
        (ProcessPurpose.AUTHENTICATE, Action.READ),
    ],
)
def test_purpose_has_explicit_effect_policy(purpose, action):
    assert purpose.action is action


def test_authentication_retains_the_exec_contracts_256_args_plus_executable(tmp_path):
    value = command(
        tmp_path, argv=("helper", *(["literal"] * 256)), purpose=ProcessPurpose.AUTHENTICATE
    )
    assert len(value.argv) == 257
    with pytest.raises(AppError, match="argument count"):
        command(
            tmp_path, argv=("helper", *(["literal"] * 257)), purpose=ProcessPurpose.AUTHENTICATE
        )


def test_snapshots_argv_environment_and_target_before_await(tmp_path):
    argv = ["tool", "$(touch sentinel); [markup]"]
    environment = {"TOKEN": "fixture-sensitive-value", "MULTILINE": "a\nb"}
    value = capture_command(
        argv,
        environment=environment,
        directory=tmp_path,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.PLUGIN,
        target=target(),
    )
    argv[1] = "changed"
    environment["TOKEN"] = "changed"
    assert value.argv[1] == "$(touch sentinel); [markup]"
    assert dict(value.environment)["TOKEN"] == "fixture-sensitive-value"
    assert "fixture-sensitive-value" not in repr(value)
    assert "fixture-sensitive-value" not in repr(
        ProcessResult(ProcessStatus.FAILED, 2, b"fixture-sensitive-value")
    )
    with pytest.raises(FrozenInstanceError):
        value.target = None


@pytest.mark.parametrize(
    "changes",
    [
        {"argv": ()},
        {"argv": "tool --flags"},
        {"argv": ("tool", "a\0b")},
        {"argv": ("tool",) * 257},
        {"mode": "capture"},
        {"purpose": "plugin"},
        {"directory": Path("relative")},
        {"directory": "/tmp"},
        {"target": "pod"},
        {"terminal_input": "true"},
        {"environment": (("duplicate", "1"), ("duplicate", "2"))},
        {"environment": tuple((f"VAR{i}", "x") for i in range(4097))},
        {"environment": (("bad=name", "x"),)},
        {"environment": (("VAR", "x\0y"),)},
        {"environment": (("VAR", 42),)},
        {"environment": (("", "x"),)},
    ],
)
def test_invalid_command_is_rejected_without_exposing_values(tmp_path, changes):
    with pytest.raises(AppError):
        command(tmp_path, **changes)


def test_command_copies_nested_environment_entries(tmp_path):
    env = [["VAR", "before"]]
    value = command(tmp_path, environment=env)
    env[0][1] = "after"
    assert value.environment == (("VAR", "before"),)


@pytest.mark.parametrize(
    "code,status",
    [(0, ProcessStatus.SUCCEEDED), (7, ProcessStatus.FAILED), (-2, ProcessStatus.SIGNALLED)],
)
def test_real_exit_codes_remain_distinguishable(code, status):
    assert exit_status(code) is status


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), 86401])
def test_process_timeout_has_finite_bounds(value):
    with pytest.raises(AppError):
        process_timeout(value)


@pytest.mark.parametrize("value", [None, 0.001, 1, 86400])
def test_supported_timeouts(value):
    assert process_timeout(value) == value


def test_config_capture_has_explicit_first_file_and_merge_semantics(tmp_path):
    assert capture_kubeconfigs("one.yaml", {"KUBECONFIG": "ignored"}, tmp_path) == (
        tmp_path / "one.yaml",
    )
    assert capture_kubeconfigs(None, {"KUBECONFIG": "one.yaml::two.yaml:one.yaml"}, tmp_path) == (
        tmp_path / "one.yaml",
        tmp_path / "two.yaml",
    )
    assert capture_kubeconfigs(None, {}, tmp_path) == (Path.home() / ".kube/config",)
    assert capture_kubeconfigs(str(tmp_path / "one.yaml"), {}, tmp_path) == (tmp_path / "one.yaml",)
    with pytest.raises(AppError):
        capture_kubeconfigs(None, {"KUBECONFIG": ":".join(["p"] * 33)}, tmp_path)
    with pytest.raises(AppError):
        capture_kubeconfigs("", {}, tmp_path)


@pytest.mark.parametrize("merged", [False, True])
def test_kubectl_exec_captures_every_scope_without_shell_parsing(tmp_path, merged):
    paths = [tmp_path / "config with spaces"] + ([tmp_path / "second"] if merged else [])
    selected = target()
    value = kubectl_exec_command(
        selected, paths, ["sh", "-l"], environment={"KUBECONFIG": "ambient"}, directory=tmp_path
    )
    assert value.target is selected and value.mode is ProcessMode.FOREGROUND
    assert value.purpose is ProcessPurpose.EXEC
    assert f"--context={selected.session.context}" in value.argv
    assert "--namespace=fixture" in value.argv and "--container=app" in value.argv
    assert value.argv[-4:] == ("pod-a", "--", "sh", "-l")
    assert dict(value.environment)["KUBECONFIG"] == os.pathsep.join(map(str, paths))
    assert (f"--kubeconfig={paths[0]}" in value.argv) is not merged


@pytest.mark.parametrize(
    "changes",
    [{"group": "apps"}, {"resource": "deployments"}, {"namespace": None}, {"container": None}],
)
def test_exec_refuses_incomplete_or_wrong_resource_scope(tmp_path, changes):
    with pytest.raises(AppError):
        kubectl_exec_command(
            target(**changes), [tmp_path / "config"], ["sh"], environment={}, directory=tmp_path
        )


@pytest.mark.parametrize(
    "paths,shell",
    [
        ([], ["sh"]),
        ([Path("relative")], ["sh"]),
        ([Path("/p")] * 1, []),
        ([Path("/p")], ["--option"]),
        ([Path(f"/p{i}") for i in range(33)], ["sh"]),
        ([Path("/with:separator"), Path("/other")], ["sh"]),
    ],
)
def test_exec_refuses_ambiguous_paths_and_invalid_shell(tmp_path, paths, shell):
    with pytest.raises(AppError):
        kubectl_exec_command(target(), paths, shell, environment={}, directory=tmp_path)


@pytest.mark.parametrize("absolute", [False, True])
def test_editor_captures_an_explicit_file_after_option_boundary(tmp_path, absolute):
    filename = tmp_path / "-file with spaces" if absolute else Path("-file with spaces")
    value = editor_command(["vim", "-n"], filename, environment={}, directory=tmp_path)
    assert value.argv == ("vim", "-n", "--", str(tmp_path / "-file with spaces"))
    assert value.mode is ProcessMode.FOREGROUND and value.purpose is ProcessPurpose.EDITOR


def test_exec_target_and_environment_stay_captured_when_source_changes(tmp_path):
    config = [tmp_path / "one"]
    shell = ["sh"]
    env = {"PATH": "/bin"}
    selected = target()
    value = kubectl_exec_command(selected, config, shell, environment=env, directory=tmp_path)
    config[0] = tmp_path / "two"
    shell[0] = "bash"
    env["PATH"] = "changed"
    assert value.argv[-1] == "sh" and dict(value.environment)["PATH"] == "/bin"
    with pytest.raises(AppError, match="stale"):
        value.target.require_current(replace(selected.session, generation=8), uid=selected.uid)
