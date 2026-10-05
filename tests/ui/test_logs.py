"""Actual HTTP log output, Pilot focus/navigation and owned stream cleanup."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web
from textual.events import MouseScrollUp
from textual.widgets import Input, OptionList

from kubetrol.config.schema import Settings
from kubetrol.domain.log_view import WINDOWS
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.logs import LogScreen
from kubetrol.ui.scopes import ScopeScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api


async def ns(request):
    return namespaces("team", "default")


def app_for(tmp_path, url):
    return KubetrolApp(
        Settings(read_only=True),
        logging.Logger("logs", level=100),
        catalog=catalog_fixture(tmp_path, url),
    )


async def open_logs(app, pilot):
    await wait_for(lambda: app.resources.row_count > 0)
    await pilot.press("l")
    await wait_for(lambda: isinstance(app.screen, LogScreen))
    screen = app.screen
    await wait_for(lambda: len(screen.body.rows) > 0)
    return screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_live_view_search_vim_modes_copy_save_resize_and_return(tmp_path, size):
    closed = asyncio.Event()

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            response = web.StreamResponse()
            await response.prepare(request)
            try:
                await response.write(
                    "".join(
                        f"2026-10-05T12:00:00Z line-{i:03} 你好 [red]literal[/red] token=hidden-log-value\n"
                        for i in range(80)
                    ).encode()
                )
                while request.transport is not None and not request.transport.is_closing():
                    await asyncio.sleep(0.005)
            finally:
                closed.set()
            return response
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count > 0)
            before = app.resources.capture_viewport()
            screen = await open_logs(app, pilot)
            await wait_for(lambda: len(screen.body.rows) == 80)
            # Retention/layout publish before Textual's deferred viewport refresh.
            await wait_for(lambda: screen.body.follow and screen.body.scroll_y > 0)
            await pilot.pause()
            assert screen.body.follow and screen.body.scroll_y > 0
            assert screen.body.show_vertical_scrollbar
            screen.body.post_message(
                MouseScrollUp(screen.body, 1, 1, 0, -1, 0, False, False, False)
            )
            await pilot.pause()
            assert not screen.body.follow
            await pilot.press("G")
            assert "hidden-log-value" not in screen.history.export()
            assert "[red]literal[/red]" in screen.history.export()
            await pilot.press("g", "j", "k", "ctrl+f", "ctrl+b", "ctrl+d", "ctrl+u")
            assert not screen.body.follow
            await pilot.press("G", "p")
            assert screen.body.follow and screen.paused
            await pilot.press("g", "G")
            assert screen.paused  # jumping does not resume reception
            await pilot.press("p", "t", "w", "L", "z")
            await pilot.pause()
            assert not screen.paused and not screen.timestamps and screen.wrap
            assert screen.body.column_lock
            assert screen.query_one("#log-dialog").has_class("fullscreen")
            assert screen.body.scrollable_content_region.height >= 1
            await pilot.press("slash", *"line-00", "enter", "n", "N")
            await pilot.pause()
            assert app.focused is screen.body and len(screen.body.matches) == 10
            assert "Matching line" in screen.message and not screen.body.follow
            await pilot.press("m", "ctrl+y")
            assert screen.history.marks
            assert app.clipboard == screen.history.export()
            await pilot.press("slash", "ctrl+a", "ctrl+k", *"jkgGhlpvtw", "escape")
            assert screen.search.value == "jkgGhlpvtw" and app.focused is screen.body
            await pilot.press("slash", "ctrl+a", "ctrl+k", "enter")
            assert "No matching" in screen.message
            await pilot.press("ctrl+s")
            destination = tmp_path / "retained.log"
            app.screen.query_one("#log-value", Input).value = str(destination)
            await pilot.press("enter")
            await wait_for(lambda: destination.exists())
            await wait_for(lambda: screen._save_task.done())
            assert destination.read_text() == screen.history.export()
            await pilot.press("question_mark")
            assert type(app.screen).__name__ == "LogHelpScreen"
            await pilot.press("escape")
            await pilot.resize_terminal(55, 16)
            await pilot.pause()
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"logs-{size[0]}.svg", path=str(evidence))
            await pilot.press("C")
            assert not screen.history.entries
            await pilot.press("escape")
            await wait_for(closed.is_set)
            assert app.resources.capture_viewport() == before
        assert screen._controller.done() and screen._renderer.done() and screen._read_task.done()


async def choose(pilot, app, index):
    await wait_for(lambda: isinstance(app.screen, ScopeScreen))
    app.screen.query_one(OptionList).highlighted = index
    await pilot.press("enter")


@pytest.mark.asyncio
async def test_regular_init_previous_windows_since_validation_buttons_and_save_error(tmp_path):
    requests = []
    value = pod("api")
    value["spec"]["initContainers"] = [{"name": "init"}]

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            requests.append(dict(request.query))
            if request.query["previous"] == "true":
                return web.Response(status=400)
            return web.Response(body=b"2026-10-05T12:00:00Z selected container output\n")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("l")
            screen = next(value for value in app.screen_stack if isinstance(value, LogScreen))
            await choose(pilot, app, 1)
            await wait_for(lambda: screen.message.startswith("Stream complete"))
            assert screen.container == "init" and requests[-1]["container"] == "init"
            await pilot.click("#log-container")
            await choose(pilot, app, 0)
            await wait_for(lambda: requests[-1]["container"] == "app")
            await pilot.click("#log-previous")
            await wait_for(lambda: "Previous container logs unavailable" in screen.message)
            assert not screen.history.entries and requests[-1]["follow"] == "false"
            await pilot.press("v")
            await wait_for(lambda: screen.message.startswith("Stream complete"))
            await pilot.click("#log-window")
            await choose(pilot, app, WINDOWS.index("Last 5m"))
            await wait_for(lambda: requests[-1].get("sinceSeconds") == "300")
            assert "tailLines" not in requests[-1]
            await pilot.press("o")
            await choose(pilot, app, len(WINDOWS))
            field = app.screen.query_one("#log-value", Input)
            field.value = "bad-time"
            await pilot.press("enter")
            assert "RFC3339" in str(app.screen.query_one("#log-request-error").content)
            field.value = "2026-10-05T12:00:00"
            await pilot.press("enter")
            assert "offset" in str(app.screen.query_one("#log-request-error").content)
            field.value = "2026-10-05T14:00:00+02:00"
            await pilot.click("#log-accept")
            await wait_for(lambda: requests[-1].get("sinceTime") == "2026-10-05T12:00:00Z")
            original = screen._read_task
            await pilot.press("o", "escape")
            assert screen._read_task is original
            await pilot.press("o")
            await choose(pilot, app, len(WINDOWS))
            await pilot.click("#log-cancel")
            assert screen._read_task is original
            await pilot.click("#log-wrap")
            await pilot.click("#log-timestamps")
            await pilot.click("#log-help")
            await pilot.click("#log-help-back")
            await pilot.press("ctrl+s")
            field = app.screen.query_one("#log-value", Input)
            await pilot.press("enter")
            assert "Enter a value" in str(app.screen.query_one("#log-request-error").content)
            path = tmp_path / "already"
            path.write_text("keep")
            field.value = str(path)
            await pilot.press("enter")
            await wait_for(lambda: "Cannot save logs" in screen.message)
            assert path.read_text() == "keep"
            await pilot.click("#log-back")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 500])
async def test_denied_deleted_and_failed_log_reads_are_clear_and_can_close(tmp_path, status):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            return web.Response(status=status, text="token=hidden-error")
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("l")
            screen = app.screen
            await wait_for(lambda: str(status) in screen.message)
            assert not screen.history.entries and "hidden-error" not in screen.message
            await pilot.press("escape")
            assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_pause_backpressures_new_output_and_reading_history_keeps_receiving(tmp_path):
    values = asyncio.Queue()
    closed = asyncio.Event()

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            response = web.StreamResponse()
            await response.prepare(request)
            try:
                await response.write(b"initial " + b"x" * 120 + b"\n")
                while request.transport is not None and not request.transport.is_closing():
                    try:
                        value = await asyncio.wait_for(values.get(), 0.02)
                    except TimeoutError:
                        continue
                    await response.write(value)
            finally:
                closed.set()
            return response
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(40, 12)) as pilot:
            screen = await open_logs(app, pilot)
            await pilot.click("#log-pause")
            await values.put(b"queued while paused\n")
            await asyncio.sleep(0.1)
            assert len(screen.history.entries) == 1
            await pilot.click("#log-follow")
            assert screen.paused and screen.body.follow
            await pilot.click("#log-pause")
            await wait_for(lambda: len(screen.history.entries) == 2)
            app.set_focus(screen.body)
            await pilot.press("g")
            await values.put(b"".join(f"line-{i}\n".encode() for i in range(30)))
            await wait_for(lambda: len(screen.body.rows) == 32)
            await pilot.pause()
            assert screen.body.scroll_y == 0 and not screen.body.follow and not screen.paused
            await pilot.press("f", "right", "L")
            x = screen.body.scroll_x
            assert x > 0
            await values.put(b"new line\n")
            await wait_for(lambda: len(screen.body.rows) == 33)
            assert screen.body.column_lock and screen.body.scroll_x == x
            await pilot.press("g", "m", "j", "h", "l")
            anchor = screen.body.first_visible
            assert anchor is not None and anchor[0] == 2
            await values.put(b"retained arrival\n")
            await wait_for(lambda: len(screen.body.rows) == 34)
            await pilot.pause()
            assert screen.body.first_visible == anchor and not screen.body.follow
            await values.put(b"".join(f"eviction-{i}\n".encode() for i in range(5010)))
            await wait_for(lambda: screen.history.buffer.dropped_lines == 44)
            await wait_for(lambda: screen.body.rows and screen.body.rows[0][0] == 45)
            await pilot.pause()
            assert screen.body.first_visible == (45, 0) and not screen.body.follow
            assert not screen.history.marks and len(screen.body._cache) == 5000
            await pilot.press("ctrl+q")
        await wait_for(closed.is_set)
        assert screen._read_task.done() and app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_scope_switch_invalidates_even_under_a_container_dialog_and_drains_paused_read(
    tmp_path, nested
):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            return await stable_watch(
                request, {"type": "literal"}
            )  # not interpreted as watch events
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await open_logs(app, pilot)
            await pilot.press("p")
            if nested:
                await pilot.press("c")
            app.workspace.select_namespace("other")
            await wait_for(lambda: screen.stale)
            await wait_for(lambda: screen._read_task.done())
            assert not screen.history.entries and not screen.body.rows
            if nested:
                previous_read = screen._read_task
                await choose(pilot, app, 0)
                assert screen._read_task is previous_read and "stale" in screen.message
            screen.action_copy()
            assert app.clipboard == "" and "stale" in screen.message
            await pilot.press("question_mark")
            await pilot.press("escape", "escape")
            assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_selected_uid_deletion_under_stream_rejects_replacement_output(tmp_path):
    updates = asyncio.Queue()

    async def handler(request):
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            try:
                while request.transport is not None and not request.transport.is_closing():
                    try:
                        value = await asyncio.wait_for(updates.get(), 0.02)
                    except TimeoutError:
                        continue
                    await response.write(frame(value))
            except ConnectionResetError:
                pass
            return response
        if request.path.endswith("/log"):
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(b"original pod\n")
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.01)
            return response
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await open_logs(app, pilot)
            await updates.put({"type": "DELETED", "object": pod("api")})
            await wait_for(lambda: screen.stale)
            await updates.put({"type": "ADDED", "object": pod("api", uid="replacement")})
            await wait_for(lambda: app.resources.row_count == 1)
            await wait_for(lambda: screen._read_task.done())
            assert screen.stale and not screen.history.entries and screen._read_task.done()
            await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot", [False, True])
async def test_quiet_open_and_empty_snapshot_show_distinct_states_and_close(tmp_path, snapshot):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            if snapshot:
                return web.Response(body=b"")
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.01)
            return response
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("l")
            screen = app.screen
            expected = "Stream complete · no output" if snapshot else "Waiting for log output"
            await wait_for(lambda: screen.message == expected)
            assert not screen.history.entries and not screen.body.rows
            await pilot.press("m", "escape")
        assert screen._read_task.done() and app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["read", "render", "save"])
async def test_unexpected_failure_uses_app_cleanup_and_drains_viewer_tasks(
    tmp_path, monkeypatch, stage
):
    from kubetrol.services.logs import LogStream
    from kubetrol.ui import logs
    from kubetrol.ui.log_body import LogBody

    async def broken(*args, **kwargs):
        raise RuntimeError("owned-log-failure")

    if stage == "read":
        monkeypatch.setattr(LogStream, "run", broken)
    elif stage == "render":
        monkeypatch.setattr(LogBody, "load", broken)
    else:
        monkeypatch.setattr(logs, "save_logs", broken)

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            return web.Response(body=b"owned output\n")
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        with pytest.raises(RuntimeError, match="owned-log-failure"):
            async with app.run_test() as pilot:
                await wait_for(lambda: app.resources.row_count == 1)
                # Direct invocation captures the screen before an immediate fault.
                app.action_logs()
                screen = app.screen
                if stage == "save":
                    await wait_for(lambda: len(screen.body.rows) == 1)
                    await pilot.press("ctrl+s")
                    app.screen.query_one("#log-value", Input).value = str(tmp_path / "save")
                    await pilot.press("enter")
                    await wait_for(
                        lambda: screen._save_task is not None and screen._save_task.done()
                    )
                elif stage == "render":
                    await wait_for(lambda: screen._renderer is not None and screen._renderer.done())
                else:
                    await wait_for(
                        lambda: screen._read_task is not None and screen._read_task.done()
                    )
        assert app.sessions.client is None and screen.closed
        assert screen._controller.done() and screen._renderer.done()
        assert screen._read_task is None or screen._read_task.done()
        assert screen._save_task is None or screen._save_task.done()


@pytest.mark.asyncio
async def test_high_volume_batches_bound_history_layout_and_head_stops_at_oldest_thousand(tmp_path):
    requests = []
    output = "".join(f"2026-10-05T12:00:00Z line-{i:05} 你好\n" for i in range(15000)).encode()

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            requests.append(dict(request.query))
            return web.Response(body=output)
        return web.json_response(
            collection(pod("api")) if request.path.endswith("/pods") else pod("api")
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(40, 12)) as pilot:
            screen = await open_logs(app, pilot)
            await wait_for(lambda: screen.message == "Stream complete")
            await wait_for(
                lambda: len(screen.body.rows) == 5000 and screen.body.rows[0][0] == 10001
            )
            assert screen.history.buffer.dropped_lines == 10000
            assert len(screen.body._cache) == 5000
            assert screen.body.render_batches < 100
            assert "10000 dropped" in str(screen.status.content)
            await pilot.press("g", "m", "w")
            await pilot.pause()
            assert not screen.body.follow and screen.history.marks
            await pilot.press("o")
            await choose(pilot, app, WINDOWS.index("Head 1000"))
            await wait_for(lambda: screen.message == "Head snapshot complete")
            assert len(screen.history.entries) == 1000
            assert "line-00000" in screen.history.entries[0].line.text
            assert "tailLines" not in requests[-1] and requests[-1]["follow"] == "false"
            await pilot.press("escape")
