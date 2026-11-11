"""Production Helm values/editor handoff, native signals and private-file restoration."""

import sys

import pytest

from tests.support.helm_lifecycle_terminal import terminal_helm_values


@pytest.mark.parametrize(
    "scenario", ["success", "noop", "failure", "malformed", "ctrl_c", "sigterm", "repeat"]
)
def test_actual_helm_values_editor_and_terminal_restoration(tmp_path, scenario):
    terminal_helm_values(
        sys.executable, tmp_path, "helm-values-editor-" + scenario, scenario=scenario
    )
