"""Actual TTY command/completion/filter/history input and exit restoration."""

import sys

from tests.support.navigation import terminal_navigation


def test_source_command_completion_filter_scope_and_history_restore_terminal(tmp_path):
    terminal_navigation([sys.executable, "-m", "kuberich"], tmp_path, evidence="command-navigation")
