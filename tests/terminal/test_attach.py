"""Source/fresh-wheel PTYs restore after attach EOF, error, interruption and exit."""

import asyncio
import sys

import pytest
from aiohttp import web

from tests.support.attach_terminal import terminal_attach
from tests.support.distribution import artifacts as artifacts
from tests.support.distribution import installed_wheel as installed_wheel
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, workspace_api
from tests.ui.test_logs import ns


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["source", "installed"])
@pytest.mark.parametrize(
    "scenario", ["eof", "failure", "interrupt", "detach", "close", "terminate", "quit"]
)
async def test_native_attach_endings_restore_and_reap_from_each_distribution(
    tmp_path, installed_wheel, entry, scenario
):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        value = pod("api", uid="api-uid")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    command = (
        [sys.executable, "-m", "kuberich"]
        if entry == "source"
        else [str(installed_wheel[0] / "kuberich")]
    )
    async with workspace_api(ns, handler) as url:
        await asyncio.to_thread(
            terminal_attach, command, tmp_path, url, scenario, "attach-" + entry + "-" + scenario
        )
