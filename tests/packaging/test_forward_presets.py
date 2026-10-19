"""The built console and module resolve named presets outside the checkout."""

import pytest

from tests.support.forward_presets import named_terminal_forward


@pytest.mark.parametrize("entry_point", ["console", "module"])
def test_installed_named_forward_annotations(installed_wheel, entry_point, monkeypatch):
    binary, directory = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    named_terminal_forward(
        command, directory, f"installed-forward-presets-{entry_point}", monkeypatch
    )
