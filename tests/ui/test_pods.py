"""Actual widget behavior under live changes, scrolling and typed sorting."""

import asyncio
import logging
import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from aiohttp import web
from textual.events import Paste

from kuberich.config.schema import Settings
from kuberich.domain.pods import PodColumn, pod_row
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from kuberich.ui.pods import PodCell
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import NOW, pod, record
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api


def rows(count=80):
    return tuple(
        pod_row(
            record(pod(f"pod-{index:03}", restarts=index, created=NOW - timedelta(seconds=index)))
        )
        for index in range(count)
    )


def make_app():
    return KubeRichApp(Settings(), logging.Logger("pod-table", level=100))


def visible_rows(app):
    return [row.key.value for row in app.resources.ordered_rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_incremental_changes_preserve_uid_and_scroll_anchor_and_literal_cells(
    size, monkeypatch
):
    app = make_app()
    baseline = rows()
    baseline = (replace(baseline[0], name="pod-000-" + "x" * 100), *baseline[1:])
    async with app.run_test(size=size) as pilot:
        table = app.resources
        assert await table.apply_rows(baseline, 1, lambda: True)
        table.set_class(True, "populated")
        app.query_one("#empty-state").display = False
        await pilot.pause()
        await pilot.press("pagedown", "pagedown", "end")
        await pilot.pause()
        selected = table.selected_uid
        x, y = table.scroll_x, table.scroll_y
        top_uid = visible_rows(app)[int(y)]
        assert x > 0 and y > 0
        before_cells = tuple(table.get_row(selected))
        added, removed, updated, clears = [], [], [], []
        for method, calls in [
            ("add_row", added),
            ("remove_row", removed),
            ("update_cell", updated),
            ("clear", clears),
        ]:
            original = getattr(table, method)

            def counted(*args, _original=original, _calls=calls, **kwargs):
                _calls.append(args)
                return _original(*args, **kwargs)

            monkeypatch.setattr(table, method, counted)
        changed = list(baseline)
        changed[0] = replace(changed[0], status="[red]CrashLoopBackOff[/red]\x1b[2J", restarts=100)
        changed[1] = replace(changed[1], name="界e\u0301")
        inserted = replace(baseline[0], uid="owned-added", name="aaa-added")
        assert await table.apply_rows((*changed, inserted), 1, lambda: True)
        await pilot.pause()
        assert table.selected_uid == selected
        assert table.scroll_x == x and visible_rows(app)[int(table.scroll_y)] == top_uid
        assert tuple(table.get_row(selected)) == before_cells
        assert len(added) == 1 and not removed and not clears
        assert {args[0] for args in updated} <= {baseline[0].uid, baseline[1].uid}
        value = table.get_cell(baseline[0].uid, "status")
        assert "[red]" in str(value) and "\x1b" not in str(value)
        assert value.__rich__().spans == []
        evidence = Path("artifacts/ui").resolve()
        evidence.mkdir(parents=True, exist_ok=True)
        app.save_screenshot(filename=f"pods-patched-{size[0]}.svg", path=str(evidence))
        await pilot.press("home", "s", "s", "s")
        assert table.sort_column is PodColumn.RESTARTS
        assert table.selected_uid == selected
        counts = [table._rows[uid].restarts for uid in visible_rows(app)]
        assert counts == sorted(counts)
        await pilot.press("S")
        assert table.descending and table.selected_uid == selected
        assert [table._rows[uid].restarts for uid in visible_rows(app)] == sorted(
            counts, reverse=True
        )
        app.save_screenshot(filename=f"pods-sorted-{size[0]}.svg", path=str(evidence))


@pytest.mark.asyncio
async def test_selected_deletion_recreation_and_empty_snapshot_are_deterministic():
    app = make_app()
    baseline = rows(4)
    async with app.run_test() as pilot:
        table = app.resources
        await table.apply_rows(baseline, 1, lambda: True)
        table.move_cursor(row=1)
        await pilot.pause()
        assert table.selected_uid == baseline[1].uid
        await table.apply_rows((baseline[0], baseline[2], baseline[3]), 1, lambda: True)
        assert table.selected_uid == baseline[2].uid
        recreated = replace(baseline[1], uid="owned-new-uid")
        await table.apply_rows((baseline[0], recreated, baseline[2], baseline[3]), 1, lambda: True)
        assert table.selected_uid == baseline[2].uid
        assert baseline[1].uid not in table._rows and recreated.uid in table._rows
        table.move_cursor(row=3)
        await table.apply_rows((baseline[0], recreated, baseline[2]), 1, lambda: True)
        assert table.selected_uid == baseline[2].uid
        await table.apply_rows((), 1, lambda: True)
        assert table.row_count == 0 and table.selected_uid is None
        await table.apply_rows((recreated,), 1, lambda: True)
        assert table.selected_uid == recreated.uid


@pytest.mark.asyncio
async def test_header_click_sort_cycle_and_live_age_updates(monkeypatch):
    app = make_app()
    baseline = rows(3)
    clock = [NOW]
    monkeypatch.setattr("kuberich.ui.pods.utc_now", lambda: clock[0])
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.resources
        await table.apply_rows(baseline, 1, lambda: True)
        await pilot.pause()
        assert await pilot.click("#resources", offset=(3, 0))
        assert table.sort_column is PodColumn.NAMESPACE
        assert "NAMESPACE" in app.query_one("#resource-view").border_subtitle
        assert await pilot.click("#resources", offset=(3, 0))
        assert table.descending
        await pilot.press("s", "s", "s", "s", "s")
        assert table.sort_column is PodColumn.AGE
        assert [str(table.get_cell(row.uid, "age")) for row in baseline] == ["0s", "1s", "2s"]
        clock[0] += timedelta(seconds=60)
        table.refresh_ages()
        assert [str(table.get_cell(row.uid, "age")) for row in baseline] == ["1m", "1m", "1m"]
        await pilot.press("s")
        assert table.sort_column is PodColumn.NAMESPACE
        assert PodCell("owned", "x" * 1000).__rich__().cell_len == 256


@pytest.mark.asyncio
async def test_large_batch_yields_and_a_new_revision_aborts_pending_old_rows(monkeypatch):
    app = make_app()
    async with app.run_test() as pilot:
        table = app.resources
        alive = [True]
        original = table.add_row

        def add(*args, **kwargs):
            result = original(*args, **kwargs)
            if table.row_count == 128:
                asyncio.get_running_loop().call_soon(lambda: alive.__setitem__(0, False))
            return result

        monkeypatch.setattr(table, "add_row", add)
        assert not await table.apply_rows(rows(1000), 1, lambda: alive[0])
        assert table.row_count == 128
        assert not await table.apply_rows(rows(1), 1, lambda: False)
        monkeypatch.setattr(table, "add_row", original)
        assert await table.apply_rows(rows(1), 2, lambda: True)
        await pilot.pause()
        assert table.row_count == 1 and table.selected_uid == "owned-pod-000"
        assert table.scroll_x == 0 and table.scroll_y == 0


@pytest.mark.asyncio
async def test_completed_patch_is_rejected_if_revision_changes_at_final_yield():
    app = make_app()
    async with app.run_test():
        alive = [True]
        task = asyncio.create_task(app.resources.apply_rows(rows(1), 1, lambda: alive[0]))
        await asyncio.sleep(0)
        alive[0] = False
        assert await task is False


@pytest.mark.asyncio
async def test_http_watch_changes_reach_cells_and_scope_replacement_clears_old_uids(tmp_path):
    events = asyncio.Queue()
    opened = asyncio.Event()

    async def namespace_handler(request):
        return namespaces("team", "default")

    async def resource_handler(request):
        scope = request.path.split("/")[4]
        if "watch" not in request.query:
            return web.json_response(
                collection(
                    pod("first", namespace=scope, uid=f"owned-{scope}"),
                    pod("second", namespace=scope, uid=f"second-{scope}"),
                )
            )
        if scope != "team":
            return await stable_watch(request)
        response = web.StreamResponse()
        await response.prepare(request)
        opened.set()
        while request.transport is not None and not request.transport.is_closing():
            try:
                event = await asyncio.wait_for(events.get(), 0.05)
            except TimeoutError:
                continue
            await response.write(frame(event))
        return response

    async with workspace_api(namespace_handler, resource_handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("live-pod-rows"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await opened.wait()
            await wait_for(lambda: app.resources.row_count == 2)
            await pilot.pause()
            assert app.resources.selected_uid == "owned-team"
            changed = pod("first", uid="owned-team", restarts=10, ready=False)
            changed["status"]["containerStatuses"][0]["state"] = {
                "waiting": {"reason": "CrashLoopBackOff"}
            }
            changed["metadata"]["resourceVersion"] = "opaque/modified"
            await events.put({"type": "MODIFIED", "object": changed})
            await wait_for(lambda: str(app.resources.get_cell("owned-team", "restarts")) == "10")
            assert str(app.resources.get_cell("owned-team", "status")) == "CrashLoopBackOff"
            assert str(app.resources.get_cell("owned-team", "ready")) == "0/1"
            assert app.resources.selected_uid == "owned-team"
            changed["metadata"]["resourceVersion"] = "opaque/deleted"
            await events.put({"type": "DELETED", "object": changed})
            await wait_for(lambda: app.resources.row_count == 1)
            assert app.resources.selected_uid == "second-team"
            recreated = pod("first", uid="owned-recreated")
            recreated["metadata"]["resourceVersion"] = "opaque/recreated"
            await events.put({"type": "ADDED", "object": recreated})
            await wait_for(lambda: app.resources.row_count == 2)
            assert app.resources.selected_uid == "second-team"
            assert "owned-team" not in visible_rows(app)
            await pilot.press("colon", *"ns default", "enter")
            await wait_for(lambda: set(visible_rows(app)) == {"owned-default", "second-default"})
            await pilot.pause()
            assert app.workspace.store.observation.status is ViewStatus.LIVE
            assert "Namespace: default" in str(app.query_one("#namespace").content)
            await pilot.press("ctrl+q")
        assert (
            not app._pod_projection._cache and app._view_task.done() and app.sessions.client is None
        )


@pytest.mark.asyncio
async def test_namespace_switch_remains_responsive_and_rejects_a_blocked_old_projection(
    tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()

    async def namespace_handler(request):
        return namespaces("team", "default")

    async def resource_handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        scope = request.path.split("/")[4]
        return web.json_response(collection(pod("owned", namespace=scope, uid=f"owned-{scope}")))

    async with workspace_api(namespace_handler, resource_handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("blocked-projection"), catalog=catalog_fixture(tmp_path, url)
        )
        project = app._pod_projection._project

        def blocked(value):
            if value.namespace == "team":
                started.set()
                assert release.wait(5)
            return project(value)

        monkeypatch.setattr(app._pod_projection, "_project", blocked)
        async with app.run_test() as pilot:
            try:
                await wait_for(started.is_set)
                await pilot.press("colon")
                # Keep the five-second fault fixture independent of per-key Pilot delays.
                app.command_input.post_message(Paste("ns default"))
                await pilot.pause()
                await pilot.press("enter")
                await wait_for(
                    lambda: (
                        app.workspace.store.observation.status is ViewStatus.LIVE
                        and app.workspace.store.observation.connection.namespace == "default"
                    )
                )
                assert app.resources.row_count == 0
                assert str(app.query_one("#namespace").content) == "Namespace: default"
            finally:
                release.set()
            await wait_for(lambda: visible_rows(app) == ["owned-default"])
            assert "owned-team" not in app.resources._rows
            await pilot.press("ctrl+q")
        assert app._view_task.done() and not app._pod_projection._cache
