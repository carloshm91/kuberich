"""Enter drill-down, captured targets and return navigation over an owned HTTP API."""

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import DataTable, Static

from kubetrol.errors import AppError
from kubetrol.ui.containers import ContainerScreen
from kubetrol.ui.logs import LogScreen
from kubetrol.ui.scopes import ScopeScreen
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_logs import app_for, ns


@pytest.mark.asyncio
@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_enter_pod_containers_selected_logs_and_back_preserves_both_viewports(
    tmp_path, multiple, size
):
    requests = []
    value = pod("api")
    if multiple:
        value["spec"]["containers"] += [{"name": f"worker-{i:02}"} for i in range(24)]
        value["spec"]["initContainers"] = [
            {"name": "init"},
            {"name": "sidecar", "restartPolicy": "Always"},
        ]

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            requests.append(dict(request.query))
            return web.Response(body=b"selected [red]literal[/red] token=hidden-output\n")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            before = app.resources.capture_viewport()
            await pilot.press("enter")
            assert isinstance(app.screen, ContainerScreen) and not requests
            containers = app.screen
            assert app.focused is containers.table
            assert containers.table.row_count == (27 if multiple else 1)
            assert containers.table.content_region.height >= 1
            assert containers.query_one("#container-back").region.bottom <= size[1]
            assert containers.table.get_row("app")[1].plain == "App"
            if multiple:
                assert containers.table.get_row("init")[1].plain == "Init"
                assert containers.table.get_row("sidecar")[1].plain == "Sidecar"
                await pilot.press("G", "k", "j", "g", "G", "up")
                assert containers.table.cursor_row == 25
                assert containers.table.scroll_y > 0
            selected = "init" if multiple else "app"
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"containers-{size[0]}-{multiple}.svg", path=str(evidence))
            row, scroll = containers.table.cursor_row, containers.table.scroll_y
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and app.screen.body.rows)
            logs = app.screen
            assert logs.container == selected and requests[-1]["container"] == selected
            assert logs.containers == containers.names and len(app.screen_stack) == 3
            # A delayed parent selection must not open a second log viewer.
            key = containers.table.coordinate_to_cell_key(containers.table.cursor_coordinate)
            containers.table.post_message(DataTable.RowSelected(containers.table, row, key.row_key))
            await pilot.pause()
            assert app.screen is logs and len(app.screen_stack) == 3
            assert "hidden-output" not in logs.history.export()
            assert "[red]literal[/red]" in logs.history.export()
            if multiple:
                await pilot.press("c")
                assert isinstance(app.screen, ScopeScreen)
                assert app.screen.values == containers.names
                await pilot.press("escape")
            await pilot.press("escape")
            await wait_for(lambda: logs._controller.done() and logs._renderer.done())
            assert app.screen is containers
            assert containers.table.cursor_row == row and containers.table.scroll_y == scroll
            await pilot.press("l")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and app.screen.body.rows)
            assert app.screen.container == selected
            await pilot.press("escape")
            await pilot.click("#container-back")
            assert app.resources.capture_viewport() == before and len(app.screen_stack) == 1
            await pilot.press("enter", "escape")
            assert len(app.screen_stack) == 1
        assert app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_scope_change_invalidates_captured_containers_even_under_logs(tmp_path, nested):
    requests = []
    value = pod("api")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            requests.append(request.path)
            return await stable_watch(request, {"type": "literal log"})
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            containers = app.screen
            if nested:
                await pilot.press("enter")
                logs = app.screen
                await wait_for(lambda: logs.history.entries)
            app._namespace_selected("default")
            await wait_for(lambda: containers.table.disabled)
            if nested:
                await wait_for(lambda: logs.stale and not logs.history.entries)
                await pilot.press("escape")
                await wait_for(lambda: logs._read_task.done())
            count = len(requests)
            await pilot.press("l")
            assert app.screen is containers and len(requests) == count
            assert "stale" in str(containers.status.content)
            await pilot.press("escape")
            assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_pod_deleted_and_recreated_during_container_selection_cannot_open_logs(tmp_path):
    updates = asyncio.Queue()
    value = pod("api")
    requests = []

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
        if request.path.endswith("/log"):
            requests.append(request.path)
            return web.Response(body=b"replacement must not appear\n")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            containers = app.screen
            await updates.put({"type": "DELETED", "object": value})
            replacement = pod("api", uid="replacement-uid")
            replacement["metadata"]["resourceVersion"] = "new-rv"
            await updates.put({"type": "ADDED", "object": replacement})
            await wait_for(lambda: containers.table.disabled)
            await pilot.press("l")
            assert not requests and app.screen is containers
            await pilot.press("escape")
            await wait_for(lambda: app.resources.selected_uid == "replacement-uid")


@pytest.mark.asyncio
async def test_recreation_between_snapshot_and_log_verification_never_reads_replacement(tmp_path):
    value, replacement = pod("api"), pod("api", uid="replacement-uid")
    requests = []

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            requests.append(request.path)
            return web.Response(body=b"replacement must not appear\n")
        return web.json_response(
            collection(value) if request.path.endswith("/pods") else replacement
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "enter")
            await wait_for(
                lambda: isinstance(app.screen, LogScreen) and "stale" in app.screen.message
            )
            assert not requests and not app.screen.history.entries
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
async def test_empty_or_invalid_container_spec_reports_error_without_drilldown(tmp_path):
    value = pod("api")
    value["spec"]["containers"] = []

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value))

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            assert len(app.screen_stack) == 1
            assert "no regular/init" in str(app.query_one("#status", Static).content)


def test_container_and_log_constructor_reject_missing_selection():
    with pytest.raises(AppError, match="no regular/init"):
        ContainerScreen(None, {"spec": {}})
    with pytest.raises(AppError, match="unavailable"):
        LogScreen(None, ("app",), selected="absent")


@pytest.mark.asyncio
async def test_pod_enter_captures_the_selected_event_uid_before_later_cursor_movement(tmp_path):
    values = [pod("api"), pod("worker")]

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(*values))

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 2)
            key = app.resources.coordinate_to_cell_key(app.resources.cursor_coordinate)
            event = DataTable.RowSelected(app.resources, 0, key.row_key)
            app.resources.move_cursor(row=1)
            app.resources.post_message(event)
            await wait_for(lambda: isinstance(app.screen, ContainerScreen))
            assert app.screen.stream.target.uid == "owned-api"
            assert app.resources.selected_uid == "owned-worker"
            await pilot.press("escape")
