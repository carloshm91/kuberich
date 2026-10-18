"""The private launcher validates ownership and never echoes its sensitive input."""

import json
import os
import runpy
import sys

import pytest

from kuberich import runtime
from kuberich.adapters import credential_child
from kuberich.domain.processes import ProcessPurpose
from kuberich.errors import AppError
from tests.unit.test_processes import command


def invocation(tmp_path, **changes):
    path = tmp_path / "credential.json"
    path.write_text(
        json.dumps(
            {
                "argv": [sys.executable, "literal"],
                "environment": {"PROFILE": "frozen", "KUBERNETES_EXEC_INFO": "old"},
                "directory": str(tmp_path),
                **changes,
            }
        )
    )
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("dynamic", [None, "new-client-go-information"])
def test_exact_helper_cwd_environment_and_only_dynamic_exec_info(tmp_path, monkeypatch, dynamic):
    path = invocation(tmp_path)
    monkeypatch.setenv("PROFILE", "plugin")
    if dynamic is None:
        monkeypatch.delenv("KUBERNETES_EXEC_INFO", raising=False)
    else:
        monkeypatch.setenv("KUBERNETES_EXEC_INFO", dynamic)
    entered = []
    monkeypatch.setattr(os, "chdir", lambda value: entered.append(value))

    def replace(executable, argv, environment):
        assert executable == sys.executable and argv == [sys.executable, "literal"]
        assert environment == {
            "PROFILE": "frozen",
            **({"KUBERNETES_EXEC_INFO": dynamic} if dynamic else {}),
        }

    monkeypatch.setattr(os, "execve", replace)
    assert credential_child.main([str(path)]) == 0
    assert entered == [str(tmp_path)]


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"argv": []},
        {"extra": 1},
        {"argv": []},
        {"argv": "sensitive"},
        {"argv": ["relative"]},
        {"argv": ["/bin/sh", None]},
        {"argv": ["/bin/sh", "\0"]},
        {"argv": ["/bin/sh"] * 258},
        {"directory": None},
        {"directory": "relative"},
        {"environment": []},
        {"environment": {"": "value"}},
        {"environment": {"BAD=KEY": "value"}},
        {"environment": {"BAD\0KEY": "value"}},
        {"environment": {"KEY": None}},
        {"environment": {"KEY": "\0"}},
        {"environment": {str(i): "v" for i in range(4097)}},
    ],
)
def test_invalid_private_request_is_bounded_and_concealed(tmp_path, capfd, data):
    if isinstance(data, dict):
        path = invocation(tmp_path, **data)
    else:
        path = invocation(tmp_path)
        path.write_text(json.dumps(data))
    assert credential_child.main([str(path)]) == 126
    assert capfd.readouterr().err == "Cannot start the captured credential helper.\n"


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "relative",
        "extra",
        "directory",
        "link",
        "mode",
        "owner",
        "large",
        "json",
        "unicode",
        "exec",
    ],
)
def test_unsafe_files_or_failed_exec_cannot_escape_the_child(tmp_path, monkeypatch, capfd, kind):
    path = invocation(tmp_path)
    args = [str(path)]
    if kind == "missing":
        args = []
    elif kind == "relative":
        args = ["relative"]
    elif kind == "extra":
        args.append("private")
    elif kind == "directory":
        args = [str(tmp_path)]
    elif kind == "link":
        link = tmp_path / "link"
        link.symlink_to(path)
        args = [str(link)]
    elif kind == "mode":
        path.chmod(0o644)
    elif kind == "owner":
        monkeypatch.setattr(os, "getuid", lambda: -1)
    elif kind == "large":
        path.write_bytes(b"x" * 1048577)
    elif kind == "json":
        path.write_text("PRIVATE")
    elif kind == "unicode":
        path.write_bytes(b"\xff")
    else:

        def fail(*args):
            raise OSError("PRIVATE")

        monkeypatch.setattr(os, "execve", fail)
        monkeypatch.setattr(os, "chdir", lambda *_: None)
    assert credential_child.main(args) == 126
    assert capfd.readouterr().err == "Cannot start the captured credential helper.\n"


def test_module_dispatch_and_closed_descriptor(tmp_path, monkeypatch):
    path = invocation(tmp_path, argv=["relative"])
    monkeypatch.setattr(sys, "argv", ["credential-child", str(path)])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(credential_child.__file__, run_name="__main__")
    assert stopped.value.code == 126


@pytest.mark.parametrize("frozen", [False, True])
def test_launcher_uses_owned_interpreter_or_frozen_private_dispatch(tmp_path, monkeypatch, frozen):
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    argv = runtime.credential_argv(tmp_path / "invocation.json")
    assert argv[0] == sys.executable and argv[-1] == str(tmp_path / "invocation.json")
    assert argv[1] == (runtime.CREDENTIAL_OPTION if frozen else "-I")
    if frozen:
        monkeypatch.setattr(sys, "argv", [sys.executable, *argv[1:]])
        monkeypatch.setattr(credential_child, "main", lambda args: 87 if args == [argv[-1]] else 1)
        assert runtime.main() == 87


@pytest.mark.parametrize(
    "value,purpose", [(True, ProcessPurpose.EXEC), ("true", ProcessPurpose.PLUGIN)]
)
def test_untrusted_readonly_process_classification_is_rejected(tmp_path, value, purpose):
    with pytest.raises(AppError, match="classification"):
        command(tmp_path, purpose=purpose, trusted_read_only=value)
