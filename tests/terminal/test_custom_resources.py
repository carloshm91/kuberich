"""Source CLI generic discovery, columns, inspection, scopes and terminal restore."""

import sys

from tests.support.custom_terminal import terminal_custom_views


def test_generic_resources_in_real_terminal(tmp_path):
    terminal_custom_views([sys.executable, "-m", "kuberich"], tmp_path, "custom-resources")
