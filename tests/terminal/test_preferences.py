"""Configured native terminal keys and an actual restart after a preference save."""

import sys

from tests.support.preferences_terminal import terminal_preferences


def test_navigation_preferences_and_restart_in_real_terminal(tmp_path):
    terminal_preferences([sys.executable, "-m", "kuberich"], tmp_path, "navigation-preferences")
