"""Real terminal start/list/stop/resize/exit and restored terminal modes."""

import sys

from tests.support.forward_terminal import terminal_forward


def test_actual_terminal_forward_ownership(tmp_path):
    terminal_forward([sys.executable, "-m", "kuberich"], tmp_path, "port-forwards")
