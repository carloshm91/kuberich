"""Real source CLI filename geometry, filtering, refresh and terminal restoration."""

import sys

import pytest

from tests.support.export_browser_geometry import terminal_export_browser_geometry


@pytest.mark.parametrize("resize", [False, True])
def test_offline_browser_long_filename_real_cli_initial_and_resize(tmp_path, resize):
    terminal_export_browser_geometry(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        evidence="source-export-browser-geometry-" + ("resize" if resize else "native100"),
        resize=resize,
    )
