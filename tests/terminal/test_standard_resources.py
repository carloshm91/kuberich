"""Actual CLI standard tables, details, small screens and terminal restoration."""

import sys

from tests.support.standard_terminal import terminal_standard_views


def test_standard_resources_in_real_terminal(tmp_path):
    terminal_standard_views([sys.executable, "-m", "kubetrol"], tmp_path, "standard-resources")
