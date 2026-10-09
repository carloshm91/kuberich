"""Source aggregate navigation/controls and actual terminal resize/mode restoration."""

import sys

from tests.support.aggregate_terminal import terminal_aggregate_logs


def test_aggregate_logs_in_real_terminal(tmp_path):
    terminal_aggregate_logs([sys.executable, "-m", "kuberich"], tmp_path, "aggregate-logs")
