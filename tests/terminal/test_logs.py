"""Real log keyboard batches, pause, error exits and terminal restoration."""

import sys

import pytest

from tests.support.log_viewer import terminal_logs


@pytest.mark.parametrize("error_exit", [False, True])
def test_source_log_viewer_restores_terminal(tmp_path, error_exit):
    terminal_logs(
        [sys.executable, "-m", "kubetrol"],
        tmp_path,
        evidence=f"log-viewer-{'error' if error_exit else 'return'}",
        error_exit=error_exit,
    )
