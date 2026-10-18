"""Actual CLI forms, repeated terminal handoff, private cleanup and job output."""

import sys

import pytest

from tests.support.plugins_terminal import terminal_plugins


@pytest.mark.parametrize("read_size", [65536, 11])
def test_real_cli_plugin_modes_and_terminal_restoration(tmp_path, read_size):
    terminal_plugins(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        f"plugin-modes-{read_size}",
        read_size=read_size,
    )
