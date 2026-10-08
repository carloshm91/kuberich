"""Actual editor handoff, failure/cancellation/no-op and terminal modes."""

import sys

import pytest

from tests.support.editing_terminal import terminal_editing


@pytest.mark.parametrize("scenario", ["success", "noop", "failure", "malformed", "ctrl_c"])
def test_actual_editor_and_terminal_restoration(tmp_path, scenario):
    terminal_editing(
        [sys.executable, "-m", "kuberich"], tmp_path, "editor-" + scenario, scenario=scenario
    )
