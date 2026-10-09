"""Native copy review/confirmation and terminal restoration from source and fresh wheel."""

import asyncio
import sys

import pytest
from aiohttp import web

from kuberich.domain.transfers import TransferDirection
from tests.support.distribution import artifacts as artifacts
from tests.support.distribution import installed_wheel as installed_wheel
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.transfer_terminal import terminal_transfer
from tests.support.workspace import stable_watch, workspace_api
from tests.ui.test_logs import ns


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", list(TransferDirection))
@pytest.mark.parametrize("entry", ["source", "installed"])
async def test_native_copy_form_is_restored_and_retains_scope(
    tmp_path, installed_wheel, direction, entry
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
            terminal_transfer,
            command,
            tmp_path,
            url,
            direction,
            "transfer-" + entry + "-" + direction.name.lower(),
        )
