"""Local history controls over a real child PTY while remote output continues."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web
from textual.events import Key, MouseScrollDown, MouseScrollUp, Paste
from textual.widgets import Static

from kuberich.config.schema import Settings
from kuberich.ui.app import KubeRichApp
from kuberich.ui.terminal import ShellScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api

CHILD = r"""
import os,select,tty
from pathlib import Path
root=Path(__file__).parent
tty.setraw(0)
(root/'pid').write_text(str(os.getpid()))
os.write(1,b'\x1b]52;c;cmVtb3RlLWNsaXBib2FyZA==\x07')
for i in range(1100):
    os.write(1,f'HISTORY-{i:04d} café界\r\n'.encode())
os.write(1,b'password=owned-secret\r\nLIVE PROMPT> ')
late=False
data=b''
while True:
    if not late and (root/'continue').exists():
        for i in range(9000):
            os.write(1,f'LATE-{i:04d} café界\r\n'.encode())
        os.write(1,b'\r\nLATE REMOTE OUTPUT\r\nLIVE PROMPT> ')
        late=True
    if not select.select([0],[],[],.01)[0]:
        continue
    chunk=os.read(0,4096)
    data+=chunk
    (root/'input').write_bytes(data)
    if b'alternate\r' in data:
        os.write(1,b'\x1b[?1049h\x1b[H\x1b[2JEDITOR ONLY\r\n')
        data=b''
    elif b'normal\r' in data:
        os.write(1,b'\x1b[?1049l')
        data=b''
    elif b'exit\r' in data:
        break
"""


@asynccontextmanager
async def embedded(tmp_path):
    value = pod("api")

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
            Settings(), logging.Logger("history", level=100), catalog=catalog_fixture(tmp_path, url)
        )
        app._process_environment = {**os.environ, "PATH": str(tmp_path)}
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "s")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ShellScreen)
                    and "LIVE PROMPT>" in "\n".join(app.screen.terminal.model.screen.display)
                )
            )
            yield app, pilot, app.screen
        assert app.processes.active_count == 0
        with pytest.raises(ProcessLookupError):
            os.kill(int((tmp_path / "pid").read_text()), 0)


@pytest.mark.asyncio
async def test_live_history_search_selection_copy_and_return_use_real_pty(tmp_path):
    async with embedded(tmp_path) as (app, pilot, screen):
        terminal = screen.terminal
        assert len(terminal.model.history.rows) == 1000 and terminal.model.history.dropped > 0
        assert app.clipboard == ""
        await pilot.press("alt+pageup")
        assert terminal.review is not None and terminal.has_focus
        output = Path("artifacts/ui")
        output.mkdir(parents=True, exist_ok=True)
        app.save_screenshot(filename="terminal-history-100.svg", path=str(output))
        frozen = terminal.review.rows
        assert "dropped" in str(screen.query_one("#shell-controls", Static).content)
        (tmp_path / "continue").touch()
        await wait_for(lambda: "LATE REMOTE" in "\n".join(terminal.model.screen.display))
        assert terminal.review.rows is frozen
        assert not any("LATE REMOTE" in row.text for row in frozen)
        await pilot.press("slash")
        screen.paste(Paste("HISTORY-0200"))
        await pilot.press("enter")
        assert frozen[terminal.review.cursor].text == "HISTORY-0200 café界"
        await pilot.press("v", "down", "y")
        assert app.clipboard == "HISTORY-0200 café界\nHISTORY-0201 café界"
        await pilot.press("v", "slash")
        screen.paste(Paste("password="))
        await pilot.press("enter", "y")
        assert app.clipboard == "password=[REDACTED]"
        await pilot.press("n", "N", "home", "pagedown", "pageup", "end", "k", "j")
        await pilot.press("ctrl+f", "a", "backspace", "escape")
        await pilot.press("slash")
        screen.paste(Paste("missing"))
        await pilot.press("enter")
        assert "No match" in str(screen.query_one("#shell-controls", Static).content)
        await pilot.press("slash")
        screen.paste(Paste("界" * 300 + "\x1b\n"))
        await pilot.press("a")
        assert len(screen.search_query) == 256
        await pilot.press("escape")
        screen.paste(Paste("discarded remote command\n"))
        await pilot.resize_terminal(40, 12)
        assert terminal.review.rows is frozen
        assert terminal.render_line(200).cell_length == 38
        await pilot.resize_terminal(100, 30)
        output = tmp_path / "input"
        assert not output.exists()  # Every review/search/paste key stayed local.
        await pilot.press("enter")
        assert terminal.review is None and "LATE REMOTE" in "\n".join(terminal.model.screen.display)
        await pilot.press(*"exit", "enter")
        await wait_for(lambda: app.screen is not screen)
        assert output.read_bytes() == b"exit\r"
        assert not terminal.model.history.rows and terminal.review is None


@pytest.mark.asyncio
async def test_history_button_mouse_editor_and_repeated_cleanup(tmp_path):
    async with embedded(tmp_path) as (app, pilot, screen):
        await pilot.press(*"alternate", "enter")
        await wait_for(lambda: "EDITOR ONLY" in "\n".join(screen.terminal.model.screen.display))
        await pilot.click("#shell-history")
        review = screen.terminal.review
        assert review is not None and screen.terminal.has_focus
        assert all("EDITOR ONLY" not in row.text for row in review.rows)
        await pilot.press("home")
        terminal = screen.terminal
        for event_type, cursor in [(MouseScrollDown, 3), (MouseScrollUp, 0)]:
            terminal.post_message(event_type(terminal, 3, 1, 0, 0, 0, False, False, False))
            await wait_for(lambda cursor=cursor: review.cursor == cursor)
        await pilot.click("#shell-terminal", offset=(3, 1))
        first = review.cursor
        await pilot.click("#shell-terminal", offset=(3, 3), shift=True)
        assert review.mark == first and review.cursor == first + 2
        await pilot.press("y")
        assert len(app.clipboard.splitlines()) == 3
        await pilot.click("#shell-history")
        assert screen.terminal.review is None
        for event_type in (MouseScrollDown, MouseScrollUp):
            terminal.post_message(event_type(terminal, 3, 1, 0, 0, 0, False, False, False))
        await pilot.pause()
        assert terminal.review is None
        await pilot.press(*"normal", "enter")
        await wait_for(lambda: "LIVE PROMPT>" in "\n".join(screen.terminal.model.screen.display))
        await pilot.press("shift+pageup", "escape", "shift+pageup", "q")
        assert screen.terminal.review is None
        await pilot.press("shift+pageup", "ctrl+right_square_bracket")
        await wait_for(lambda: app.screen is not screen)
        assert not screen.terminal.model.history.rows and screen.terminal.review is None
        old_terminal = screen.terminal
        old_pid = int((tmp_path / "pid").read_text())
        await pilot.press("s")
        await wait_for(
            lambda: (
                isinstance(app.screen, ShellScreen)
                and "LIVE PROMPT>" in "\n".join(app.screen.terminal.model.screen.display)
            )
        )
        assert app.screen.terminal is not old_terminal and app.screen.terminal.review is None
        with pytest.raises(ProcessLookupError):
            os.kill(old_pid, 0)
        await pilot.press("ctrl+right_square_bracket")
        await wait_for(lambda: not isinstance(app.screen, ShellScreen))


@pytest.mark.asyncio
async def test_stale_history_cannot_copy_and_owned_child_is_cancelled(tmp_path):
    async with embedded(tmp_path) as (app, pilot, screen):
        await pilot.press("shift+pageup")
        app.workspace.connect("kuberich-test-two")
        screen.key(Key("y", "y"))
        assert app.clipboard == ""
        screen.validate_target()
        await wait_for(lambda: app.screen is not screen)
        assert not screen.terminal.model.history.rows and screen.terminal.review is None
