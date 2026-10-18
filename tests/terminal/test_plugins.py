"""Actual CLI forms, repeated terminal handoff, private cleanup and job output."""

import sys

from tests.support.plugins_terminal import terminal_plugins


def test_real_cli_plugin_modes_and_terminal_restoration(tmp_path):
    terminal_plugins([sys.executable, "-m", "kuberich"], tmp_path, "plugin-modes")
