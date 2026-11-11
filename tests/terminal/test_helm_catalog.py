"""The actual public CLI catalog/editor path with no available Helm executable."""

import sys

import pytest

from tests.support.helm_catalog_terminal import terminal_helm_catalog


@pytest.mark.parametrize("wrapped", [False, True])
def test_public_cli_catalog_shell_editor_cached_readonly_and_missing_helm(tmp_path, wrapped):
    calls = []

    def wrap(argv, environment):
        calls.append((argv, environment))
        return ["/usr/bin/env", *(name + "=" + value for name, value in environment.items()), *argv]

    receipt = terminal_helm_catalog(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "helm-public-cli-wrapped" if wrapped else "helm-public-cli",
        wrap=wrap if wrapped else None,
        controller_environment={"OWNED_CLI_CONTROLLER": "separate"},
    )
    assert receipt["editor_sessions"] == 2 and receipt["owned_state_removed"]
    assert receipt["wrapped"] is wrapped
    if wrapped:
        assert len(calls) == 2
        assert "OWNED_CLI_CONTROLLER" not in calls[0][1]
        assert calls[0][1]["HOME"] == str(tmp_path / "home")
