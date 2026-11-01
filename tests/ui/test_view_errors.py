"""Public navigation and Retry survive real controller fault injection."""

import asyncio
import logging
from dataclasses import replace

import pytest
from aiohttp import web
from textual.widgets import Input, Static

from kuberich.config.catalog import Entry, KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import ResourceCommand
from kuberich.services.workspace import ViewSubscription
from kuberich.ui.app import KubeRichApp
from kuberich.ui.controllers.pods import PodController
from kuberich.ui.controllers.standard import StandardController
from kuberich.ui.port_forwards import ForwardPrompt, ForwardScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.port_forwards import executable
from tests.support.resources import collection
from tests.support.standard import standard_api
from tests.support.watches import frame
from tests.support.workers import CoroutineCalls
from tests.support.workspace import wait_for, workspace_api


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["project", "filter", "apply"])
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_faulted_view_shows_safe_inline_retry_and_other_view_navigation_still_works(
    monkeypatch, tmp_path, stage, size
):
    original = getattr(PodController, stage)
    broken = True
    calls = []

    async def injected(self, *args):
        calls.append(stage)
        if broken:
            raise RuntimeError("Bearer private-fault-value")
        return await original(self, *args)

    monkeypatch.setattr(PodController, stage, injected)
    catalog = KubeCatalog(
        contexts={"owned": Entry({"cluster": "synthetic", "namespace": "default"}, tmp_path)},
        clusters={"synthetic": Entry({"server": "https://unused.invalid"}, tmp_path)},
    )
    app = KubeRichApp(
        Settings(read_only=True), logging.Logger("owned-view-fault", level=100), catalog=catalog
    )
    async with app.run_test(size=size) as pilot:
        panel = app.query_one("#view-error")
        await wait_for(lambda: panel.has_class("failed"))
        assert len(calls) == 1
        assert "private-fault-value" not in str(panel.query_one(Static).content)
        assert "private-fault-value" not in app.export_screenshot()
        app.filter_input.value = "fresh-observation"
        await pilot.pause()
        assert len(calls) == 1
        await app.run_command("ctx")
        await wait_for(lambda: not panel.has_class("failed"))
        assert app.context_table.display
        await pilot.press("escape")
        await wait_for(lambda: panel.has_class("failed"))
        assert len(calls) == 1
        broken = False
        button = app.query_one("#view-error-retry")
        assert button.visible and button.region.height >= 1
        assert button.region.right <= size[0] and button.region.bottom <= size[1]
        assert await pilot.click("#view-error-retry")
        await wait_for(lambda: not panel.has_class("failed") and len(calls) == 2)
        assert str(app.query_one("#empty-title", Static).content) == "No cluster connection"
        assert app.views.renderer.active_count == 1
    assert app.views.renderer.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["publish", "header"])
async def test_presentation_fault_does_not_end_the_real_watch_or_observation_task(
    tmp_path, monkeypatch, stage
):
    observers = CoroutineCalls()
    delivered = []
    next_observation = ViewSubscription.__anext__

    async def observed(subscription):
        observers.capture()
        value = await next_observation(subscription)
        delivered.append(value)
        return value

    monkeypatch.setattr(ViewSubscription, "__anext__", observed)
    streams = []
    closed = asyncio.Event()
    initial = pod("initial")

    async def resources(request):
        if "watch" not in request.query:
            return web.json_response(collection(initial))
        response = web.StreamResponse()
        await response.prepare(request)
        streams.append(response)
        try:
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.005)
        finally:
            closed.set()
        return response

    async def send(name):
        manifest = pod(name)
        manifest["metadata"]["resourceVersion"] = "version-" + name
        await streams[0].write(frame({"type": "ADDED", "object": manifest}))

    async with workspace_api(lambda _: response_namespaces(), resources) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("owned-presentation-watch", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        broken = False
        failures = []
        publish = app.presenter.publish
        chrome = app.header.chrome

        def injected_publish(request, outcome):
            if stage == "publish" and broken:
                failures.append("publish")
                raise RuntimeError("Bearer private-publisher-value")
            return publish(request, outcome)

        def injected_identity():
            if stage == "header" and broken and asyncio.current_task() is observers.latest:
                failures.append("header")
                raise RuntimeError("Bearer private-header-value")
            return chrome.identity()

        monkeypatch.setattr(app.presenter, "publish", injected_publish)
        app.header.chrome = replace(chrome, identity=injected_identity)
        async with app.run_test() as pilot:
            await wait_for(
                lambda: (
                    app.state.status is ViewStatus.LIVE
                    and app.resources.row_count == 1
                    and bool(streams)
                )
            )
            await pilot.pause()
            owner = observers.latest
            client = app.sessions.client
            assert owner is not None and not owner.done() and client is not None
            broken = True
            await send("second")
            panel = app.query_one("#view-error")
            await wait_for(lambda: panel.has_class("failed"))
            assert failures == [stage]
            assert "private-publisher-value" not in app.export_screenshot()
            assert "private-header-value" not in app.export_screenshot()
            broken = False
            await send("third")
            await wait_for(
                lambda: any(
                    value.snapshot is not None and len(value.snapshot.items) == 3
                    for value in delivered
                )
            )
            await pilot.pause()
            assert owner is observers.latest and not owner.done()
            assert app.sessions.client is client and len(streams) == 1
            assert panel.has_class("failed")
            assert app.views.renderer.active_count == 1
            assert await pilot.click("#view-error-retry")
            await wait_for(lambda: not panel.has_class("failed") and app.resources.row_count == 3)
            await send("fourth")
            await wait_for(lambda: app.resources.row_count == 4)
            assert owner is observers.latest and not owner.done()
        assert app.sessions.client is None and app.processes.active_count == 0
        assert observers.tasks and all(task.done() for task in observers.tasks)
        assert app.views.renderer.active_count == 0
        assert (
            app.workspace.ownership.watch_count == app.workspace.ownership.subscription_count == 0
        )
        assert app.workspace.ownership.close_complete
        await wait_for(closed.is_set)


async def response_namespaces():
    return namespaces("team", "default")


@pytest.mark.asyncio
async def test_projection_failure_keeps_an_actual_forward_child_and_tcp_listener_alive(
    tmp_path, monkeypatch
):
    original = StandardController.project
    broken = False

    async def injected(self, request):
        if broken:
            raise RuntimeError("private-view-fault")
        return await original(self, request)

    monkeypatch.setattr(StandardController, "project", injected)
    async with standard_api(tmp_path) as (url, _):
        app = KubeRichApp(
            Settings(),
            logging.Logger("owned-forward-view-fault", level=100),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=ResourceCommand(RESOURCE_ALIASES["svc"], "team"),
            environment=executable(tmp_path),
            directory=tmp_path,
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            app.screen.query_one("#forward-mappings", Input).value = ":80"
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await wait_for(
                lambda: (
                    bool(app.forwards.infos) and app.forwards.infos[0].state is ForwardState.READY
                )
            )
            ready = app.forwards.infos[0]
            await pilot.press("escape")
            broken = True
            app.request_render()
            await wait_for(lambda: app.query_one("#view-error").has_class("failed"))
            reader, writer = await asyncio.open_connection(ready.address, ready.ports[0].local)
            try:
                writer.write(b"alive")
                await writer.drain()
                assert (
                    await reader.readexactly(len(b"owned-response:alive"))
                    == b"owned-response:alive"
                )
            finally:
                writer.close()
                await writer.wait_closed()
            assert app.forwards.infos[0].state is ForwardState.READY
            assert app.forwards.active_count == 1 and app.processes.active_count > 0
            await app.run_command("ctx")
            await wait_for(lambda: not app.query_one("#view-error").has_class("failed"))
            assert app.forwards.active_count == 1
        assert app.forwards.active_count == app.processes.active_count == 0
