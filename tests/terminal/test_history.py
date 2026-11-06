"""Source CLI historical metrics use explicit owned HTTP and restore the terminal."""

import sys

import pytest

from tests.support.history_terminal import terminal_history


@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
def test_source_history_keyboard_scopes_ranges_and_cleanup(tmp_path, size):
    terminal_history(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        evidence=f"source-history-{size[0]}",
        size=size,
    )
