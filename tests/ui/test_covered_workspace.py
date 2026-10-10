"""Covered root views keep transports live and publish their latest state on return."""

import asyncio
from datetime import timedelta

import pytest
from aiohttp import web

from kuberich.ui.chrome import WorkspaceHeader
from kuberich.ui.logs import LogScreen
from kuberich.ui.scopes import ScopeScreen
from tests.support.pods import NOW, pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import wait_for, workspace_api
from tests.ui.test_logs import app_for, ns, open_logs


@pytest.mark.asyncio
@pytest.mark.parametrize("cover", ["selector", "logs", "nested"])
@pytest.mark.parametrize("quit_covered", [False, True])
async def test_covered_workspace_receives_changes_without_painting_and_resumes_latest(
    tmp_path, monkeypatch, cover, quit_covered
):
    events = asyncio.Queue()
    clock = [NOW]
    monkeypatch.setattr("kuberich.ui.pods.utc_now", lambda: clock[0])
    original = pod("first", created=NOW - timedelta(seconds=30))

    async def resources(request):
        if request.path.endswith("/log"):
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(b"owned live log\n")
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.005)
            return response
        if request.path.endswith("/first"):
            return web.json_response(original)
        if "watch" not in request.query:
            return web.json_response(collection(original))
        response = web.StreamResponse()
        await response.prepare(request)
        while request.transport is not None and not request.transport.is_closing():
            try:
                event = await asyncio.wait_for(events.get(), 0.05)
            except TimeoutError:
                continue
            await response.write(frame(event))
        return response

    async with workspace_api(ns, resources) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.pause()
            app.resources.move_cursor(row=0)
            if cover != "selector":
                log_screen = await open_logs(app, pilot)
            if cover != "logs":
                await app.push_screen(ScopeScreen("Owned choice", ("first", "second")))
            await pilot.pause()
            assert str(app.resources.get_cell("owned-first", "restarts")) == "0"
            assert str(app.resources.get_cell("owned-first", "age")) == "30s"

            header_updates = []
            update_identity = WorkspaceHeader.update_identity

            def observed_header(header):
                header_updates.append(header.id)
                update_identity(header)

            monkeypatch.setattr(WorkspaceHeader, "update_identity", observed_header)

            changed = pod("first", restarts=11, created=NOW - timedelta(seconds=30))
            changed["metadata"]["resourceVersion"] = "owned/changed"
            added = pod("second")
            added["metadata"]["resourceVersion"] = "owned/added"
            await events.put({"type": "MODIFIED", "object": changed})
            await events.put({"type": "ADDED", "object": added})
            await wait_for(
                lambda: (
                    app.workspace.store.observation.snapshot is not None
                    and app.workspace.store.observation.snapshot.resource_version == "owned/added"
                )
            )
            clock[0] += timedelta(minutes=2)
            app._refresh_tables()
            await pilot.pause()
            assert app.resources.row_count == 1
            assert app.resources.selected_uid == "owned-first"
            assert str(app.resources.get_cell("owned-first", "restarts")) == "0"
            assert str(app.resources.get_cell("owned-first", "age")) == "30s"
            assert header_updates == []
            if cover != "selector":
                assert not log_screen.stale
                assert "owned live log" in log_screen.history.export()

            if not quit_covered:
                if cover != "logs":
                    await pilot.press("escape")
                if cover != "selector":
                    assert isinstance(app.screen, LogScreen)
                    await pilot.press("escape")
                await wait_for(lambda: app.resources.row_count == 2)
                await pilot.pause()
                assert str(app.resources.get_cell("owned-first", "restarts")) == "11"
                assert str(app.resources.get_cell("owned-first", "age")) == "2m"
                assert app.resources.selected_uid == "owned-first"
            await pilot.press("ctrl+q")
        assert app._render_task.done() and app._view_task.done()
        assert not app._pod_projection._cache and app.sessions.client is None
