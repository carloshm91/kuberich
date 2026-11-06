"""Installed console/module curated views run outside the source checkout."""

import hashlib

import pytest

from tests.support.curated_terminal import terminal_curated


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["families", "events"])
@pytest.mark.parametrize("entry_point", ["console", "module"])
async def test_installed_curated_resources_native_keyboard_and_cleanup(
    installed_wheel, artifacts, tmp_path, flow, entry_point
):
    binary, _ = installed_wheel
    command = (
        [str(binary / "kuberich")]
        if entry_point == "console"
        else [str(binary / "python"), "-m", "kuberich"]
    )
    await terminal_curated(
        command,
        tmp_path,
        evidence=f"installed-curated-{flow}-{entry_point}",
        flow=flow,
        wheel_sha256=hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
    )
