"""Pulse drilldowns replace inherited filters and history restores visible preferences."""

import pytest
from aiohttp import web

from kuberich.domain.navigation import Viewport
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app
from tests.ui.test_pulse import roots


@pytest.mark.asyncio
async def test_running_summary_members_survive_inherited_errors_and_toggle_still_works(tmp_path):
    async def ns(request):
        return namespaces("team")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("pods"):
            pending = pod("pending")
            pending["status"]["phase"] = "Pending"
            return web.json_response(collection(pod("ready"), pod("unready", ready=False), pending))
        return web.json_response(collection())

    async with workspace_api(ns, resources, discovery_roots=roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 3)
            await app.run_command("errors")
            await pilot.pause()
            assert app.interactions.errors
            prior = {key.value for key in app.resources.rows}
            assert "owned-ready" not in prior
            await app.run_command("pulse")
            await wait_for(
                lambda: (
                    "pods:pod-running" in app.pulse_table.rows
                    and app.pulse_table.get_cell("pods:pod-running", "VALUE").plain == "2"
                )
            )
            app.pulse_table.restore_viewport(Viewport("pods:pod-running", 0, 0, 0, None))
            await pilot.pause()
            await pilot.press("enter")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count > 0)
            await pilot.pause()
            assert {key.value for key in app.resources.rows} == {"owned-ready", "owned-unready"}
            assert not app.interactions.errors
            await app.run_command("errors")
            await pilot.pause()
            assert app.interactions.errors and "owned-ready" not in {
                key.value for key in app.resources.rows
            }
            await app.run_command("back")
            await wait_for(lambda: app.state.view_kind == "pulse")
            assert app.interactions.errors
            await app.run_command("back")
            await wait_for(lambda: app.state.view_kind == "pods")
            await pilot.pause()
            assert app.interactions.errors and {key.value for key in app.resources.rows} == prior
