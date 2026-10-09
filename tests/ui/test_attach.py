"""Actual embedded PTY attachment and remote detach-key routing in Textual."""

import json
import logging
import os
import sys

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.terminal import ShellScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api

CHILD = """
import json,os,sys,tty
from pathlib import Path
root=Path(__file__).parent
(root/'argv.json').write_text(json.dumps(sys.argv[1:]))
(root/'pid').write_text(str(os.getpid()))
tty.setraw(0)
os.write(1,b'ATTACH READY\\r\\n')
data=b''
while True:
    data+=os.read(0,4096)
    (root/'input').write_bytes(data)
    if b'\\x10\\x11' in data:
        break
"""


def test_attach_command_is_available_and_gated_before_any_transport():
    assert CommandService(AccessPolicy(False)).resolve(":attach") is Command.ATTACH
    with pytest.raises(AppError, match="Read-only"):
        CommandService(AccessPolicy(True)).resolve(":attach")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,observed",
    [
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ],
)
@pytest.mark.parametrize("ending", ["detach", "back", "quit", "quit-after-other-key"])
async def test_selected_running_container_uses_an_embedded_pty_and_keeps_detach_sequence(
    tmp_path, kind, observed, ending
):
    value = pod("api")
    value["spec"] = {kind: [{"name": "app"}]}
    value["status"] = {"phase": "Running", observed: [{"name": "app", "state": {"running": {}}}]}

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    binary = tmp_path / "kubectl"
    binary.write_text(f"#!{sys.executable}\n" + CHILD)
    binary.chmod(0o700)
    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("attach", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = {**os.environ, "PATH": str(tmp_path)}
        async with app.run_test(size=(80, 25)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            viewport = app.resources.capture_viewport()
            await pilot.press("colon", *"attach", "enter")
            assert isinstance(app.screen, ContainerScreen)
            containers = app.screen
            await pilot.press("a")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ShellScreen)
                    and "ATTACH READY" in "\n".join(app.screen.terminal.model.screen.display)
                )
            )
            screen = app.screen
            assert screen.attach_mode and "existing process" in str(
                screen.query_one("#shell-heading").content
            )
            assert "Ctrl+P, Ctrl+Q" in str(screen.query_one("#shell-controls").content)
            arguments = json.loads((tmp_path / "argv.json").read_text())
            assert arguments[3:] == [
                "attach",
                "--stdin",
                "--tty",
                "--container=app",
                "--detach-keys=ctrl-p,ctrl-q",
                "--pod-running-timeout=1s",
                "api",
            ]
            path = screen.request.path
            pid = int((tmp_path / "pid").read_text())
            await pilot.press("colon", "slash", "q", "ctrl+c")
            await wait_for(
                lambda: (
                    (tmp_path / "input").exists()
                    and b":/q\x03" in (tmp_path / "input").read_bytes()
                )
            )
            assert app.screen is screen and not app._exit
            if ending == "detach":
                await pilot.press("ctrl+p", "ctrl+q")
            elif ending == "back":
                await pilot.press("ctrl+right_square_bracket")
            elif ending == "quit-after-other-key":
                await pilot.press("ctrl+p", "x", "ctrl+q")
            else:
                await pilot.press("ctrl+q")
            if ending in {"detach", "back"}:
                await wait_for(lambda: app.screen is containers)
                assert not app._exit and not path.exists()
                assert "Attach closed" in str(containers.status.content)
                if ending == "detach":
                    assert b"\x10\x11" in (tmp_path / "input").read_bytes()
                await pilot.press("escape")
                assert app.resources.capture_viewport() == viewport
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not path.exists() and app.processes.active_count == 0


@pytest.mark.asyncio
async def test_readonly_attach_routes_make_no_pod_preflight_or_process(tmp_path):
    gets = []
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if not request.path.endswith("/pods"):
            gets.append(request.path)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("readonly-attach", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("colon", *"attach", "enter")
            assert len(app.screen_stack) == 1
            await pilot.press("enter", "a")
            assert isinstance(app.screen, ContainerScreen)
            assert "Read-only" in str(app.screen.status.content)
            assert not gets and app.processes.active_count == 0
