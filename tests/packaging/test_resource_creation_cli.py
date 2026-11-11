"""Installed creation console/module entrypoints operate outside the checkout."""

import pytest

from tests.support.resource_creation_cli import (
    retain_creation_cli_receipt,
    terminal_resource_creation_cli,
)


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_creation_public_dryrun_review_and_created_uid(
    installed_wheel, tmp_path, entry_point
):
    binary, _ = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    scenario = "installed-creation-cli-" + entry_point
    terminal_resource_creation_cli(command, tmp_path, scenario, initial_offline=True)
    retain_creation_cli_receipt(tmp_path, "installed", scenario)
