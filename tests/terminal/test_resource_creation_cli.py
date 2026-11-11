"""Public source entrypoint performs create-only HTTP effects and owned cancellation."""

import sys

import pytest

from tests.support.resource_creation_cli import terminal_resource_creation_cli


@pytest.mark.parametrize(
    "mode,initial_offline", [("success", False), ("cancel", False), ("success", True)]
)
def test_public_creation_cli_records_actual_uid_or_uncertain_committed_write(
    tmp_path, mode, initial_offline
):
    terminal_resource_creation_cli(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "resource-creation-cli-" + mode + ("-offline" if initial_offline else ""),
        mode=mode,
        initial_offline=initial_offline,
    )
