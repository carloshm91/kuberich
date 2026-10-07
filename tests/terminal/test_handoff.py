"""Native terminal input, job control and repeated Textual suspension/restoration."""

import sys

import pytest

from tests.support.handoff import terminal_handoff_trial


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "failure",
        "ctrl_c",
        "cancel",
        "spawn_error",
        "parent_shutdown",
        "hangup",
        "read_only",
    ],
)
def test_real_terminal_handoff(tmp_path, scenario):
    terminal_handoff_trial(sys.executable, tmp_path, scenario, name=f"handoff-{scenario}")
