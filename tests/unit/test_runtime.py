"""Frozen launch decisions preserve literal arguments and external tool identity."""

import os
import sys
from pathlib import Path

import pytest

from kuberich import cli, runtime
from kuberich.adapters import pty_child


def frozen(monkeypatch, platform="linux", directory="/owned/bundle"):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", directory, raising=False)
    monkeypatch.setattr(sys, "platform", platform)


@pytest.mark.parametrize(
    "enabled,directory,platform",
    [
        (False, "/owned/bundle", "linux"),
        (True, None, "linux"),
        (True, 123, "linux"),
        (True, "relative", "linux"),
        (True, "/owned/bundle", "win32"),
    ],
)
def test_unmanaged_runtime_preserves_every_environment_value(
    monkeypatch, enabled, directory, platform
):
    frozen(monkeypatch, platform, directory)
    monkeypatch.setattr(sys, "frozen", enabled)
    inherited = {
        "LD_LIBRARY_PATH": "/owned/bundle",
        "LD_LIBRARY_PATH_ORIG": "",
        "_PYI_ARCHIVE_FILE": "literal",
        "PATH": "",
        "TOKEN": "sensitive",
    }
    result = runtime.external_environment(inherited)
    assert result == inherited and result is not inherited


@pytest.mark.parametrize(
    "original,expected",
    [(None, None), ("", ""), ("/user/lib", "/user/lib"), ("/owned/bundle:/user/lib", "/user/lib")],
)
def test_linux_external_libraries_restore_the_original_user_value(monkeypatch, original, expected):
    frozen(monkeypatch)
    inherited = {
        "LD_LIBRARY_PATH": "/owned/bundle:/user/lib",
        "_PYI_APPLICATION_HOME_DIR": "/owned/bundle",
        "_PYI_PARENT_PROCESS_LEVEL": "1",
        "TOKEN": "fixture-sensitive",
        "KUBECONFIG": "/owned/captured.yaml",
        "PATH": "/bin",
    }
    if original is not None:
        inherited["LD_LIBRARY_PATH_ORIG"] = original
    before = dict(inherited)
    ambient = dict(os.environ)
    result = runtime.external_environment(inherited)
    assert result.get("LD_LIBRARY_PATH") == expected
    assert ("LD_LIBRARY_PATH" in result) is (expected is not None)
    assert "LD_LIBRARY_PATH_ORIG" not in result
    assert not any(key.startswith("_PYI_") for key in result)
    assert result["TOKEN"] == "fixture-sensitive" and result["PATH"] == "/bin"
    assert result["KUBECONFIG"] == "/owned/captured.yaml"
    assert inherited == before and dict(os.environ) == ambient


def test_explicit_external_library_override_is_preserved(monkeypatch):
    frozen(monkeypatch)
    assert runtime.external_environment(
        {"LD_LIBRARY_PATH": "/explicit/lib", "LD_LIBRARY_PATH_ORIG": "/ambient/lib"}
    ) == {"LD_LIBRARY_PATH": "/explicit/lib"}
    assert runtime.external_environment({}) == {}


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("name", ["PATH", "DYLD_LIBRARY_PATH"])
@pytest.mark.parametrize(
    "value,expected",
    [
        ("/owned/bundle", None),
        ("/owned/bundle/bin:/user/bin:/owned/bundle-other", "/user/bin:/owned/bundle-other"),
        (":/owned/bundle/lib:relative", ":relative"),
        ("/owned/bundle/../external:/user/bin", "/owned/bundle/../external:/user/bin"),
        ("", ""),
    ],
)
def test_external_search_paths_remove_only_paths_inside_the_bundle(
    monkeypatch, platform, name, value, expected
):
    frozen(monkeypatch, platform)
    result = runtime.external_environment({name: value})
    assert result.get(name) == expected
    assert (name in result) is (expected is not None)


def test_macos_does_not_replace_user_linux_library_variables(monkeypatch):
    frozen(monkeypatch, "darwin")
    inherited = {"LD_LIBRARY_PATH": "/owned/bundle", "LD_LIBRARY_PATH_ORIG": "user"}
    assert runtime.external_environment(inherited) == inherited


@pytest.mark.parametrize("enabled", [False, True])
def test_pty_launcher_keeps_resolved_executable_and_literal_arguments(monkeypatch, enabled):
    monkeypatch.setattr(sys, "frozen", enabled, raising=False)
    arguments = ["/owned/tool", "literal;$(touch file)", "[markup]", "two words"]
    before = list(arguments)
    prefix = (
        (sys.executable, runtime.PTY_OPTION)
        if enabled
        else (sys.executable, "-I", str(Path(runtime.__file__).parent / "adapters/pty_child.py"))
    )
    assert runtime.pty_argv(arguments) == (*prefix, *arguments)
    assert arguments == before


@pytest.mark.parametrize(
    "enabled,args", [(False, []), (False, [runtime.PTY_OPTION]), (True, []), (True, ["--help"])]
)
def test_normal_entry_calls_the_cli_without_rewriting_its_arguments(monkeypatch, enabled, args):
    monkeypatch.setattr(sys, "frozen", enabled, raising=False)
    monkeypatch.setattr(sys, "argv", ["owned-entry", *args])
    calls = []
    monkeypatch.setattr(cli, "main", lambda: calls.append(tuple(sys.argv)) or 7)
    assert runtime.main() == 7
    assert calls == [("owned-entry", *args)]


def test_frozen_pty_entry_uses_clean_external_environment_and_no_cli(monkeypatch):
    frozen(monkeypatch)
    monkeypatch.setattr(
        sys, "argv", ["owned-entry", runtime.PTY_OPTION, "/owned/tool", "literal;argument"]
    )
    monkeypatch.setenv("LD_LIBRARY_PATH", "/owned/bundle")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    calls = []
    monkeypatch.setattr(
        pty_child, "main", lambda argv, *, environment: calls.append((argv, environment)) or 126
    )
    monkeypatch.setattr(cli, "main", lambda: pytest.fail("PTY child must not start the UI"))
    before = dict(os.environ)
    assert runtime.main() == 126
    assert calls[0][0] == ["/owned/tool", "literal;argument"]
    assert "LD_LIBRARY_PATH" not in calls[0][1]
    assert dict(os.environ) == before


def test_pty_child_replaces_itself_with_exact_explicit_argv_and_environment(monkeypatch):
    monkeypatch.setattr(pty_child.fcntl, "ioctl", lambda *args: None)
    monkeypatch.setattr(pty_child.os, "tcsetpgrp", lambda *args: None)
    calls = []

    class Replaced(BaseException):
        pass

    def execve(path, argv, environment):
        calls.append((path, argv, environment))
        raise Replaced

    monkeypatch.setattr(pty_child.os, "execve", execve)
    with pytest.raises(Replaced):
        pty_child.main(["/owned/tool", "literal;argument"], environment={"PATH": "/bin"})
    assert calls == [("/owned/tool", ["/owned/tool", "literal;argument"], {"PATH": "/bin"})]


@pytest.mark.parametrize("arguments", [[], ["/missing/tool"]])
def test_frozen_pty_child_failure_is_bounded_and_does_not_echo_arguments(monkeypatch, arguments):
    monkeypatch.setattr(pty_child.fcntl, "ioctl", lambda *args: None)
    monkeypatch.setattr(pty_child.os, "tcsetpgrp", lambda *args: None)
    monkeypatch.setattr(pty_child.os, "execve", lambda *args: (_ for _ in ()).throw(OSError()))
    output = []
    monkeypatch.setattr(pty_child.os, "write", lambda fd, value: output.append((fd, value)))
    assert pty_child.main(arguments, environment={}) == 126
    assert output == [(2, b"Cannot start the interactive executable.\n")]
