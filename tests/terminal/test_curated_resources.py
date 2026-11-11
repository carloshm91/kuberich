"""Source resource, admission and Event keyboard lifetimes over an owned API."""

import sys

import pytest

from tests.support.curated_terminal import terminal_curated


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["families", "events", "admission"])
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_source_curated_resources_native_keyboard_and_cleanup(tmp_path, flow, size):
    await terminal_curated(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        evidence=f"source-curated-{flow}-{size[0]}",
        flow=flow,
        size=size,
    )
