"""Real PTY inspection input, clipboard output, resize and terminal restoration."""

import sys

from tests.support.inspection import terminal_inspection


def test_source_inspection_restores_terminal(tmp_path):
    terminal_inspection(
        [sys.executable, "-m", "kuberich"], tmp_path, evidence="resource-inspection"
    )
