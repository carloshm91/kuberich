"""Real source CLI local browsing, explicit clipboard/deletion and terminal restoration."""

import sys

import pytest

from tests.support.local_exports import terminal_local_exports


@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
def test_source_offline_export_browser_retains_owned_context_without_connecting(tmp_path, size):
    terminal_local_exports(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        evidence=f"source-local-exports-{size[0]}",
        size=size,
    )
