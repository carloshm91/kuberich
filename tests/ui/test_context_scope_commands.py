"""Filters on local contexts must not leak into scoped pod commands."""

import pytest
from aiohttp import web

from kubetrol.domain.views import ViewStatus
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["ns default", "po default", "ns *"])
async def test_scoped_namespace_and_pod_commands_leave_context_filter_on_contexts(
    tmp_path, command
):
    async def ns(request):
        return namespaces("team", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        namespace = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        return web.json_response(collection(pod("api", namespace=namespace)))

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("c")
            await wait_for(lambda: app.context_table.row_count == 2)
            await pilot.press("slash", *"owned", "enter", "G")
            selected = app.context_table.capture_viewport().selected
            await pilot.press("colon", *command, "enter")
            await wait_for(
                lambda: (
                    app._resource_name == "pods"
                    and app.workspace.store.observation.status is ViewStatus.LIVE
                )
            )
            assert app.filter_input.value == ""
            await wait_for(lambda: app.resources.row_count == 1)
            assert app.sessions.observation.namespace == (
                None if command.endswith("*") else "default"
            )
            await pilot.press("c")
            await wait_for(
                lambda: app._resource_name == "contexts" and app.context_table.row_count == 2
            )
            await pilot.pause()
            assert (
                app.filter_input.value == "owned"
                and app.context_table.capture_viewport().selected == selected
            )
