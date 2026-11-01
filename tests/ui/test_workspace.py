"""The terminal observes only its current scope and exposes stale/error recovery."""

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Static

from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.views import ViewStatus
from kuberich.services.workspace import ViewSubscription
from kuberich.ui.app import KubeRichApp
from kuberich.ui.scopes import ConnectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, item
from tests.support.workers import CoroutineCalls
from tests.support.workspace import stable_watch, wait_for, workspace_api


@pytest.fixture
def observers(monkeypatch):
    calls = CoroutineCalls()
    monkeypatch.setattr(ViewSubscription, "__anext__", calls.observe(ViewSubscription.__anext__))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_visible_stale_recovery_status_details_and_namespace_change(
    tmp_path, size, observers
):
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
        app = KubeRichApp(
            Settings(read_only=True), logging.Logger("view"), catalog=catalog_fixture(tmp_path, url)
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.STALE)
            await pilot.pause()
            assert "Stale resource data" in str(app.status.content)
            assert "Read-only" in str(app.status.content)
            assert "Insecure transport" in str(app.status.content)
            assert "Stale resource data" in str(app.query_one("#empty-title", Static).content)
            assert app.workspace.store.observation.snapshot.items and app.resources.row_count == 1
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
            await wait_for(
                lambda: app.state.namespace == "default" and app.state.status is ViewStatus.LIVE
            )
            await pilot.pause()
            assert app.workspace.store.observation.snapshot.items[0].namespace == "default"
            assert str(app.query_one("#namespace", Static).content) == "Namespace: default"
            await pilot.press("slash", *"team", "escape", "escape")
            assert "Live" in str(app.status.content)
            app.save_screenshot(filename=f"workspace-live-{size[0]}.svg", path=str(evidence))
            await pilot.press("ctrl+q")
        assert app.sessions.client is None
        assert observers.tasks and all(task.done() for task in observers.tasks)
        assert (
            app.workspace.ownership.watch_count == app.workspace.ownership.subscription_count == 0
        )
        assert app.workspace.ownership.close_complete


@pytest.mark.asyncio
async def test_ui_rejects_a_delayed_old_subscription_observation(tmp_path, monkeypatch):
    async def handler(request):
        return namespaces("team", "default")

    async with workspace_api(handler) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("late-view"), catalog=catalog_fixture(tmp_path, url)
        )
        subscriptions = []
        subscribe = app.workspace.subscribe

        def capture_subscription():
            subscription = subscribe()
            subscriptions.append(subscription)
            return subscription

        monkeypatch.setattr(app.workspace, "subscribe", capture_subscription)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            await pilot.pause()
            current = app.workspace.store.observation
            assert len(subscriptions) == 1
            subscription = subscriptions[0]
            subscription.offer(replace(current, revision=current.revision - 1, context="obsolete"))
            await pilot.pause()
            assert str(app.query_one("#context", Static).content) == "Context: kuberich-test-one"
            assert app.workspace.store.observation is current
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
async def test_unexpected_subscription_render_error_reaches_sanitized_hook_and_cleans_up(
    tmp_path, monkeypatch, observers
):
    from tests.support.watches import frame

    async def handler(request):
        return namespaces("team")

    streams = []
    closed = asyncio.Event()
    delivered = []
    next_observation = ViewSubscription.__anext__

    async def observed(subscription):
        value = await next_observation(subscription)
        delivered.append(value)
        return value

    monkeypatch.setattr(ViewSubscription, "__anext__", observed)

    async def resources(request):
        if "watch" not in request.query:
            return web.json_response(collection(item("initial")))
        response = web.StreamResponse()
        await response.prepare(request)
        streams.append(response)
        try:
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.005)
        finally:
            closed.set()
        return response

    async with workspace_api(handler, resources) as url:
        app = KubeRichApp(
            Settings(), logging.Logger("render-failure"), catalog=catalog_fixture(tmp_path, url)
        )
        update = app.status.update_text
        failed = False

        def broken(content):
            if failed:
                raise RuntimeError("opaque-render-value")
            update(content)

        monkeypatch.setattr(app.status, "update_text", broken)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.state.status is ViewStatus.LIVE and bool(streams))
            await pilot.pause()
            owner = observers.latest
            client = app.sessions.client
            assert owner is not None and not owner.done() and client is not None
            failed = True
            app.request_render()
            panel = app.query_one("#view-error")
            await wait_for(lambda: panel.has_class("failed"))
            assert "opaque-render-value" not in app.export_screenshot()
            failed = False
            monkeypatch.setattr(app.status, "update_text", update)
            changed = item("after-error")
            changed["metadata"]["resourceVersion"] = "after-error-version"
            await streams[0].write(frame({"type": "ADDED", "object": changed}))
            await wait_for(
                lambda: any(
                    value.snapshot is not None and len(value.snapshot.items) == 2
                    for value in delivered
                )
            )
            assert owner is observers.latest and not owner.done()
            assert app.sessions.client is client and len(streams) == 1
            assert await pilot.click("#view-error-retry")
            await wait_for(lambda: not panel.has_class("failed") and app.resources.row_count == 2)
            assert "2 pods" in str(app.status.content)
        assert app.sessions.client is None and app.processes.active_count == 0
        assert observers.tasks and all(task.done() for task in observers.tasks)
        assert (
            app.workspace.ownership.watch_count == app.workspace.ownership.subscription_count == 0
        )
        assert app.workspace.ownership.close_complete
        await wait_for(closed.is_set)


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
        app = KubeRichApp(
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
            await wait_for(
                lambda: app.state.namespace == "allowed" and app.state.status is ViewStatus.LIVE
            )
            await pilot.pause()
            assert app.workspace.store.observation.snapshot.items[0].namespace == "allowed"
            assert "Live" in str(app.status.content)
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
@pytest.mark.parametrize("size,count", [((40, 12), 0), ((100, 30), 1)])
async def test_quiet_renewal_preserves_live_preview_copy_and_selected_context(
    tmp_path, monkeypatch, size, count, observers
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
        app = KubeRichApp(
            Settings(),
            logging.Logger("quiet-preview"),
            catalog=catalog_fixture(tmp_path, url),
            # A UI trial qualifies quiet EOF renewal, not a 250 ms paint/header
            # race on a contended host. Keep actual 1 s server expiry/renewal;
            # short ordinary-header versus quiet-body deadlines have contract tests.
            connection=ConnectionRequest(timeout=1.0),
        )
        show = app.status.update_text

        def record(content):
            displayed.append(str(content))
            show(content)

        monkeypatch.setattr(app.status, "update_text", record)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: len(versions) >= 3)
            await pilot.pause()
            assert str(app.query_one("#empty-title", Static).content) == (
                "Pods ready" if count else "No pods in this scope"
            )
            description = str(app.query_one("#empty-description", Static).content)
            assert "No pods were returned" in description
            assert ":ctx contexts" in description
            assert str(app.query_one("#context", Static).content) == "Context: kuberich-test-one"
            assert f"Live · {count} pods" in str(app.status.content)
            assert len(set(versions)) == 1
            assert displayed and all(
                not any(
                    marker in content
                    for marker in (
                        "Stale resource data",
                        "Resource data unavailable",
                        "Reloading snapshot",
                    )
                )
                for content in displayed
            )
            assert app.resources.row_count == count
            evidence = Path("artifacts/ui").resolve()
            evidence.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"workspace-quiet-live-{size[0]}.svg", path=str(evidence))
            await pilot.press("ctrl+q")
        assert app.sessions.client is None
        assert observers.tasks and all(task.done() for task in observers.tasks)
        assert app.workspace.ownership.close_complete
