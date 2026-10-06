"""Resource viewer through real sessions, live watches and Textual focus/navigation."""

import asyncio
import logging
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.config.schema import Settings
from kubetrol.domain.views import ViewStatus
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.unit.test_inspection import event


def manifest(name="api", uid=None):
    value = pod(name, uid=uid)
    value["metadata"].update(
        managedFields=[{"manager": "test-manager", "fieldsV1": {}}],
        annotations={"value": "hidden-annotation"},
    )
    value["spec"]["containers"][0]["env"] = [{"name": "VALUE", "value": "hidden-env"}]
    return value


async def ns(request):
    return namespaces("team", "default")


def app_for(tmp_path, url):
    return KubetrolApp(
        Settings(read_only=True),
        logging.Logger("inspection", level=100),
        catalog=catalog_fixture(tmp_path, url),
    )


async def loaded(app):
    await wait_for(
        lambda: (
            app.workspace.store.observation.status is ViewStatus.LIVE
            and app.resources.row_count > 0
        )
    )


async def viewer_loaded(app):
    await wait_for(
        lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
    )
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_yaml_details_events_search_copy_managed_scroll_and_return_keep_table(tmp_path, size):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/events"):
            return web.json_response(collection(event().manifest))
        if request.path.endswith("/pods"):
            return web.json_response(collection(*(manifest(f"pod-{i:03}") for i in range(80))))
        return web.json_response(manifest(request.path.rsplit("/", 1)[1]))

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await loaded(app)
            await pilot.press("s", "S", "pagedown", "end")
            before = app.resources.capture_viewport()
            query, sorting = app.filter_input.value, app.resources.sort_column
            await pilot.press("y")
            screen = await viewer_loaded(app)
            await pilot.pause()
            assert "apiVersion: v1" in screen.viewer.text
            assert "hidden-env" not in screen.viewer.text
            assert screen.viewer.read_only and not screen.viewer.soft_wrap
            assert screen.viewer.content_region.height >= 1
            assert screen.search.region.bottom <= screen.status.region.y
            await pilot.press("m")
            assert "managedFields" in screen.viewer.text and "test-manager" in screen.viewer.text
            await pilot.press("m")
            assert "managedFields" not in screen.viewer.text
            await pilot.press("slash", *"containers", "enter")
            assert app.focused is screen.viewer
            assert screen.viewer.selected_text == "containers"
            await pilot.press("n", "N", "ctrl+y")
            assert app.clipboard == "containers"
            await pilot.press("slash", "ctrl+a", *"absent", "enter")
            assert "No matches" in str(screen.status.content)
            await pilot.press("slash", "y", "d", "e", "m", "n", "colon", "slash")
            assert screen.search.value.endswith("ydemn:/") and len(app.screen_stack) == 2
            await pilot.press("escape")
            assert app.focused is screen.viewer
            await pilot.press("d")
            assert "scheduling" in screen.viewer.text and "containerStatuses" in screen.viewer.text
            await pilot.press("e")
            assert "No related events" in screen.viewer.text  # another UID's event is excluded
            await pilot.click("#show-yaml")
            await pilot.click("#copy-view")
            assert app.clipboard == screen.viewer.text and "hidden-env" not in app.clipboard
            await pilot.press("pagedown", "end", "left", "home")
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"inspection-{size[0]}.svg", path=str(evidence))
            await pilot.click("#inspection-back")
            await pilot.pause()
            assert app.resources.capture_viewport() == before
            assert app.filter_input.value == query and app.resources.sort_column == sorting
            await pilot.press("d")
            reopened = await viewer_loaded(app)
            assert reopened.page == "details"
            await pilot.press("escape")
            await wait_for(lambda: reopened._load_task.done())
        assert app.sessions.client is None and screen._load_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("key,status", [("y", 403), ("e", 404)])
async def test_permission_and_unavailable_events_are_visible_without_losing_pod(
    tmp_path, key, status
):
    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/events"):
            return web.Response(status=status)
        return web.json_response(
            collection(manifest()) if request.path.endswith("/pods") else manifest()
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await pilot.press(key)
            screen = await viewer_loaded(app)
            await pilot.press("e")
            assert str(status) in screen.viewer.text
            await pilot.press("y")
            assert "apiVersion" in screen.viewer.text
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_live_updates_under_viewer_uid_recreation_invalidates_and_blocks_copy(tmp_path):
    updates = asyncio.Queue()

    async def handler(request):
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                try:
                    update = await asyncio.wait_for(updates.get(), 0.05)
                except TimeoutError:
                    continue
                await response.write(frame(update))
            return response
        if request.path.endswith("/events"):
            return web.json_response(collection(event().manifest))
        return web.json_response(
            collection(manifest()) if request.path.endswith("/pods") else manifest()
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await pilot.press("e")
            screen = await viewer_loaded(app)
            assert "BackOff" in screen.viewer.text and "[red]literal[/red]" in screen.viewer.text
            value = manifest()
            value["status"]["containerStatuses"][0]["restartCount"] = 9
            value["metadata"]["resourceVersion"] = "modified-version"
            await updates.put({"type": "MODIFIED", "object": value})
            await wait_for(lambda: app.resources._rows["owned-api"].restarts == 9)
            assert screen.result is not None
            value["metadata"]["resourceVersion"] = "deleted-version"
            await updates.put({"type": "DELETED", "object": value})
            await wait_for(lambda: screen.result is None)
            assert screen.viewer.text == "" and "stale" in str(screen.status.content)
            await updates.put({"type": "ADDED", "object": manifest(uid="new-api")})
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("ctrl+y")
            assert app.clipboard == "" and "stale" in str(screen.status.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("switch", [False, True])
async def test_close_or_scope_switch_cancels_pending_read_and_no_late_data(tmp_path, switch):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(manifest()))
        started.set()
        await release.wait()
        return web.json_response(manifest())

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await pilot.press("y")
            screen = app.screen
            await started.wait()
            if switch:
                app._namespace_selected("default")
                await wait_for(lambda: screen._load_task.done())
                assert screen.viewer.text == "" and "stale" in str(screen.status.content)
            else:
                await pilot.press("escape")
                await wait_for(lambda: screen._load_task.done())
            release.set()
        assert screen._load_task.done() and app.sessions.client is None


@pytest.mark.asyncio
async def test_disconnected_view_has_clear_selection_message_and_no_modal():
    app = KubetrolApp(Settings(), logging.Logger("none", level=100))
    async with app.run_test() as pilot:
        await pilot.press("d")
        assert (
            "Select a connected resource" in str(app.status.content) and len(app.screen_stack) == 1
        )


@pytest.mark.asyncio
async def test_resource_permission_error_and_early_copy_do_not_use_table_manifest(tmp_path):
    release = asyncio.Event()

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(manifest()))
        await release.wait()
        return web.Response(status=403)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await pilot.press("y", "ctrl+y", "m")
            screen = app.screen
            assert screen.result is None and app.clipboard == ""
            release.set()
            await wait_for(lambda: screen._load_task.done())
            assert "Permission denied" in str(screen.status.content) and screen.viewer.text == ""
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_unexpected_inspection_failure_propagates_through_safe_app_cleanup(
    tmp_path, monkeypatch
):
    from kubetrol.services.inspection import InspectionService

    async def broken(self):
        raise RuntimeError("owned-inspection-error")

    monkeypatch.setattr(InspectionService, "load", broken)

    async def handler(request):
        return (
            await stable_watch(request)
            if "watch" in request.query
            else web.json_response(collection(manifest()))
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        with pytest.raises(RuntimeError, match="owned-inspection-error"):
            async with app.run_test() as pilot:
                await loaded(app)
                await pilot.press("y")
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_scope_invalidation_then_close_drains_the_same_serializer_once(tmp_path, monkeypatch):
    import threading

    from kubetrol.services import inspection

    started, release, ended = (threading.Event() for _ in range(3))
    unmounting = asyncio.Event()
    original = inspection.inspection_documents
    original_unmount = InspectionScreen.on_unmount

    def controlled(*args):
        started.set()
        try:
            assert release.wait(5)
            return original(*args)
        finally:
            ended.set()

    async def observe_unmount(self):
        unmounting.set()
        await original_unmount(self)

    monkeypatch.setattr(inspection, "inspection_documents", controlled)
    monkeypatch.setattr(InspectionScreen, "on_unmount", observe_unmount)

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/events"):
            return web.json_response(collection())
        return web.json_response(
            collection(manifest()) if request.path.endswith("/pods") else manifest()
        )

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await pilot.press("y")
            screen = app.screen
            await wait_for(started.is_set)
            app._namespace_selected("default")
            await wait_for(lambda: screen._load_task.cancelling() > 0)

            async def monitor():
                try:
                    await unmounting.wait()
                    await asyncio.sleep(0.02)
                    assert not screen._load_task.done() and not ended.is_set()
                finally:
                    release.set()

            check = asyncio.create_task(monitor())
            try:
                await pilot.press("escape")
                await check
            finally:
                release.set()
                await asyncio.gather(check, return_exceptions=True)
            assert ended.is_set() and screen._load_task.done()
