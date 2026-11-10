"""Actual source CLI review, explicit confirm, cancellation and terminal restoration."""

import sys

import pytest

from tests.support.node_maintenance_terminal import terminal_node_maintenance


@pytest.mark.parametrize("scenario", ["stop", "quit"])
def test_node_maintenance_owns_drain_and_restores_terminal(tmp_path, scenario):
    terminal_node_maintenance(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        scenario,
        evidence="node-maintenance-" + scenario,
    )
