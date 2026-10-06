"""A real PTY child within the running Textual app, including local/remote keys."""

import asyncio
import logging
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web
from textual.events import Key, Paste

from kubetrol.config.schema import Settings
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.containers import ContainerScreen
from kubetrol.ui.terminal import ShellScreen, _color
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api

CHILD = """
import os,sys,tty
from pathlib import Path
path=Path(__file__).with_name('input')
Path(__file__).with_name('pid').write_text(str(os.getpid()))
tty.setraw(0)
os.write(1,b'\\x1b[31mREMOTE $ \\x1b[0m\\r\\n\\x1b[?1h\\x1b[?2004h')
data=b''
while True:
    chunk=os.read(0,4096)
    data+=chunk
    path.write_bytes(data)
    if b'exit\\r' in data:
        break
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
@pytest.mark.parametrize("ending", ["back", "exit", "quit", "stale", "uid"])
async def test_real_embedded_shell_keys_frame_paste_resize_and_owned_return(tmp_path, size, ending):
    value = pod("api")
    updates = asyncio.Queue()

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                try:
                    await response.write(frame(await asyncio.wait_for(updates.get(), 0.02)))
                except TimeoutError:
                    continue
            return response
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    binary = tmp_path / "kubectl"
    binary.write_text(f"#!{sys.executable}\n" + CHILD)
    binary.chmod(0o700)
    path = tmp_path / "input"
    async with workspace_api(ns, handler) as url:
        app = KubetrolApp(
            Settings(),
            logging.Logger("embedded", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        app._process_environment = {**os.environ, "PATH": str(tmp_path)}
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            viewport = app.resources.capture_viewport()
            await pilot.press("enter")
            containers = app.screen
            await pilot.press("s")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ShellScreen)
                    and "REMOTE $" in "\n".join(app.screen.terminal.model.screen.display)
                )
            )
            screen = app.screen
            credential_directory = Path(app.sessions.client.directory.name)
            assert screen.terminal.has_focus and len(app.screen_stack) == 3
            assert "kubetrol-test-one" in str(screen.query_one("#shell-context").content)
            assert "api" in str(screen.query_one("#shell-target").content)
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"embedded-shell-{size[0]}.svg", path=str(output))
            await pilot.press("q", "colon", "slash", "j", "k", "escape", "tab", "ctrl+c", "up")
            app.post_message(Paste("Unicode á\r\n"))
            await wait_for(lambda: path.exists() and "á".encode() in path.read_bytes())
            data = path.read_bytes()
            assert data.startswith(b"q:/jk\x1b\t\x03\x1bOA")
            assert b"\x1b[200~Unicode " + "á".encode() + b"\r\x1b[201~" in data
            assert app.screen is screen and not app._exit
            await pilot.resize_terminal(80, 25)
            assert (screen.terminal.model.screen.columns, screen.terminal.model.screen.lines) == (
                78,
                19,
            )
            assert screen.terminal.render_line(200).cell_length == 78
            screen.terminal.model.feed("界".encode())
            screen.terminal.render_line(screen.terminal.model.screen.cursor.y)
            screen.paste(Paste("x" * 16385))
            assert "too large" in str(screen.query_one("#shell-controls").content)
            screen.terminal.pending.extend(b"x" * 65536)
            endpoint = screen.terminal.endpoint
            screen.terminal.endpoint = None
            screen.key(Key("x", "x"))
            assert "busy" in str(screen.query_one("#shell-controls").content)
            screen.terminal.pending.clear()
            screen.terminal.endpoint = endpoint
            pid = int((tmp_path / "pid").read_text())
            if ending == "quit":
                await pilot.press("ctrl+q")
            elif ending == "exit":
                await pilot.press(*"exit", "enter")
            elif ending == "stale":
                app.workspace.connect("kubetrol-test-two")
                screen.validate_target()
            elif ending == "uid":
                await updates.put({"type": "DELETED", "object": value})
                replacement = pod("api", uid="replacement")
                replacement["metadata"]["resourceVersion"] = "new-version"
                await updates.put({"type": "ADDED", "object": replacement})
            else:
                await pilot.press("ctrl+right_square_bracket")
            if ending != "quit":
                await wait_for(lambda: screen._session_task is None)
                assert app.screen is containers and isinstance(containers, ContainerScreen)
                assert not list(credential_directory.glob("exec-*.json"))
                if ending in {"back", "exit"}:
                    await pilot.press("escape")
                    assert app.resources.capture_viewport() == viewport
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert app.processes.active_count == 0 and app.sessions.client is None


def test_color_boundaries_are_literal_and_invalid_colors_are_inert():
    assert _color("brown") == "yellow" and _color("red") == "red"
    assert _color("abcdef") == "#abcdef"
    for value in ["default", "notacolor", "00000000", "zzzzzz"]:
        assert _color(value) is None


@pytest.mark.asyncio
async def test_immediate_close_after_mount_returns_without_starting_process(tmp_path, monkeypatch):
    # Delay preparation, then cancel the screen before the transport can be launched.
    value = pod("api")

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if not request.path.endswith("/pods"):
            await asyncio.sleep(0.2)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("early"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            containers = app.screen
            containers.action_shell()
            await wait_for(
                lambda: isinstance(app.screen, ShellScreen) and app.screen._session_task is not None
            )
            app.screen.close_shell()
            await wait_for(lambda: app.screen is containers)
            assert app.processes.active_count == 0
