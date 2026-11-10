"""Actual node diagnostic CLI input, return, child ownership and TTY restoration."""

import sys

import pytest

from tests.support.node_shell_terminal import terminal_node_shell


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "repeat",
        "ctrl_c",
        "close",
        "quit",
        "sigterm",
        "missing",
        "shell_missing",
        "connection_loss",
    ],
)
def test_actual_node_shell_terminal_restore(tmp_path, scenario):
    terminal_node_shell(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        scenario,
        evidence="node-shell-" + scenario,
    )
