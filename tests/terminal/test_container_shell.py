"""Console/module shell routes, explicit kubectl scope and terminal restoration."""

import shutil
import sys

import pytest

from tests.support.shell import terminal_shell


@pytest.mark.parametrize("entry", ["console", "module"])
@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "failure",
        "ctrl_c",
        "terminate",
        "fullscreen",
        "missing",
        "readonly",
        "deleted",
        "shell_missing",
    ],
)
def test_native_selected_container_shell(tmp_path, entry, scenario):
    command = (
        [sys.executable, "-m", "kubetrol"] if entry == "module" else [shutil.which("kubetrol")]
    )
    assert command[0]
    terminal_shell(command, tmp_path, scenario, evidence=f"container-shell-{entry}-{scenario}")
