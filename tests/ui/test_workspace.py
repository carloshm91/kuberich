"""The terminal observes only its current scope and exposes stale/error recovery."""

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Static

from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionRequest
from kubetrol.domain.views import ViewStatus
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.scopes import ConnectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, item
from tests.support.workspace import stable_watch, wait_for, workspace_api


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_visible_stale_recovery_status_details_and_namespace_change(tmp_path, size):
    failing = asyncio.Event()
    failing.set()

    async def handler(request):
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            if failing.is_set():
                return web.Response(status=503, text="opaque-private-server-body")
            return await stable_watch(request)
        namespace = request.path.split("/")[4]
        return web.json_response(collection(item(namespace=namespace)))

    async with workspace_api(handler, resources) as url:
        app = KubetrolApp(
            Settings(read_only=True), logging.Logger("view"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.STALE)
            await pilot.pause()
            assert "Stale resource data" in str(app.status.content)
            assert "Read-only" in str(app.status.content)
            assert "Insecure transport" in str(app.status.content)
            assert "Stale resource data" in str(app.query_one("#empty-title", Static).content)
            assert app.workspace.store.observation.snapshot.items and app.resources.row_count == 0
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"workspace-stale-{size[0]}.svg", path=str(evidence))
            await pilot.press("colon", *"status", "enter")
            assert isinstance(app.screen, ConnectionScreen)
            assert "503" in str(app.screen.query_one("#connection-details", Static).content)
            assert "opaque-private" not in str(
                app.screen.query_one("#connection-details", Static).content
            )
            await pilot.press("escape")
            failing.clear()
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert "1 pods" in str(app.status.content) and "Live" in str(app.status.content)
            await pilot.press("colon", *"ns default", "enter")
            await app._connection_task
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert app.workspace.store.observation.snapshot.items[0].namespace == "default"
            assert str(app.query_one("#namespace", Static).content) == "Namespace: default"
            await pilot.press("slash", *"team", "escape", "escape")
            assert "Live" in str(app.status.content)
            app.save_screenshot(filename=f"workspace-live-{size[0]}.svg", path=str(evidence))
            await pilot.press("ctrl+q")
        assert app.sessions.client is None and app._view_task.done()
        assert app.workspace._watch is None and not app.workspace._subscriptions


@pytest.mark.asyncio
async def test_ui_rejects_a_delayed_old_subscription_observation(tmp_path):
    async def handler(request):
        return namespaces("team", "default")

    async with workspace_api(handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("late-view"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            current = app.workspace.store.observation
            subscription = next(iter(app.workspace._subscriptions))
            subscription.offer(replace(current, revision=current.revision - 1, context="obsolete"))
            await pilot.pause()
            assert str(app.query_one("#context", Static).content) == "Context: kubetrol-test-one"
            assert app.workspace.store.observation is current
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
async def test_unexpected_subscription_render_error_reaches_sanitized_hook_and_cleans_up(
    tmp_path, monkeypatch
):
    async def handler(request):
        return namespaces("team")

    def broken(view):
        raise RuntimeError("opaque-render-value")

    async with workspace_api(handler) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("render-failure"), catalog=catalog_fixture(tmp_path, url)
        )
        monkeypatch.setattr(app, "_show_view", broken)
        with pytest.raises(RuntimeError, match="opaque-render-value"):
            async with app.run_test() as pilot:
                await pilot.pause()
        assert app.return_code == 1 and app.sessions.client is None
        assert app._view_task.done() and app.workspace._watch is None


@pytest.mark.asyncio
async def test_denied_pod_list_is_an_error_then_manual_allowed_namespace_recovers(tmp_path):
    async def handler(request):
        return namespaces("team", "allowed")

    async def resources(request):
        if "/allowed/" not in request.path:
            return web.Response(status=403, text="opaque-private-denial-body")
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(item(namespace="allowed")))

    async with workspace_api(handler, resources) as url:
        app = KubetrolApp(
            Settings(), logging.Logger("denied-pods"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            await pilot.pause()
            assert app.workspace.store.observation.snapshot is None
            assert str(app.query_one("#empty-title", Static).content) == "Resource data unavailable"
            assert "403" in str(app.status.content) and "opaque-private" not in str(
                app.status.content
            )
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="workspace-denied-100.svg", path=str(evidence))
            await pilot.press("colon", *"ns allowed", "enter")
            await app._connection_task
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            assert app.workspace.store.observation.snapshot.items[0].namespace == "allowed"
            assert "Live" in str(app.status.content)
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
@pytest.mark.parametrize("size,count", [((40, 12), 0), ((100, 30), 1)])
async def test_quiet_renewal_preserves_live_preview_copy_and_selected_context(
    tmp_path, monkeypatch, size, count
):
    versions, displayed = [], []

    async def handler(request):
        return namespaces("team")

    async def resources(request):
        if "watch" not in request.query:
            return web.json_response(collection(*([item()] if count else [])))
        versions.append(request.query["resourceVersion"])
        response = web.StreamResponse()
        await response.prepare(request)
        await asyncio.sleep(int(request.query["timeoutSeconds"]))
        await response.write_eof()
        return response

    async with workspace_api(handler, resources) as url:
        app = KubetrolApp(
            Settings(),
            logging.Logger("quiet-preview"),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(timeout=0.25),
        )
        show = app._show_view

        def record(view):
            displayed.append(view)
            show(view)

        monkeypatch.setattr(app, "_show_view", record)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: len(versions) >= 3)
            await pilot.pause()
            assert str(app.query_one("#empty-title", Static).content) == "Resource data ready"
            description = str(app.query_one("#empty-description", Static).content)
            assert "Table rows arrive in the next preview" in description
            assert ":ctx choose context" in description
            assert str(app.query_one("#context", Static).content) == "Context: kubetrol-test-one"
            assert f"Live · {count} pods" in str(app.status.content)
            assert len(set(versions)) == 1
            assert displayed and all(
                view.status not in {ViewStatus.STALE, ViewStatus.FAILED, ViewStatus.RELISTING}
                for view in displayed
            )
            assert app.resources.row_count == 0
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"workspace-quiet-live-{size[0]}.svg", path=str(evidence))
            await pilot.press("ctrl+q")
        assert app.sessions.client is None and app._view_task.done()
