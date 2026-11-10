"""Real offline entry, editor handoff, local save and native terminal restoration."""

import sys

import pytest

from tests.support.local_manifest_terminal import terminal_local_manifests


@pytest.mark.parametrize(
    "scenario", ["success", "noop", "failure", "invalid", "ctrl_c", "sigterm", "repeat"]
)
def test_actual_local_manifest_editor_and_terminal_restore(tmp_path, scenario):
    terminal_local_manifests(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "local-manifest-" + scenario,
        scenario=scenario,
        size=(80, 24) if scenario == "success" else (120, 36),
    )
