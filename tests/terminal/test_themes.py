"""Actual no-color CLI theme preferences, About and native terminal restoration."""

import sys

from tests.support.themes_terminal import terminal_themes


def test_theme_preview_save_and_about_in_real_terminal(tmp_path):
    terminal_themes([sys.executable, "-m", "kuberich"], tmp_path, "themes-mono")
