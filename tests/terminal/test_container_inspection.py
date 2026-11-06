"""Source CLI container inspection with real PTY navigation and terminal cleanup."""

import sys

import pytest

from tests.support.container_inspection_terminal import terminal_container_inspection


@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
def test_source_container_inspection_restores_terminal(tmp_path, size):
    terminal_container_inspection(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        evidence=f"source-container-inspection-{size[0]}",
        size=size,
    )
