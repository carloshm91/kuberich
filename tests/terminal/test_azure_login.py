"""Explicit provider login never prints bearer JSON and restores the real TTY."""

import sys

import pytest

from tests.support.azure_handoff import azure_terminal_trial


@pytest.mark.parametrize("scenario", ["success", "never", "ctrl_c", "cancel", "parent_shutdown"])
def test_native_azure_login_lifecycle(tmp_path, scenario):
    azure_terminal_trial(sys.executable, tmp_path, scenario, name=f"azure-login-{scenario}")
